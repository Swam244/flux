# Flux Limiter (Developer Documentation)

**Flux** is a high-performance, framework-agnostic rate limiter for Python, implemented with a C++ core for minimal latency. This repository contains the source code, including the C++ extension and Python bindings.

> **For usage instructions and installation guide, see [PYPI.md](PYPI.md) or the [PyPI page](https://pypi.org/project/flux-limiter/).**

## Architecture

Flux is designed for performance and correctness.

- **Core Logic (C++)**: The rate limiting algorithms (GCRA, Token Bucket, etc.) are implemented in C++ (`src/cpp`) for speed.
- **Redis Integration**: State is maintained in Redis. We use optimized Lua scripts (loaded via C++) to ensure atomicity and reduce network round-trips.
- **Python Bindings**: We use `pybind11` to expose the C++ core to Python.
- **Framework Adapters**: Light wrappers for Django, FastAPI, and Flask extract request information and handle responses.

## Development Setup

### Prerequisites

- **Python**: >= 3.11
- **C++ Compiler**: A compiler supporting C++17 (GCC, Clang, MSVC).
- **CMake**: >= 3.15
- **Redis**: Required for running tests and the example application.

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Start-Flux/flux.git
   cd flux
   ```

2. **Install dependencies**:
   We recommend using `uv` for fast dependency management, but `pip` works too.
   ```bash
   # Using uv
   uv sync
   
   # Using pip
   pip install -e .[dev,test]
   ```

3. **Build the extension**:
   The C++ extension is built automatically during install. If you need to rebuild manually:
   ```bash
   # If using editable install, changes to C++ might need a re-install or build command depending on your setup.
   # Usually:
   pip install -e . --no-build-isolation
   ```

## CLI Reference

Flux includes a CLI tool for management and monitoring.

- **Initialize Config**:
  ```bash
  python -m flux.cli init
  ```
- **Clear Redis Keys**:
  ```bash
  python -m flux.cli clear
  ```
- **Real-time Monitor**:
  Start the text-based UI (TUI) to watch traffic.
  ```bash
  # Ensure your app is running with analytics enabled
  python -m flux.cli monitor
  ```
  python -m flux.cli monitor
  ```

### Analytics Configuration
Flux includes a real-time analytics pipeline powered by Redis Streams. You can configure it in `flux.toml`:

```toml
[analytics]
enabled = true
sample_rate = 1.0   # 1.0 = 100% (default), 0.1 = 10% sampling
port = 4444         # Port for internal analytics API
retention = 100000  # Max events to keep in stream
```
## Testing

We use `pytest`. Ensure Redis is running on localhost:6379 before running tests.

```bash
pytest
```

## Contributing

1. Fork the repo.
2. Create a feature branch.
3. Add tests for your changes.
4. Ensure `pytest` passes.
5. Submit a Pull Request.

## License

MIT
