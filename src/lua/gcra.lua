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
    local retry_after = math.ceil((allow_at - now) / 1000) -- Convert to seconds
    return {-1, retry_after}
else
    -- Allow the request
    redis.call('SET', key, new_tat, 'PX', math.ceil(delay_variation_tolerance * 2))
    return {0, new_tat}
end

