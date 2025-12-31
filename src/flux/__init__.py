"""
Flux - A high-performance, lightweight Django rate-limiter package.

This package provides rate limiting functionality for Django applications
with a C++ core for optimal performance.
"""
import warnings

try:
    # Import the C++ bindings
    from ._flux_core import RedisClient
    __all__ = ['RedisClient']

except ImportError:
    # Fallback/Error if the C++ extension is not built or found
    warnings.warn(
        "Flux C++ extension not found. Please ensure the package is built with 'uv pip install .'",
        ImportWarning
    )
    __all__ = []

__version__ = "0.1.0"