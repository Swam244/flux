#include <pybind11/pybind11.h>
#include <hiredis.h>
#include <fmt/core.h>
#include <string>
#include <vector>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <iostream>

namespace py = pybind11;

/**
 * REDIS CONNECTION POOL
 * * "Systems Deep" Architecture:
 * 1. Pre-allocates 'pool_size' connections.
 * 2. Uses a condition_variable to block threads when the pool is empty.
 * 3. Uses a 'Guard' pattern to auto-return connections.
 */
class RedisClient {
private:
    std::string host;
    int port;
    int timeout_ms;
    
    // The Pool
    std::queue<redisContext*> connection_pool;
    size_t pool_size;
    
    // Thread Safety
    std::mutex pool_mutex;
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

public:
    // Constructor: Builds the pool immediately (Warm start)
    RedisClient(std::string host = "127.0.0.1", int port = 6379, size_t pool_size = 5, int timeout_ms = 200) 
        : host(host), port(port), pool_size(pool_size), timeout_ms(timeout_ms) {
        
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
     * CONNECTION GUARD (Internal Helper)
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

        // Destructor: Returns to pool
        ~ConnectionGuard() {
            std::lock_guard<std::mutex> lock(parent.pool_mutex);
            parent.connection_pool.push(ctx);
            parent.pool_cv.notify_one(); // Wake up a waiting thread
        }
    };

    // ----------------------------------------------------------------
    // PUBLIC COMMANDS (The Interface)
    // ----------------------------------------------------------------

    std::string ping() {
        // 1. Acquire connection (Blocks if pool is full)
        ConnectionGuard guard(*this); 
        
        // 2. Use the connection (Thread-safe here)
        redisReply* reply = (redisReply*)redisCommand(guard.ctx, "PING");
        
        if (!reply) {
            // Simple retry logic could go here (reconnect and retry)
            throw std::runtime_error("Redis command failed (Network error?)");
        }

        std::string response;
        if (reply->type == REDIS_REPLY_STATUS) response = reply->str;
        else response = "UNKNOWN";

        freeReplyObject(reply);
        
        // 3. Guard destructor runs here -> Connection returns to pool automatically
        return response;
    }
};

PYBIND11_MODULE(_flux_core, m) {
    m.doc() = "Flux Core: High-performance C++ Rate Limiter Engine";

    py::class_<RedisClient>(m, "RedisClient")
        .def(py::init([](const std::string& host, int port, int pool_size, int timeout_ms) {
            return new RedisClient(host, port, static_cast<size_t>(pool_size), timeout_ms);
        }), 
             py::arg("host") = "127.0.0.1", 
             py::arg("port") = 6379,
             py::arg("pool_size") = 5,
             py::arg("timeout_ms") = 200,
             "Initialize Redis Connection Pool")
        .def("ping", &RedisClient::ping, "Thread-safe PING");
}