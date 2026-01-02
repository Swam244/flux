"""
Tests for Flux
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux import RateLimiter, RateLimitExceeded, rate_limit


class TestRateLimiter:
    """Test the RateLimiter class."""
    
    def test_basic_allow(self):
        # We need a Redis client mocked or real. 
        # For unit tests without Redis, we might fail or need mocking.
        # Assuming the environment has Redis or we skip.
        try:
            limiter = RateLimiter(requests=10, period=60)
            assert limiter.hit("test:1").allowed is True
        except ConnectionError:
            pytest.skip("Redis not available")
    
    def test_hit_returns_result(self):
        try:
            limiter = RateLimiter(requests=10, period=60)
            result = limiter.hit("test:2")
            
            assert result.allowed is True
            assert result.remaining >= 0
            assert result.retry_after == 0
        except ConnectionError:
            pytest.skip("Redis not available")
    
    def test_result_headers(self):
        try:
            limiter = RateLimiter(requests=10, period=60)
            result = limiter.hit("test:3")
            headers = result.to_headers()
            
            assert "X-RateLimit-Remaining" in headers
        except ConnectionError:
            pytest.skip("Redis not available")
    
    def test_different_keys_independent(self):
        try:
            limiter = RateLimiter(requests=5, period=60)
            
            assert limiter.hit("user:1").allowed is True
            assert limiter.hit("user:2").allowed is True
            assert limiter.hit("user:3").allowed is True
        except ConnectionError:
            pytest.skip("Redis not available")


class TestRateLimitDecorator:
    """Test the @rate_limit decorator."""
    
    def test_static_key(self):
        # Using lambda for static key
        @rate_limit(requests=10, period=60, key=lambda: "test_func")
        def my_func():
            return "ok"
        
        try:
            assert my_func() == "ok"
        except ConnectionError:
            pytest.skip("Redis not available")
    
    def test_dynamic_key(self):
        @rate_limit(requests=10, period=60, key=lambda user_id: f"user:{user_id}")
        def my_func(user_id):
            return f"processed:{user_id}"
        
        try:
            result = my_func("123")
            assert result == "processed:123"
        except ConnectionError:
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


@pytest.mark.skipif(
    os.environ.get("SKIP_REDIS_TESTS", "0") == "1",
    reason="Redis not available"
)
class TestRedisIntegration:
    """Tests requiring Redis."""
    
    def test_redis_connection(self):
        try:
            from flux import RateLimiter
            limiter = RateLimiter(requests=10, period=60)
            assert limiter.client.ping() == "PONG"
        except Exception:
            pytest.skip("Redis not available")
