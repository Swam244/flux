"""
Flux Identity Management

Handles the generation of secure, unique keys for rate limiting.
Strategies:
1. User-provided callable (e.g. `lambda req: req.user.id`)
2. Fallback to IP address (if no callable provided)
3. Hashing (SHA-256) to ensure privacy and uniformity
"""

import hashlib
from typing import Any, Callable, Union, Optional

def get_ip(request: Any) -> str:
    """
    Best-effort attempt to get client IP from various framework request objects.
    Supports: Django, Flask, FastAPI (Starlette), Werkzeug.
    """
    # 1. FastAPI / Starlette
    if hasattr(request, "client") and hasattr(request.client, "host"):
        return request.client.host
    
    # 2. Django / Flask (remote_addr)
    if hasattr(request, "remote_addr"):
        return request.remote_addr
    
    # 3. Headers (X-Forwarded-For) - Common in proxies
    if hasattr(request, "headers"):
        x_forwarded = request.headers.get("X-Forwarded-For")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()
            
    # 4. Meta (Django)
    if hasattr(request, "META"):
        return request.META.get("REMOTE_ADDR") or "0.0.0.0"

    return "0.0.0.0"

def generate_identity(
    request: Any, 
    key_func: Optional[Union[str, Callable]] = None,
    prefix: str = ""
) -> str:
    """
    Generates a secure, hashed identity key.
    
    Args:
        request: The request object (framework specific)
        key_func: Optional callable to extract ID, or static string.
        prefix: Optional prefix (e.g. "api_v1")
        
    Returns:
        SHA-256 hashed string safe for Redis
    """
    raw_identity = ""

    if key_func is None:
        # Default: Use IP
        raw_identity = f"ip:{get_ip(request)}"
    elif callable(key_func):
        try:
            # Try passing request
            val = key_func(request)
            raw_identity = str(val)
        except TypeError:
            # If callable doesn't accept args (e.g. lambda: "static")
            val = key_func()
            raw_identity = str(val)
    else:
        # Static string (e.g. "global_limit")
        raw_identity = str(key_func)

    # Combine with prefix if needed
    final_raw = f"{prefix}:{raw_identity}" if prefix else raw_identity
    
    # Return raw identity (RateLimiter core will handle hashing)
    return final_raw
