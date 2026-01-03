
import pytest
from unittest.mock import MagicMock
from flux.limiter import RateLimiter, RateLimitResult
from flux.config import FluxConfig

class TestJitter:
    def test_jitter_applied_and_within_range(self):
        # Configure with jitter enabled, max 1000ms
        config = FluxConfig(jitter_enabled=True, jitter_max_ms=1000)
        limiter = RateLimiter(requests=1, period=10, config=config)
        
        # Mock client to simulate rate limit exceeded (status=1)
        # Value 10.0 (10 seconds retry)
        limiter._client = MagicMock()
        limiter._client.eval_script.return_value = (1, 10.0)
        
        # Call _parse_result directly or via hit (hit calls client.eval_script)
        # We'll call _parse_result directly to isolate logic, 
        # but _parse_result is usually called by hit. 
        # Let's call _parse_result directly as it contains the logic we changed.
        
        # Test 100 iterations to check range and variance
        results = []
        for _ in range(100):
            res = limiter._parse_result(1, 10.0, 0)
            results.append(res.retry_after)
            
        # 1. Verify all valid range [10.0, 11.0]
        # range is inclusive of lower, exclusive upper effectively for uniform
        for val in results:
            assert 10.0 <= val <= 11.0, f"Value {val} out of range"
            
        # 2. Verify variance (not all same)
        assert len(set(results)) > 1, "Jitter did not produce variable results"
        
    def test_jitter_disabled(self):
        # Configure with jitter disabled
        config = FluxConfig(jitter_enabled=False)
        limiter = RateLimiter(requests=1, period=10, config=config)
        
        # Mock result
        res = limiter._parse_result(1, 10.0, 0)
        
        assert res.retry_after == 10.0
        
    def test_jitter_zero_max(self):
         # Configure with jitter enabled but 0 max
        config = FluxConfig(jitter_enabled=True, jitter_max_ms=0)
        limiter = RateLimiter(requests=1, period=10, config=config)
        
        res = limiter._parse_result(1, 10.0, 0)
        assert res.retry_after == 10.0

if __name__ == "__main__":
    pytest.main([__file__])
