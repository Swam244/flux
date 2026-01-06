# Contributing to Flux

Flux uses `uv` for dependency management and building.

## Prerequisites

Before starting, ensure you have the following installed:

*   **C++ Compiler**: `g++` (Linux), `clang` (macOS), or MSVC (Windows).
*   **CMake**: Required for building the C++ core (`sudo apt install cmake` on Ubuntu).
*   **Python 3.11+**: The core requires a modern Python version.
*   **uv**: Our package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

## Running Redis

Flux requires a running Redis instance for tests and usage.

1.  **Install Redis**
    *   Ubuntu/Debian: `sudo apt install redis-server`
    *   macOS: `brew install redis`
    *   Windows: Use WSL2 or Docker (`docker run -p 6379:6379 redis`)

2.  **In Ubuntu --> Start the Server**
    Open a new terminal and run:
    ```bash
    redis-server --port 6379
    ```
## Development Setup

1.  **Clone the repository**
    ```bash
    git clone https://github.com/Swam244/flux.git
    cd flux
    ```

2.  **Create a venv and Sync dependencies**
    This will install all development and runtime dependencies.
    ```bash
    uv sync --all-extras
    ```

3.  **Build the project**
    To compile the C++ core and build the package:
    ```bash
    uv build
    ```


## Running Tests

Once the environment is set up, you can run the test suite:

```bash
uv run pytest
```

## Reference Environment

This project is actively developed and tested in the following environment. If you encounter build issues, comparing against this configuration might help:

*   **OS**: Ubuntu 22.04.5 LTS (Jammy Jellyfish)
*   **Kernel**: Linux
*   **Python**: 3.11+
*   **Compiler**: GCC/G++ 11.4.0
*   **CMake**: Latest version recommended

