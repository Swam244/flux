#include "redis_client.hpp"
#include <stdexcept>
#include <iostream>
#include <spdlog/spdlog.h>

RedisClient::RedisClient(std::string host, int port, int timeout_ms)
    : host_(std::move(host)), port_(port), timeout_ms_(timeout_ms) {
    spdlog::debug("RedisClient initialized: host={}, port={}, timeout_ms={}", host_, port_, timeout_ms_);
}

RedisClient::~RedisClient() {
    if (context_) {
        spdlog::debug("RedisClient: Closing connection to {}:{}", host_, port_);
        redisFree(context_); // Clean up the raw connection
    }
}

bool RedisClient::connect() {

    // return if already connected 
    if (context_ && context_->err == 0) {
        spdlog::debug("RedisClient: Already connected to {}:{}", host_, port_);
        return true;
    }
    
    if (context_) {
        spdlog::warn("RedisClient: Previous connection had errors, reconnecting to {}:{}", host_, port_);
        redisFree(context_);
    }

    spdlog::info("RedisClient: Attempting to connect to {}:{} (timeout: {}ms)", host_, port_, timeout_ms_);
    struct timeval timeout = { 0, timeout_ms_ * 1000 };
    context_ = redisConnectWithTimeout(host_.c_str(), port_, timeout);

    if (context_ == nullptr || context_->err) {
        if (context_) {
            spdlog::error("RedisClient: Connection failed to {}:{} - {}", host_, port_, context_->errstr);
            redisFree(context_);
            context_ = nullptr;
        } else {
            spdlog::error("RedisClient: Failed to allocate context for {}:{}", host_, port_);
        }
        return false;
    }
    
    spdlog::info("RedisClient: Successfully connected to {}:{}", host_, port_);
    return true;
}



// LUA Script Runner
long long RedisClient::eval_gcra(const std::string& script_sha, 
                                 const std::string& script_content, 
                                 const std::string& key, 
                                 int burst, 
                                 int rate, 
                                 int period) {

    std::lock_guard<std::mutex> lock(mutex_);

    spdlog::debug("RedisClient: eval_gcra called for key={}, burst={}, rate={}, period={}", key, burst, rate, period);

    if (!connect()) {
        spdlog::error("RedisClient: Connection failed, cannot execute eval_gcra for key={}", key);
        return -1; // Auto-reconnect attempt
    }

    // 1. OPTIMISTIC: Try EVALSHA (Fastest, saves bandwidth)
    spdlog::debug("RedisClient: Attempting EVALSHA for key={} with script_sha={}", key, script_sha);
    Reply reply( (redisReply*)redisCommand(context_, "EVALSHA %s 1 %s %d %d %d", script_sha.c_str(), key.c_str(), burst, rate, period) );

    // 2. CHECK: Did it fail because the script is missing?
    if (reply && reply->type == REDIS_REPLY_ERROR && 
        std::string(reply->str).find("NOSCRIPT") != std::string::npos) {
        
        spdlog::warn("RedisClient: Script missing (NOSCRIPT), falling back to EVAL for key={}", key);

        // 3. FALLBACK: Load script and run (Slower, but self-healing)
        reply.reset( (redisReply*)redisCommand(context_, 
            "EVAL %s 1 %s %d %d %d", 
            script_content.c_str(), key.c_str(), burst, rate, period) );
    }

    // 4. VALIDATE result
    if (!reply || reply->type != REDIS_REPLY_INTEGER) {
        if (reply) {
            spdlog::error("RedisClient: eval_gcra failed for key={} - Error: {}", key, reply->str);
        } else {
            spdlog::error("RedisClient: eval_gcra failed for key={} - No reply received", key);
        }
        return -1;
    }

    spdlog::debug("RedisClient: eval_gcra succeeded for key={}, returned TAT={}", key, reply->integer);
    return reply->integer; // Return the new TAT or retry time
}