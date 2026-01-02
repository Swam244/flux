#include "redis_client.hpp"
#include <fmt/core.h>
#include <spdlog/sinks/basic_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <iostream>

// ============================================================================
// RedisClient Implementation
// ============================================================================

RedisClient::RedisClient(std::string host, int port, size_t pool_size, int timeout_ms, std::string log_path) 
    : host(host), port(port), pool_size(pool_size), timeout_ms(timeout_ms) {
    
    setup_logging(log_path);
    spdlog::debug("Initializing RedisClient with pool_size={}", pool_size);

    for (size_t i = 0; i < pool_size; i++) {
        connection_pool.push(create_connection());
    }
}

RedisClient::~RedisClient() {
    std::lock_guard<std::mutex> lock(pool_mutex);
    shutting_down = true;
    while (!connection_pool.empty()) {
        redisFree(connection_pool.front());
        connection_pool.pop();
    }
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

redisContext* RedisClient::create_connection() {
    struct timeval timeout = { 0, timeout_ms * 1000 };
    redisContext* ctx = redisConnectWithTimeout(host.c_str(), port, timeout);
    
    if (ctx == nullptr || ctx->err) {
        std::string err = ctx ? ctx->errstr : "Allocation failure";
        if (ctx) redisFree(ctx);
        throw std::runtime_error(fmt::format("Redis Connection Failed: {}", err));
    }
    return ctx;
}

void RedisClient::setup_logging(const std::string& log_path) {
    if (spdlog::get("flux")) {
        spdlog::drop("flux");
    }

    try {
        auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
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

// ----------------------------------------------------------------------------
// Connection Guard
// ----------------------------------------------------------------------------

RedisClient::ConnectionGuard::ConnectionGuard(RedisClient& client) : parent(client) {
    std::unique_lock<std::mutex> lock(parent.pool_mutex);
    
    parent.pool_cv.wait(lock, [&] { 
        return !parent.connection_pool.empty() || parent.shutting_down; 
    });

    if (parent.shutting_down) throw std::runtime_error("Client is shutting down");

    ctx = parent.connection_pool.front();
    parent.connection_pool.pop();
}

RedisClient::ConnectionGuard::~ConnectionGuard() {
    std::lock_guard<std::mutex> lock(parent.pool_mutex);
    parent.connection_pool.push(ctx);
    parent.pool_cv.notify_one();
}

// ----------------------------------------------------------------------------
// Public API
// ----------------------------------------------------------------------------

std::string RedisClient::ping() {
    spdlog::debug("Executing PING command");
    return execute_with_retry([this](redisContext* ctx) -> std::string {
        redisReply* reply = (redisReply*)redisCommand(ctx, "PING");
        
        if (!reply) {
            throw std::runtime_error("Redis command failed (Network error?)");
        }

        std::string response;
        if (reply->type == REDIS_REPLY_STATUS) response = reply->str;
        else response = "UNKNOWN";

        freeReplyObject(reply);
        return response;
    });
}

std::string RedisClient::load_script(const std::string& script_content) {
    spdlog::debug("load_script: content_len={}", script_content.size());

    return execute_with_retry([&](redisContext* ctx) -> std::string {
        redisReply* reply = (redisReply*)redisCommand(ctx, "SCRIPT LOAD %s", script_content.c_str());

        if (!reply) {
            throw std::runtime_error("Redis SCRIPT LOAD command failed (Network error?)");
        }

        std::string sha;
        if (reply->type == REDIS_REPLY_STRING || reply->type == REDIS_REPLY_STATUS) {
            sha = reply->str;
            spdlog::debug("load_script: Cached successfully. SHA={}", sha);
        } else if (reply->type == REDIS_REPLY_ERROR) {
            std::string error = reply->str;
            freeReplyObject(reply);
            throw std::runtime_error("SCRIPT LOAD error: " + error);
        } else {
            freeReplyObject(reply);
            throw std::runtime_error("Unexpected reply type from SCRIPT LOAD");
        }

        freeReplyObject(reply);
        return sha;
    });
}

std::pair<long long, double> RedisClient::eval_sha(
    const std::string& script_sha,
    const std::vector<std::string>& keys,
    const std::vector<long long>& args
) {
    spdlog::debug("eval_sha: keys={}, args={}, sha={}", keys.size(), args.size(), script_sha);

    return execute_with_retry([&](redisContext* ctx) -> std::pair<long long, double> {
        std::vector<const char*> argv;
        std::vector<size_t> argvlen;
        std::vector<std::string> arg_strings;
        
        argv.push_back("EVALSHA");
        argvlen.push_back(7);
        
        argv.push_back(script_sha.c_str());
        argvlen.push_back(script_sha.size());
        
        arg_strings.push_back(std::to_string(keys.size()));
        argv.push_back(arg_strings.back().c_str());
        argvlen.push_back(arg_strings.back().size());
        
        for (const auto& key : keys) {
            argv.push_back(key.c_str());
            argvlen.push_back(key.size());
        }
        
        for (long long arg : args) {
            arg_strings.push_back(std::to_string(arg));
            argv.push_back(arg_strings.back().c_str());
            argvlen.push_back(arg_strings.back().size());
        }
        
        redisReply* reply = (redisReply*)redisCommandArgv(
            ctx, 
            static_cast<int>(argv.size()), 
            argv.data(), 
            argvlen.data()
        );

        if (!reply) {
            throw std::runtime_error("Redis EVALSHA command failed (Network error?)");
        }

        if (reply->type == REDIS_REPLY_ERROR && 
            std::string(reply->str).find("NOSCRIPT") != std::string::npos) {
            freeReplyObject(reply);
            throw std::runtime_error("NOSCRIPT");
        }

        std::pair<long long, double> result;

        if (reply->type == REDIS_REPLY_ARRAY && reply->elements >= 2) {
            long long status = reply->element[0]->integer;
            long long value = reply->element[1]->integer;
            result = {status, static_cast<double>(value)};
        } else if (reply->type == REDIS_REPLY_ERROR) {
            std::string error = reply->str;
            freeReplyObject(reply);
            throw std::runtime_error("Lua error: " + error);
        } else {
            freeReplyObject(reply);
            throw std::runtime_error("Unexpected reply type");
        }

        freeReplyObject(reply);
        return result;
    });
}



// For backward compatibility.

std::pair<long long, double> RedisClient::eval_script(
    const std::string& script_sha,
    const std::string& script_content,
    const std::vector<std::string>& keys,
    const std::vector<long long>& args
) {
    try {
        return eval_sha(script_sha, keys, args);
    } catch (const std::runtime_error& e) {
        std::string err = e.what();
        if (err == "NOSCRIPT") {
            spdlog::warn("NOSCRIPT received, re-loading script...");
            load_script(script_content);
            return eval_sha(script_sha, keys, args);
        }
        throw;
    }
}