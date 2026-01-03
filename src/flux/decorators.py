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

        from .identity import generate_identity

        def get_request(args, kwargs):
            """
            Heuristic to find the 'request' object in args or kwargs.
            """
            # 1. Check kwargs first (FastAPI/Flask often use 'request')
            if "request" in kwargs:
                return kwargs["request"]
                
            # 2. Check pos args (Django/Starlette)
            for arg in args:
                # Check for common attributes
                if hasattr(arg, "method") and hasattr(arg, "url"):
                    return arg
                if hasattr(arg, "META") and hasattr(arg, "GET"): # Django
                    return arg
                if hasattr(arg, "client") and hasattr(arg, "scope"): # Starlette/FastAPI
                    return arg
            
            # 3. Flask Global Context
            try:
                from flask import request
                if request:
                    return request
            except ImportError:
                pass
                
            return None

        def get_final_key(args, kwargs, func_name):
            request = get_request(args, kwargs)
            
            # If 'key' arg was passed to decorator, use it (callable or string)
            # If not, generate_identity falls back to IP
            identity_hash = generate_identity(request, key, prefix=name or func_name)
            return identity_hash

        def check_limit_and_get_response(limiter, final_key, args):
            result = limiter.hit(final_key)
            
            if not result.allowed:
                # ---------------------------------------------------------
                # AUTO-RESPONSE GENERATION
                # ---------------------------------------------------------
                retry_str = str(int(result.retry_after))
                headers = result.to_headers()
                content = {
                    "error": "Too Many Requests",
                    "retry_after": int(result.retry_after),
                    "detail": f"Rate limit exceeded. Try again in {retry_str} seconds."
                }

                # 1. Django Detection
                # -------------------
                if args and hasattr(args[0], 'META'):
                    try:
                        from django.http import JsonResponse
                        resp = JsonResponse(content, status=429)
                        for h, v in headers.items():
                            resp[h] = v
                        return resp
                    except ImportError:
                        pass

                # 2. Starlette / FastAPI Detection
                # --------------------------------
                # Heuristic: args[0] is often the request in middleware, or we found it earlier
                # But here we just want to return a JSONResponse if Starlette is present
                try:
                    from starlette.responses import JSONResponse
                    return JSONResponse(content, status_code=429, headers=headers)
                except ImportError:
                    pass

                # 3. Flask Detection
                # ------------------
                # Flask routes usually return (body, status, headers) tuple
                try:
                    import flask
                    # Check if we are in a request context to be sure
                    if flask.request:
                        from flask import jsonify, make_response
                        resp = make_response(jsonify(content), 429)
                        for h, v in headers.items():
                            resp.headers[h] = v
                        return resp
                except (ImportError, RuntimeError):
                    pass

                # Fallback: If no framework detected or imports fail, raise exception
                raise RateLimitExceeded(key=final_key, retry_after=result.retry_after)
            
            return None # Allowed

        # ---------------------------------------------------------
        # ASYNC WRAPPER
        # ---------------------------------------------------------
        

        if is_async:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                limiter = get_limiter()
                final_key = get_final_key(args, kwargs, func.__name__)
                
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
                final_key = get_final_key(args, kwargs, func.__name__)
                
                denied_response = check_limit_and_get_response(limiter, final_key, args)
                if denied_response:
                    return denied_response
                
                return func(*args, **kwargs)
            return wrapper

    return decorator
