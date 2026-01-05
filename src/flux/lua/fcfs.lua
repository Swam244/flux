-- FCFS (First Come First Served) Rate Limiter
-- Parameters:
--   KEYS[1]: rate limit key
--   KEYS[2]: queue key
--   ARGV[1]: max_requests (burst)
--   ARGV[2]: window_ms (time window in milliseconds)
--   ARGV[3]: now (current timestamp in milliseconds)
--   (Analytics args starting ARGV[4]... see implementation)
-- Returns:
--   -1 if rate limit exceeded (with position in queue)
--   0 if allowed immediately
--   Position in queue if queued

local limit_key = KEYS[1]
local queue_key = KEYS[2]
local max_requests = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Get current request count
local count = redis.call('GET', limit_key)
if count == false then
    count = 0
else
    count = tonumber(count)
end

-- Check if under limit
if count < max_requests then
    -- Allow immediately
    redis.call('INCR', limit_key)
    redis.call('PEXPIRE', limit_key, window_ms)
    -- Analytics Recording
    -- KEYS: [1] limit, [2] queue, [3] stream
    -- ARGV: [1] max, [2] win, [3] now, [4] record, [5] ep, ... [10] maxlen
    local record_analytics = tonumber(ARGV[4]) or 0
    if record_analytics == 1 then
        local stream_key = KEYS[3]
        redis.call('XADD', stream_key, 'MAXLEN', '~', ARGV[10], '*',
            'ts', now,
            'key', KEYS[1],
            'ep', ARGV[5],
            'd', 1,
            'p', 'fixed_window',
            'u', count + 1,
            'mr', ARGV[6],
            'mp', ARGV[7],
            'mb', ARGV[8]
        )
    end

    return {0, 0} -- {allowed, queue_position}
else
    -- Rate limit exceeded, add to queue
    local queue_pos = redis.call('ZADD', queue_key, 'NX', now, now)
    redis.call('PEXPIRE', queue_key, window_ms)
    
    -- Get position in queue
    local position = redis.call('ZRANK', queue_key, now)
    if position == false then
        position = -1
    end
    
    -- Clean up old entries (outside window)
    local cutoff = now - window_ms
    redis.call('ZREMRANGEBYSCORE', queue_key, 0, cutoff)
    
    -- Analytics Recording
    local record_analytics = tonumber(ARGV[4]) or 0
    if record_analytics == 1 then
        local stream_key = KEYS[3]
        redis.call('XADD', stream_key, 'MAXLEN', '~', ARGV[10], '*',
            'ts', now,
            'key', KEYS[1],
            'ep', ARGV[5],
            'd', 0,
            'p', 'fixed_window',
            'u', count,
            'mr', ARGV[6],
            'mp', ARGV[7],
            'mb', ARGV[8]
        )
    end

    return {-1, position} -- {denied, queue_position}
end

