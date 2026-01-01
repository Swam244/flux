import threading
import pytest
import sys
import os

# Ensure we can import the build artifact
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

try:
    from flux._flux_core import RedisClient
except ImportError:
    pytest.fail("Could not import 'flux._flux_core'. Did you run 'pip install .'?", pytrace=False)

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
INVALID_PORT = 9999  # A port where Redis is NOT running

# ------------------------------------------------------------------
# TEST FIXTURES
# ------------------------------------------------------------------
@pytest.fixture
def redis_client():
    """
    Fixture that provides a connected RedisClient.
    Skips the test if Redis is not running locally.
    """
    try:
        client = RedisClient(REDIS_HOST, REDIS_PORT)
        return client
    except RuntimeError:
        pytest.skip(f"Redis not running on {REDIS_HOST}:{REDIS_PORT}")

# ------------------------------------------------------------------
# TESTS
# ------------------------------------------------------------------

def test_module_docstring():
    """Verify module documentation exists."""
    import flux._flux_core
    assert flux._flux_core.__doc__ is not None
    assert "Flux Core" in flux._flux_core.__doc__

def test_ping_success(redis_client):
    """
    Verify the basic C++ -> Redis PING command.
    """
    response = redis_client.ping()
    assert response == "PONG", f"Expected 'PONG', got '{response}'"

def test_connection_failure():
    """
    Verify that connecting to an invalid port raises a RuntimeError.
    """
    with pytest.raises(RuntimeError) as excinfo:
        # Tries to connect to port 9999 where nothing is running
        RedisClient(REDIS_HOST, INVALID_PORT)
    
    error_msg = str(excinfo.value)
    
    # [FIX] Updated assertions to match your C++ 'main.cpp' output
    print(f"DEBUG: Captured Error -> {error_msg}") # Helpful for debugging
    assert "Redis Connection Failed" in error_msg

def test_constructor_defaults():
    """
    Verify the default constructor arguments.
    """
    try:
        client = RedisClient() 
        assert client.ping() == "PONG"
    except RuntimeError:
        pytest.skip("Default local Redis not available")

def test_pool_concurrency():
    """
    Spins up 20 threads sharing a pool of size 5.
    They should all succeed by waiting their turn.
    """
    try:
        # Initialize pool with only 5 connections
        client = RedisClient("127.0.0.1", 6379, pool_size=5)
    except RuntimeError:
        pytest.skip(f"Redis not running on {REDIS_HOST}:{REDIS_PORT}")
    
    errors = []
    errors_lock = threading.Lock()
    
    def worker():
        try:
            # Each thread tries to ping 10 times
            for _ in range(10):
                res = client.ping()
                if res != "PONG":
                    with errors_lock:
                        errors.append(f"Got {res}")
        except Exception as e:
            with errors_lock:
                errors.append(str(e))

    # Launch 20 threads (High contention)
    threads = [threading.Thread(target=worker) for _ in range(20)]
    
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(errors) == 0, f"Errors occurred: {errors}"