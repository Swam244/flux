#include <pybind11/pybind11.h>
#include <hiredis.h>
#include <fmt/core.h>
#include <string>
#include <vector>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <iostream>
#include <thread>
#include <chrono>
#include <functional>
#include <spdlog/spdlog.h>
#include <spdlog/sinks/basic_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

namespace py = pybind11;

/**
 * REDIS CONNECTION POOL
    1. Pre-allocates 'pool_size' connections.
    2. Uses a condition_variable to block threads when the pool is empty.
    3. Uses a 'Guard' pattern to auto-return connections.
 */
class RedisClient {
private:
    std::string host;
    int port;
    int timeout_ms;
    
    std::queue<redisContext*> connection_pool; // connection pool queue
    size_t pool_size;
    
    std::mutex pool_mutex;    // Thread Safety
    std::condition_variable pool_cv;
    bool shutting_down = false;

    // Helper: Create a single raw connection
    redisContext* create_connection() {
        struct timeval timeout = { 0, timeout_ms * 1000 };
        redisContext* ctx = redisConnectWithTimeout(host.c_str(), port, timeout);
        
        if (ctx == nullptr || ctx->err) {
            std::string err = ctx ? ctx->errstr : "Allocation failure";
            if (ctx) redisFree(ctx);
            throw std::runtime_error(fmt::format("Redis Connection Failed: {}", err));
        }
        return ctx;
    }

    // Helper: Initialize logging (Singleton-ish but reconfigurable)
    void setup_logging(const std::string& log_path) {
        // Only re-initialize if the logger doesn't exist or we want to support changing files
        // For simplicity, we'll drop and recreate to support the test case requirements.
        if (spdlog::get("flux")) {
            spdlog::drop("flux");
        }

        try {
            auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
            // Use 'false' to APPEND to the log file instead of overwriting it
            auto file_sink = std::make_shared<spdlog::sinks::basic_file_sink_mt>(log_path, false); 
            
            std::vector<spdlog::sink_ptr> sinks {console_sink, file_sink};
            auto logger = std::make_shared<spdlog::logger>("flux", sinks.begin(), sinks.end());
            
            spdlog::set_default_logger(logger);
            spdlog::set_level(spdlog::level::debug);
            spdlog::flush_on(spdlog::level::debug);
            
            spdlog::info("Flux logging initialized. Writing to console and {}", log_path);
        } catch (const spdlog::spdlog_ex& ex) {
            std::cerr << "Log init failed: " << ex.what() << std::endl;
        }
    }

public:
    // Constructor: Builds the pool immediately (Warm start)
    RedisClient(std::string host = "127.0.0.1", int port = 6379, size_t pool_size = 5, int timeout_ms = 200, std::string log_path = "flux_debug.log") 
        : host(host), port(port), pool_size(pool_size), timeout_ms(timeout_ms) {
        
        setup_logging(log_path);
        spdlog::debug("Initializing RedisClient with pool_size={}", pool_size);

        for (size_t i = 0; i < pool_size; i++) {
            connection_pool.push(create_connection());
        }
    }

    // Destructor: Drains the pool and closes all sockets
    ~RedisClient() {
        std::lock_guard<std::mutex> lock(pool_mutex);
        shutting_down = true;
        while (!connection_pool.empty()) {
            redisFree(connection_pool.front());
            connection_pool.pop();
        }
    }

    /**
     * CONNECTION GUARD
     * This ensures that we NEVER lose a connection, even if the code crashes.
     */
    struct ConnectionGuard {
        RedisClient& parent;
        redisContext* ctx;

        // Constructor: Borrows from pool
        ConnectionGuard(RedisClient& client) : parent(client) {
            std::unique_lock<std::mutex> lock(parent.pool_mutex);
            
            // Wait until a connection is available (Blocking)
            parent.pool_cv.wait(lock, [&] { 
                return !parent.connection_pool.empty() || parent.shutting_down; 
            });

            if (parent.shutting_down) throw std::runtime_error("Client is shutting down");

            ctx = parent.connection_pool.front();
            parent.connection_pool.pop();
        }

        ~ConnectionGuard() {
            std::lock_guard<std::mutex> lock(parent.pool_mutex);
            parent.connection_pool.push(ctx);
            parent.pool_cv.notify_one(); // Wake up a waiting thread
        }
    };

    // ----------------------------------------------------------------
    // GENERIC RETRY WRAPPER
    // ----------------------------------------------------------------
    template <typename Func>
    typename std::invoke_result<Func, redisContext*>::type 
    execute_with_retry(Func func, int max_retries = 3, int base_delay_ms = 50) {
        int attempt = 0;
        while (true) {
            try {
                // 1. Acquire connection (Blocks if pool is full)
                ConnectionGuard guard(*this);
                
                // 2. Execute the command
                return func(guard.ctx);

            } catch (const std::exception& e) {
                attempt++;
                spdlog::warn("Attempt {}/{} failed: {}. Retrying in {}ms...", attempt, max_retries, e.what(), base_delay_ms * attempt);
                
                if (attempt > max_retries) {
                    spdlog::error("All {} attempts failed. Final error: {}", max_retries, e.what());
                    throw; 
                }

                // Simple exponential backoff: 50ms, 100ms, 150ms...
                std::this_thread::sleep_for(std::chrono::milliseconds(base_delay_ms * attempt));
            }
        }
    }

    // ----------------------------------------------------------------
    // PUBLIC COMMANDS (The Interface)
    // ----------------------------------------------------------------

    std::string ping() {
        spdlog::debug("Executing PING command");
        return execute_with_retry([this](redisContext* ctx) -> std::string {
            // Use the connection
            redisReply* reply = (redisReply*)redisCommand(ctx, "PING");
            
            if (!reply) {
                // Throwing here triggers the retry in execute_with_retry
                throw std::runtime_error("Redis command failed (Network error?)");
            }

            std::string response;
            if (reply->type == REDIS_REPLY_STATUS) response = reply->str;
            else response = "UNKNOWN";

            freeReplyObject(reply);
            return response;
        });
    }
};






PYBIND11_MODULE(_flux_core, m) {
    m.doc() = "Flux Core: High-performance C++ Rate Limiter Engine";

    py::class_<RedisClient>(m, "RedisClient")
        .def(py::init([](const std::string& host, int port, int pool_size, int timeout_ms, const std::string& log_path) {
            return new RedisClient(host, port, static_cast<size_t>(pool_size), timeout_ms, log_path);
        }), 
             py::arg("host") = "127.0.0.1", 
             py::arg("port") = 6379,
             py::arg("pool_size") = 5,
             py::arg("timeout_ms") = 200,
             py::arg("log_file") = "flux_debug.log",
             "Initialize Redis Connection Pool")
        .def("ping", &RedisClient::ping, "Thread-safe PING");
}