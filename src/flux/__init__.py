"""
Flux - Simple, high-performance, framework-agnostic rate limiting.

Works with Django, FastAPI, Flask, or any Python application.

Basic Usage:
    >>> from flux import RateLimiter
    >>> 
    >>> limiter = RateLimiter(requests=100, period=60)
    >>> 
    >>> if limiter.is_allowed("user:123"):
    ...     process()

From TOML Config:
    >>> from flux import RateLimiter
    >>> 
    >>> # Uses [rate_limits.api] from flux.toml
    >>> limiter = RateLimiter.from_config("api")
    >>> result = limiter.check("user:123")

FastAPI Example:
    >>> from flux import RateLimiter
    >>> limiter = RateLimiter()
    >>> 
    >>> @app.get("/api/data")
    >>> async def get_data(request: Request):
    ...     result = limiter.check(f"user:{request.user.id}")
    ...     if not result.allowed:
    ...         raise HTTPException(429, headers=result.to_headers())
    ...     return {"data": "..."}

Flask Example:
    >>> limiter = RateLimiter.from_config("api")
    >>> 
    >>> @app.before_request
    >>> def check_rate_limit():
    ...     result = limiter.check(request.remote_addr)
    ...     if not result.allowed:
    ...         return "Too Many Requests", 429, result.to_headers()

Django Middleware:
    # settings.py
    MIDDLEWARE = ['flux.middleware.FluxMiddleware', ...]
    FLUX_REQUESTS = 1000
    FLUX_PERIOD = 3600
    FLUX_KEY_FUNC = lambda request: f"user:{request.user.id}"

Supported Policies:
    - GCRA (Generic Cell Rate Algorithm) - smooth, recommended
    - Token Bucket - good for bursty traffic
    - Leaky Bucket - smooth output rate
    - Fixed Window - simple, but can burst at window edges
"""

import warnings

__version__ = "0.1.0"

# Exceptions
from .exceptions import FluxError, RateLimitExceeded, ConnectionError

# Core
from .limiter import RateLimiter, RateLimitResult, create_limiter, preload_scripts

# Decorator
from .decorators import rate_limit

# Config
from .config import FluxConfig, load_config, get_config, RateLimitPolicy, reload_config

# Try to import C++ core
try:
    from ._flux_core import RedisClient
except ImportError:
    warnings.warn(
        "Flux C++ extension not found. Run 'pip install .'",
        ImportWarning
    )
    RedisClient = None

__all__ = [
    "__version__",
    # Core
    "RateLimiter",
    "RateLimitResult", 
    "rate_limit",
    "create_limiter",
    "preload_scripts",
    # Policy enum
    "RateLimitPolicy",
    # Exceptions
    "FluxError",
    "RateLimitExceeded",
    "ConnectionError",
    # Config
    "FluxConfig",
    "load_config",
    "get_config",
    "reload_config",
    # C++ binding
    "RedisClient",
]