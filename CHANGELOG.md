# Changelog

All notable changes to this project will be documented in this file.

## [0.1.5] - 2026-01-03
### Added
- **Configurable Console Logging**: Added `console_logging` option to `flux.toml` (and `FluxConfig`).
    - Default is `false` (silent stdout).
    - Can be enabled for debugging.
- **Internal**: Updated C++ `RedisClient` to support conditional logging sinks.

## [0.1.4] - 2026-01-03
### Added
- **Graceful Failure (Fail Open)**: Added `fail_silently` option to `flux.toml` (default `true`).
    - If Redis is unreachable, the application will **not crash**.
    - The error will be logged to stderr, and the request will be **allowed**.
- **Robustness**: `RateLimiter.hit()` now catches `ConnectionError` and `RuntimeError`.

## [0.1.3] - 2026-01-03
### Added
- **Auto-Response Handling**: The `@rate_limit` decorator now automatically returns appropriate 429 Error responses for major frameworks:
    - **FastAPI / Starlette**: Returns `JSONResponse`.
    - **Django**: Returns `JsonResponse`.
    - **Flask**: Returns `flask.Response`.
- **UX**: Removed the need for users to implement manual exception handlers for `RateLimitExceeded`.

## [0.1.2] - 2026-01-03
### Fixed
- **Packaging**: Resolved `FileNotFoundError` by correctly bundling Lua scripts (`src/flux/lua`) into the wheel.
- **Build**: Fixed `scikit-build-core` configuration to include package data.

## [0.1.1] - 2026-01-03
### Fixed
- **Release**: Version bump to resolve PyPI file collision errors during initial upload tests.

## [0.1.0] - 2026-01-02
### Added
- **Core Engine**: High-performance C++ Rate Limiter Core (`_flux_core`).
- **Algorithms**: Support for GCRA, Token Bucket, Leaky Bucket, and Fixed Window.
- **Decorators**: `@rate_limit` for easy Python integration.
- **Config**: TOML-based configuration system `flux.toml`.
- **Identity**: Smart identity generation (IP / user-based).
