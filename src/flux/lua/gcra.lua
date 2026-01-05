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
-- KEYS: [1] limit_key, [2] stream_key
-- ARGV: [1] emission, [2] tolerance, [3] now, [4] record_analytics, [5] ep, [6-9] meta... [10] retention

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
-- Analytics Recording
if record_analytics == 1 then
    local stream_key = KEYS[2]
    local endpoint = ARGV[5]
    local max_len = ARGV[10]
    
    redis.call('XADD', stream_key, 'MAXLEN', '~', max_len, '*',
        'ts', now,
        'key', KEYS[1],
        'ep', endpoint,
        'd', decision_allowed,
        'p', 'gcra',
        'u', current_usage,
        'mr', ARGV[6], -- requests
        'mp', ARGV[7], -- period
        'mb', ARGV[8]  -- burst
    )
end

if decision_allowed == 1 then
    return {0, return_val, current_usage}
else
    return {-1, return_val, current_usage}
end
