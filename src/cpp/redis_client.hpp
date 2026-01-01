#pragma once
#include <string>
#include <vector>
#include <memory>
#include <mutex>
#include <hiredis.h>

// 1. HELPER: A smart pointer that automatically calls 'freeReplyObject'
//    when it goes out of scope. Zero overhead.
struct ReplyDeleter {
    void operator()(redisReply* r) {
        if (r) freeReplyObject(r);
    }
};

using Reply = std::unique_ptr<redisReply, ReplyDeleter>;


class RedisClient {
public:
    RedisClient(std::string host, int port, int timeout_ms = 100);
    ~RedisClient();

    // The Main Interface
    bool connect();
    
    // Run the GCRA script
    // Returns: long long (the new TAT) or -1 on error
    long long eval_gcra(const std::string& script_sha, 
                        const std::string& script_content, 
                        const std::string& key, 
                        int burst, 
                        int rate, 
                        int period);

private:
    std::string host_;
    int port_;
    int timeout_ms_;
    
    // Raw pointer to the connection (managed manually by this class)
    redisContext* context_ = nullptr; 
    
    // Mutex to make this thread-safe if multiple Python threads hit it
    std::mutex mutex_;

    // Internal helper to send commands safely
    Reply send_command(const char* format, ...);
};