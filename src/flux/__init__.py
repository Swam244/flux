import warnings
from .exceptions import FluxError, RateLimitExceeded, ConnectionError
from .limiter import RateLimiter, RateLimitResult, create_limiter, preload_scripts
from .decorators import rate_limit
from .config import FluxConfig, load_config, get_config, RateLimitPolicy, reload_config

try:
    from ._flux_core import RedisClient
except ImportError:
    warnings.warn(
        "Flux C++ extension not found. Run 'pip install .'",
        ImportWarning
    )
    RedisClient = None

__version__ = "0.1.17"

__all__ = [
    "__version__",

    "RateLimiter",
    "RateLimitResult", 
    "rate_limit",
    "create_limiter",
    "preload_scripts",
   
    "RateLimitPolicy",
   
    "FluxError",
    "RateLimitExceeded",
    "ConnectionError",
   
    "FluxConfig",
    "load_config",
    "get_config",
    "reload_config",
   
    "RedisClient",
]