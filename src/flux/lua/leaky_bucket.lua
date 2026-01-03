-- Leaky Bucket Rate Limiter
-- Parameters:
--   KEYS[1]: rate limit key (stores current level and last_leak_time)
--   ARGV[1]: capacity (max bucket size/burst)
--   ARGV[2]: leak_rate (units per second that leak out)
--   ARGV[3]: now (current timestamp in milliseconds)
-- Returns:
--   -1 if rate limit exceeded (bucket full, with retry_after)
--   0 if allowed (with current level)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local leak_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Get current state: level and last_leak_time
local data = redis.call('HMGET', key, 'level', 'last_leak')
local level = tonumber(data[1]) or 0
local last_leak = tonumber(data[2]) or now

-- Calculate time elapsed since last leak (in seconds)
local elapsed_seconds = (now - last_leak) / 1000.0

-- Leak out units based on elapsed time
if elapsed_seconds > 0 then
    local leaked = math.floor(elapsed_seconds * leak_rate)
    level = math.max(0, level - leaked)
    last_leak = now
end

-- Check if bucket has space
if level < capacity then
    -- Add one unit to bucket
    level = level + 1
    
    -- Update state in Redis
    redis.call('HMSET', key, 'level', level, 'last_leak', last_leak)
    
    -- Set expiration (bucket expires after 2x the time to fill from empty)
    local ttl = math.ceil((capacity / leak_rate) * 2)
    redis.call('EXPIRE', key, ttl)
    
    return {0, level} -- {allowed, current_level}
else
    -- Bucket is full
    -- Calculate when next unit will leak out
    local time_until_leak = math.ceil((1.0 / leak_rate) * 1000) -- in milliseconds
    local retry_after = math.ceil(time_until_leak / 1000) -- in seconds
    
    -- Update last_leak time
    redis.call('HMSET', key, 'level', level, 'last_leak', last_leak)
    local ttl = math.ceil((capacity / leak_rate) * 2)
    redis.call('EXPIRE', key, ttl)
    
    return {-1, retry_after} -- {denied, retry_after_seconds}
end

