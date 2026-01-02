#pragma once

#include <string>
#include <vector>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <thread>
#include <functional>
#include <hiredis.h>
#include <spdlog/spdlog.h>

class RedisClient {
private:
    std::string host;
    int port;
    int timeout_ms;
    
    std::queue<redisContext*> connection_pool;
    size_t pool_size;
    
    std::mutex pool_mutex;
    std::condition_variable pool_cv;
    bool shutting_down = false;

    // Helper: Create a single raw connection
    redisContext* create_connection();

    // Helper: Initialize logging
    void setup_logging(const std::string& log_path);

public:
    // Constructor: Builds the pool immediately
    RedisClient(std::string host, int port, size_t pool_size, int timeout_ms, std::string log_path);

    // Destructor: Drains the pool
    ~RedisClient();

    // Connection Guard for RAII-style pool borrowing
    struct ConnectionGuard {
        RedisClient& parent;
        redisContext* ctx;
        ConnectionGuard(RedisClient& client);
        ~ConnectionGuard();
    };

    // Generic Retry Wrapper
    template <typename Func>
    typename std::invoke_result<Func, redisContext*>::type 
    execute_with_retry(Func func, int max_retries = 3, int base_delay_ms = 50);

    // Public API
    std::string ping();
    std::string load_script(const std::string& script_content);
    
    std::pair<long long, double> eval_sha(
        const std::string& script_sha,
        const std::vector<std::string>& keys,
        const std::vector<long long>& args
    );

    std::pair<long long, double> eval_script(
        const std::string& script_sha,
        const std::string& script_content,
        const std::vector<std::string>& keys,
        const std::vector<long long>& args,
        const std::string& key_prefix = ""
    );
};

// Template implementation must be in header (or explicitly instantiated)
template <typename Func>
typename std::invoke_result<Func, redisContext*>::type 
RedisClient::execute_with_retry(Func func, int max_retries, int base_delay_ms) {
    int attempt = 0;
    while (true) {
        try {
            ConnectionGuard guard(*this);
            return func(guard.ctx);
        } catch (const std::exception& e) {
            attempt++;
            spdlog::warn("Attempt {}/{} failed: {}. Retrying in {}ms...", attempt, max_retries, e.what(), base_delay_ms * attempt);
            
            if (attempt > max_retries) {
                spdlog::error("All {} attempts failed. Final error: {}", max_retries, e.what());
                throw; 
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(base_delay_ms * attempt));
        }
    }
}