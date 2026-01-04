-- GCRA (Generic Cell Rate Algorithm) Rate Limiter
-- Parameters:
--   KEYS[1]: rate limit key
--   ARGV[1]: emission_interval (period / rate) in milliseconds
--   ARGV[2]: delay_variation_tolerance (burst tolerance) in milliseconds
-- Returns:
--   -1 if rate limit exceeded (with retry_after in seconds)
--   0 if allowed
--   The new TAT (Theoretical Arrival Time) if allowed

local key = KEYS[1]
local emission_interval = tonumber(ARGV[1])
local delay_variation_tolerance = tonumber(ARGV[2])
local now = tonumber(ARGV[3]) -- Current timestamp in milliseconds

-- Get current TAT (Theoretical Arrival Time)
-- Analytics Argv indices
-- KEYS: [1] limit_key, [2] stats_ep_key, [3] stats_global_key, [4] stats_ep_set
-- ARGV: [1] emission, [2] tolerance, [3] now, [4] record_analytics, [5-10] meta...

local record_analytics = tonumber(ARGV[4]) or 0
local decision_allowed = 0
local return_val = 0 -- tat or retry_after
local current_usage = 0

-- Get current TAT (Theoretical Arrival Time)
local tat = redis.call('GET', key)
if tat == false then
    tat = 0
else
    tat = tonumber(tat)
end

-- Calculate the new TAT
local new_tat = math.max(now, tat) + emission_interval

-- Check if request is within tolerance
local allow_at = new_tat - delay_variation_tolerance

if now < allow_at then
    -- Rate limit exceeded
    decision_allowed = 0
    local retry_after = math.ceil((allow_at - now) / 1000) -- Convert to seconds
    return_val = retry_after
    current_usage = math.max(0, tat - now)
else
    -- Allow the request
    decision_allowed = 1
    redis.call('SET', key, new_tat, 'PX', math.ceil(delay_variation_tolerance * 2))
    return_val = new_tat
    current_usage = math.max(0, new_tat - now)
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
    
    -- Update Global Stats
    redis.call('HINCRBY', stats_global_key, 'l:count', 1)
    redis.call('EXPIRE', stats_global_key, stats_ttl)
end

if decision_allowed == 1 then
    return {0, return_val, current_usage}
else
    return {-1, return_val, current_usage}
end
