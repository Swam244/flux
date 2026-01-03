import pytest
import threading
import time
import subprocess
import os
import sys
from unittest.mock import MagicMock
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux._flux_core import RedisClient
from flux.limiter import RateLimiter, RateLimitResult
from flux.config import FluxConfig

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
INVALID_PORT = 9999

# ------------------------------------------------------------------
# FIXTURES
# ------------------------------------------------------------------
@pytest.fixture
def redis_client():
    """Fixture for connected RedisClient. Skips if Redis not available."""
    try:
        client = RedisClient(REDIS_HOST, REDIS_PORT)
        return client
    except RuntimeError:
        pytest.skip(f"Redis not running on {REDIS_HOST}:{REDIS_PORT}")

@pytest.fixture
def temp_logfile(tmp_path):
    log = tmp_path / "flux_test.log"
    log.write_text("")
    return log

# ------------------------------------------------------------------
# REDIS CONNECTION TESTS
# ------------------------------------------------------------------
class TestRedisConnection:
    def test_ping_success(self, redis_client):
        assert redis_client.ping() == "PONG"

    def test_connection_failure(self):
        with pytest.raises(RuntimeError) as exc:
            RedisClient(REDIS_HOST, INVALID_PORT)
        assert "Redis Connection Failed" in str(exc.value)

    def test_pool_concurrency(self):
        try:
            client = RedisClient(REDIS_HOST, REDIS_PORT, pool_size=5)
        except RuntimeError:
            pytest.skip("Redis not available")
            
        errors = []
        lock = threading.Lock()
        
        def worker():
            try:
                for _ in range(10):
                    if client.ping() != "PONG":
                        with lock: errors.append("Ping failed")
            except Exception as e:
                with lock: errors.append(str(e))
                
        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        assert not errors

    def test_chaos_retry(self, temp_logfile):
        """Simulate redis restart to verify retry mechanics."""
        port = 6388
        log_file = str(temp_logfile)
        
        # Start Temp Redis
        proc = subprocess.Popen(
            ["redis-server", "--port", str(port), "--save", ""],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(1)
        
        try:
            client = RedisClient(REDIS_HOST, port, log_file=log_file)
            assert client.ping() == "PONG"
            
            # Kill Redis
            proc.terminate()
            proc.wait()
            
            # Expect failure after retries
            with pytest.raises(RuntimeError):
                client.ping()
                
            logs = temp_logfile.read_text()
            assert "Attempt 1/3 failed" in logs
            
        finally:
            if proc.poll() is None:
                proc.terminate()

# ------------------------------------------------------------------
# JITTER TESTS
# ------------------------------------------------------------------
class TestJitterLogic:
    def test_jitter_applied_range(self):
        config = FluxConfig(jitter_enabled=True, jitter_max_ms=1000)
        limiter = RateLimiter(requests=1, period=10, config=config)
        
        # Mock Redis response: Status 1 (Denied), 10.0s retry
        limiter._client = MagicMock()
        limiter._client.eval_script.return_value = (1, 10.0)
        
        results = []
        for _ in range(50):
            # Access internal parser to inject mock values
            res = limiter._parse_result(1, 10.0, 0)
            results.append(res.retry_after)
            
        # Verify range [10.0, 11.0] and variance
        for val in results:
            assert 10.0 <= val <= 11.0
        assert len(set(results)) > 1

    def test_jitter_disabled(self):
        config = FluxConfig(jitter_enabled=False)
        limiter = RateLimiter(requests=1, period=10, config=config)
        res = limiter._parse_result(1, 10.0, 0)
        assert res.retry_after == 10.0
