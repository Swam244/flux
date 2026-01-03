import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux import rate_limit, RateLimitExceeded, RateLimiter

class TestRateLimitDecorator:
    """Test the @rate_limit decorator logic independent of framework."""
    
    def test_static_key(self):
        @rate_limit(requests=10, period=60, key=lambda: "test_func")
        def my_func():
            return "ok"
        
        # This will try to hit Redis. If Redis is down, it skips or fails depending on config.
        # Ideally we mock RedisClient here for pure unit test, but integration is fine.
        try:
            assert my_func() == "ok"
        except RuntimeError:
            pytest.skip("Redis not available")
    
    def test_dynamic_key(self):
        class MockRequest:
            def __init__(self, user_id):
                self.user_id = user_id
                self.method = "GET" 
                self.url = "/"

        @rate_limit(requests=10, period=60, key=lambda r: f"user:{r.user_id}")
        def my_func(request):
            return f"processed:{request.user_id}"
        
        try:
            req = MockRequest("123")
            result = my_func(req)
            assert result == "processed:123"
        except RuntimeError:
            pytest.skip("Redis not available")
    
    def test_preserves_metadata(self):
        @rate_limit(requests=10, period=60, key=lambda: "test")
        def documented_func():
            """My docstring."""
            pass
        
        assert documented_func.__name__ == "documented_func"
        assert "docstring" in documented_func.__doc__

class TestExceptions:
    """Test exception classes."""
    
    def test_rate_limit_exceeded(self):
        exc = RateLimitExceeded(key="user:123", retry_after=5.5)
        assert "user:123" in str(exc)
    
    def test_headers(self):
        exc = RateLimitExceeded(key="test", retry_after=10)
        headers = exc.to_headers()
        
        assert headers["Retry-After"] == "10"
        assert headers["X-RateLimit-Remaining"] == "0"
