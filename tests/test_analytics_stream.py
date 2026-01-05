import time
import pytest
import redis
from flux.limiter import RateLimiter
from flux.config import FluxConfig, RateLimitPolicy, load_config
from flux.worker import AnalyticsWorker

@pytest.fixture
def redis_client():
    # Helper to get a clean redis connection
    # Assuming local redis available as per project defaults
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    try:
        r.ping()
    except redis.exceptions.ConnectionError:
        pytest.skip("Redis not available")
    return r

@pytest.fixture
def clean_redis(redis_client):
    redis_client.flushdb()
    return redis_client

def test_analytics_stream_emission(clean_redis):
    # 1. Setup Config
    config = FluxConfig(
        analytics_enabled=True,
        analytics_stream="test:events",
        key_prefix="test:",
        policy=RateLimitPolicy.TOKEN_BUCKET
    )
    
    # 2. Create Limiter
    limiter = RateLimiter(requests=10, period=60, config=config)
    
    # 3. Hit
    limiter.hit("user_123", endpoint="test_ep")
    
    # 4. Verify Stream
    entries = clean_redis.xrange("test:events")
    assert len(entries) == 1
    
    msg_id, data = entries[0]
    assert data['ep'] == "test_ep"
    
    # Key should be hashed
    import hashlib
    expected_key = "test:" + hashlib.sha256("user_123".encode()).hexdigest()
    assert data['key'] == expected_key
    
    assert data['p'] == "token_bucket"
    assert data['d'] == "1" # Allowed

def test_analytics_worker_consumption(clean_redis):
    # 1. Setup Config
    config = FluxConfig(
        analytics_enabled=True,
        analytics_stream="test:events",
        key_prefix="test:",
        policy=RateLimitPolicy.GCRA
    )
    
    # 2. Create Limiter & Worker
    limiter = RateLimiter(requests=5, period=10, config=config)
    worker = AnalyticsWorker(config)
    
    # 3. Generate Traffic (Allowed)
    limiter.hit("user_a", endpoint="api_v1")
    limiter.hit("user_a", endpoint="api_v1")
    
    # 4. Process manually (avoid threading in test for determinism)
    # Ensure group exists
    worker._ensure_group()
    
    # Read from stream
    entries = clean_redis.xreadgroup(
        worker.group_name, 
        worker.consumer_name, 
        {config.analytics_stream: '>'}, 
        count=10
    )
    
    assert len(entries) > 0
    stream, messages = entries[0]
    assert len(messages) == 2
    
    # Process
    worker._process_messages(messages)
    
    # 5. Verify Metrics Hashes
    # stats:ep:api_v1 should have c:allowed = 2
    stats_key = "test:stats:ep:api_v1"
    stats = clean_redis.hgetall(stats_key)
    
    assert stats['c:allowed'] == '2'
    assert 'm:last_updated' in stats
    
    # Global stats
    global_stats = clean_redis.hgetall("test:stats:global")
    assert global_stats['l:count'] == '2'

def test_analytics_worker_blocked_request(clean_redis):
    # 1. Setup Config (Low limit)
    config = FluxConfig(
        analytics_enabled=True,
        analytics_stream="test:events",
        key_prefix="test:",
        policy=RateLimitPolicy.TOKEN_BUCKET
    )
    
    limiter = RateLimiter(requests=1, period=60, config=config)
    worker = AnalyticsWorker(config)
    worker._ensure_group()
    
    # 2. Hit (Allowed)
    limiter.hit("user_b", endpoint="api_blocked")
    # 3. Hit (Blocked)
    limiter.hit("user_b", endpoint="api_blocked")
    
    # 4. Process
    entries = clean_redis.xreadgroup(
        worker.group_name, 
        worker.consumer_name, 
        {config.analytics_stream: '>'}, 
        count=10
    )
    worker._process_messages(entries[0][1])
    
    # 5. Verify
    stats = clean_redis.hgetall("test:stats:ep:api_blocked")
    assert stats['c:allowed'] == '1'
    assert stats['c:blocked'] == '1'
