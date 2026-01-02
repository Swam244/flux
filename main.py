#!/usr/bin/env python3
"""
Flux Demo - Simple Rate Limiting
"""

from flux import RateLimiter, RateLimitExceeded, rate_limit


def demo_basic():
    """Basic rate limiter usage."""
    print("\n=== Basic RateLimiter ===")
    
    limiter = RateLimiter(requests=5, period=60)
    print(f"Created: {limiter}")
    
    for i in range(7):
        result = limiter.hit("demo:user:1")
        status = "✅" if result.allowed else "❌"
        print(f"  Request {i+1}: {status} remaining={result.remaining}")


def demo_decorator():
    """Decorator usage."""
    print("\n=== @rate_limit Decorator ===")
    
    @rate_limit(requests=3, period=60, key=lambda user: f"email:{user}")
    def send_email(user: str):
        return f"Email sent to {user}"
    
    for i in range(5):
        try:
            result = send_email("alice@example.com")
            print(f"  Call {i+1}: ✅ {result}")
        except RateLimitExceeded as e:
            print(f"  Call {i+1}: ❌ {e}")


def demo_callback():
    """Decorator with custom callback."""
    print("\n=== Decorator with Callback ===")
    
    @rate_limit(
        requests=2, 
        period=60, 
        key="api",
        on_exceeded=lambda e: {"error": "rate_limited", "retry": e.retry_after}
    )
    def api_call():
        return {"status": "ok"}
    
    for i in range(4):
        result = api_call()
        print(f"  Call {i+1}: {result}")


def main():
    print("\n⚡ FLUX - Simple Rate Limiting\n")
    
    # Test Redis connection
    try:
        from flux import RedisClient
        client = RedisClient()
        print(f"Redis: {client.ping()} ✅")
    except Exception as e:
        print(f"Redis: ❌ {e}")
    
    demo_basic()
    demo_decorator()
    demo_callback()
    
    print("\n✨ Done!\n")


if __name__ == "__main__":
    main()