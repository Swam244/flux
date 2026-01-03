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
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

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
    
    -- Update state in Redis
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    
    -- Set expiration (bucket expires after 2x the time to fill from empty)
    local ttl = math.ceil((capacity / refill_rate) * 2)
    redis.call('EXPIRE', key, ttl)
    
    return {0, tokens} -- {allowed, remaining_tokens}
else
    -- No tokens available
    local time_until_next_token = math.ceil((1.0 / refill_rate) * 1000) -- in milliseconds
    local retry_after = math.ceil(time_until_next_token / 1000) -- in seconds
    
    -- Update last_refill time even if we can't serve
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    local ttl = math.ceil((capacity / refill_rate) * 2)
    redis.call('EXPIRE', key, ttl)
    
    return {-1, retry_after} -- {denied, retry_after_seconds}
end

