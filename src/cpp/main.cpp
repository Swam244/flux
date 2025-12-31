#include <pybind11/pybind11.h>
#include <hiredis.h>
#include <fmt/core.h>
#include <string>
#include <stdexcept>

namespace py = pybind11;

/**
 * @brief Low-level Redis wrapper using Hiredis.
 * Manages the raw C connection context and handles memory safety.
 */
class RedisClient {
private:
    redisContext* context = nullptr;
    std::string host;
    int port;

public:
    // RAII: Connect on instantiation
    RedisClient(const std::string& host = "127.0.0.1", int port = 6379) 
        : host(host), port(port) {
        
        // Established connection to Redis
        context = redisConnect(host.c_str(), port);

        if (context == nullptr || context->err) {
            std::string error_msg = context ? context->errstr : "Unknown connection error";
            if (context) {
                redisFree(context);
                context = nullptr;
            }
            // Throwing std::runtime_error propagates to Python as RuntimeError
            throw std::runtime_error(fmt::format("Flux Redis Error: Cannot connect to {}:{}. Reason: {}", 
                                                 host, port, error_msg));
        }
    }

    // RAII: Clean up connection on destruction
    ~RedisClient() {
        if (context) {
            redisFree(context);
        }
    }

    // Basic Command: PING -> PONG
    std::string ping() {
        if (!context) {
            throw std::runtime_error("Redis context is closed.");
        }

        // Send raw command
        auto* reply = static_cast<redisReply*>(redisCommand(context, "PING"));
        
        if (!reply) {
            throw std::runtime_error(fmt::format("Flux Redis Error: Command failed on {}:{}", host, port));
        }

        std::string response;
        if (reply->type == REDIS_REPLY_STATUS) {
            response = reply->str; // Expected: "PONG"
        } else {
            response = fmt::format("Unexpected reply type: {}", reply->type);
        }

        // Hiredis requires manual memory management for replies
        freeReplyObject(reply);
        
        return response;
    }
};

// Python Module Definitions
PYBIND11_MODULE(_flux_core, m) {
    m.doc() = "Flux Core: High-performance C++ Rate Limiter Engine";

    py::class_<RedisClient>(m, "RedisClient")
        .def(py::init<const std::string&, int>(), 
             py::arg("host") = "127.0.0.1", 
             py::arg("port") = 6379,
             "Initialize connection to Redis")
        .def("ping", &RedisClient::ping, "Send a PING command to Redis and return the response");
}