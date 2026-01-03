#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "redis_client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_flux_core, m) {
    m.doc() = "Flux Core: High-performance C++ Rate Limiter Engine";

    py::class_<RedisClient>(m, "RedisClient")
        .def(py::init([](const std::string& host, int port, int pool_size, int timeout_ms, const std::string& log_path, bool enable_console_logging) {
            return new RedisClient(host, port, static_cast<size_t>(pool_size), timeout_ms, log_path, enable_console_logging);
        }), 
             py::arg("host") = "127.0.0.1", 
             py::arg("port") = 6379,
             py::arg("pool_size") = 5,
             py::arg("timeout_ms") = 200,
             py::arg("log_file") = "flux_debug.log",
             py::arg("enable_console_logging") = false,
             "Initialize Redis Connection Pool")
        .def("ping", &RedisClient::ping, "Thread-safe PING")
        .def("load_script", &RedisClient::load_script, "Cache Lua script on Redis. Returns SHA1.")
        .def("eval_sha", &RedisClient::eval_sha, "Execute cached script by SHA1.")
        .def("eval_script", &RedisClient::eval_script,
             py::arg("script_sha"),
             py::arg("script_content"),
             py::arg("keys"),
             py::arg("args"),
             py::arg("key_prefix") = "",
             "Execute with automatic fallback (EVALSHA -> SCRIPT LOAD -> EVALSHA). Hashing is performed internally.");
}