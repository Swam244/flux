-- Token Bucket Rate Limiter
-- Parameters:
--   KEYS[1]: rate limit key (stores tokens and last_refill_time)
--   ARGV[1]: capacity (max tokens/burst)
--   ARGV[2]: refill_rate (tokens per second)
--   ARGV[3]: now (current timestamp in milliseconds)
-- Returns:
--   -1 if rate limit exceeded (with retry_after in seconds)
--   Remaining tokens if allowed

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_time_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local refill_rate = 1000.0 / refill_time_ms

-- Get current state: tokens and last_refill_time
-- Analytics args (indices shift based on Keys)
-- KEYS: [1] limit_key, [2] stats_ep_key, [3] stats_global_key, [4] stats_ep_set
-- ARGV: [1] capacity, [2] refill_time_ms, [3] now, [4] record_analytics (0/1), [5] endpoint_name, [6] meta_requests, [7] meta_period, [8] meta_burst, [9] meta_policy, [10] ttl

local record_analytics = tonumber(ARGV[4]) or 0

-- Rate Limit Logic
local decision_allowed = 0
local return_val = 0
local current_usage = 0

-- Get current state: tokens and last_refill_time
local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1]) or capacity
local last_refill = tonumber(data[2]) or now

-- Calculate time elapsed since last refill (in seconds)
local elapsed_seconds = (now - last_refill) / 1000.0

-- Refill tokens based on elapsed time
if elapsed_seconds > 0 then
    local tokens_to_add = math.floor(elapsed_seconds * refill_rate)
    tokens = math.min(capacity, tokens + tokens_to_add)
    last_refill = now
end

-- Check if we have tokens available
if tokens >= 1 then
    -- Consume one token
    tokens = tokens - 1
    decision_allowed = 1
    current_usage = capacity - tokens
    return_val = tokens
    
    -- Update state in Redis
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    local ttl = math.ceil((capacity / refill_rate) * 2)
    redis.call('EXPIRE', key, ttl)
else
    -- No tokens available
    decision_allowed = 0
    current_usage = capacity - tokens
    
    local time_until_next_token = math.ceil((1.0 / refill_rate) * 1000) -- in milliseconds
    local retry_after = math.ceil(time_until_next_token / 1000) -- in seconds
    return_val = retry_after
    
    -- Update last_refill time even if we can't serve
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    local ttl = math.ceil((capacity / refill_rate) * 2)
    redis.call('EXPIRE', key, ttl)
end

-- Analytics Recording
if record_analytics == 1 then
    local stats_ep_key = KEYS[2]
    local stats_global_key = KEYS[3]
    local stats_ep_set = KEYS[4]
    local endpoint = ARGV[5]
    local stats_ttl = tonumber(ARGV[10]) or 3600
    
    -- Add to Set
    redis.call('SADD', stats_ep_set, endpoint)
    redis.call('EXPIRE', stats_ep_set, stats_ttl)
    
    -- Update Endpoint Stats
    local status_field = (decision_allowed == 1) and "c:allowed" or "c:blocked"
    redis.call('HINCRBY', stats_ep_key, status_field, 1)
    
    -- Update Usage & Meta
    redis.call('HSET', stats_ep_key, 
        'u:raw', current_usage,
        'm:last_updated', now,
        'm:requests', ARGV[6],
        'm:period', ARGV[7],
        'm:burst', ARGV[8],
        'm:policy', ARGV[9]
    )
    redis.call('EXPIRE', stats_ep_key, stats_ttl)
    
    -- Update Global Stats (No latency, just counts)
    redis.call('HINCRBY', stats_global_key, 'l:count', 1)
    redis.call('EXPIRE', stats_global_key, stats_ttl)
end

if decision_allowed == 1 then
     return {0, return_val, current_usage}
else
     return {-1, return_val, current_usage}
end

