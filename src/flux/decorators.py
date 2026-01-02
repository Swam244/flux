"""
Flux Decorators

Provides the @rate_limit decorator for easy integration with:
- Django Views
- FastAPI Endpoints
- Flask Routes
- Regular Python Functions
"""

import functools
import inspect
import hashlib
from typing import Optional, Callable, Union, Any

from .limiter import RateLimiter, RateLimitResult
from .exceptions import RateLimitExceeded


def rate_limit(
    name: Optional[str] = None,
    *,
    requests: Optional[int] = None,
    period: Optional[int] = None,
    burst: Optional[int] = None,
    policy: Optional[str] = None,
    key: Optional[Callable[..., str]] = None,
):
    """
    Decorator to apply rate limiting to a function or view.
    Supports both Sync and Async functions.
    
    Args:
        name: Name of a preset config in flux.toml (e.g. "api")
        requests: Override requests per period
        period: Override period in seconds
        burst: Override burst capacity
        policy: Override rate limit policy
        key: Callable to generate unique key. Receives function args.
             If None, defaults to "function_name:ip_address" logic.
    """
    
    def decorator(func):
        is_async = inspect.iscoroutinefunction(func)
        _limiter_instance: Optional[RateLimiter] = None
        
        def get_limiter():
            nonlocal _limiter_instance
            if _limiter_instance is None:
                if name:
                    # Load from named config
                    _limiter_instance = RateLimiter.from_config(name)
                    # Apply overrides
                    if any([requests, period, burst, policy]):
                        # Create new instance with overrides, inheriting from the config
                        _limiter_instance = RateLimiter(
                            requests=requests or _limiter_instance.requests,
                            period=period or _limiter_instance.period,
                            burst=burst or _limiter_instance.burst,
                            policy=policy or _limiter_instance.policy.value, # Pass string logic handles enum
                        )
                else:
                    _limiter_instance = RateLimiter(
                        requests=requests,
                        period=period,
                        burst=burst,
                        policy=policy,
                    )
            return _limiter_instance

        def generate_key(args, kwargs, func_name):
            if key:
                try:
                    # Try to bind args if possible (inspect.signature is slow but safe?)
                    # For performance, just pass what we have.
                    # Ideally key func handles (request) or (*args)
                    return key(*args, **kwargs)
                except TypeError:
                    # Fallback: Maybe key expects just the first arg (request)
                    if args:
                        return key(args[0])
                    raise

            # Default Auto-Inference Strategy
            req_obj = args[0] if args else None
            
            # 1. Django
            if hasattr(req_obj, 'META') and hasattr(req_obj, 'user'):
                user_id = str(req_obj.user.id) if req_obj.user.is_authenticated else None
                ip = req_obj.META.get('REMOTE_ADDR', 'unknown')
                return f"django:{user_id or ip}"
            
            # 2. FastAPI / Starlette
            if hasattr(req_obj, 'client') and hasattr(req_obj, 'url'):
                ip = req_obj.client.host if req_obj.client else 'unknown'
                return f"fastapi:{ip}"
            
            # 3. Flask (Global context, req_obj might not be request)
            try:
                from flask import request
                # Verify if we are in a request context
                if request and request.remote_addr:  
                     return f"flask:{request.remote_addr}"
            except (ImportError, RuntimeError, AttributeError):
                pass

            # 4. Fallback: Function args hash
            arg_str = str(args) + str(kwargs)
            arg_hash = hashlib.md5(arg_str.encode()).hexdigest()
            return f"func:{func_name}:{arg_hash}"

        def check_limit_and_get_response(limiter, final_key, args):
            result = limiter.hit(final_key)
            
            if not result.allowed:
                # Handle Rate Limit Exceeded
                
                # Django Response
                if hasattr(args[0], 'META'):
                    from django.http import JsonResponse
                    resp = JsonResponse(
                        {"error": "Too Many Requests", "retry_after": int(result.retry_after)}, 
                        status=429
                    )
                    for h, v in result.to_headers().items():
                        resp[h] = v
                    return resp  # Return response object directly
                
                # Raise Exception for others (FastAPI catches this)
                raise RateLimitExceeded(key=final_key, retry_after=result.retry_after)
            
            return None # Allowed

        # ---------------------------------------------------------
        # ASYNC WRAPPER
        # ---------------------------------------------------------
        if is_async:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                limiter = get_limiter()
                limit_key = generate_key(args, kwargs, func.__name__)
                final_key = f"{func.__name__}:{limit_key}"
                
                # Check limit (Sync operation, Redis is fast enough)
                # If we need async redis, we'd need a different client
                denied_response = check_limit_and_get_response(limiter, final_key, args)
                if denied_response:
                    return denied_response
                
                return await func(*args, **kwargs)
            return wrapper
        
        # ---------------------------------------------------------
        # SYNC WRAPPER
        # ---------------------------------------------------------
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                limiter = get_limiter()
                limit_key = generate_key(args, kwargs, func.__name__)
                final_key = f"{func.__name__}:{limit_key}"
                
                denied_response = check_limit_and_get_response(limiter, final_key, args)
                if denied_response:
                    return denied_response
                
                return func(*args, **kwargs)
            return wrapper

    return decorator
