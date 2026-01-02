"""
Flux Redis Inspector
"""
import redis
import time
from flux import RateLimiter, RateLimitPolicy, preload_scripts

def inspect():
    # 0. Preload Scripts (Simulate App Startup)
    print("--- 0. Preloading Scripts ---")
    try:
        count = preload_scripts()
        print(f"✅ Preloaded {count} scripts into Redis.")
    except Exception as e:
        print(f"⚠️  Preload failed (ensure C++ ext is built): {e}")

    # 1. Connect
    r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    try:
        r.ping()
        print("✅ Connected to Redis")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return

    print("\n--- 1. Loaded Scripts ---")
    # Manually check known scripts
    scripts = {
        "GCRA": RateLimitPolicy.GCRA,
        "Token Bucket": RateLimitPolicy.TOKEN_BUCKET,
        "Leaky Bucket": RateLimitPolicy.LEAKY_BUCKET,
        "Fixed Window": RateLimitPolicy.FIXED_WINDOW,
    }
    
    # Check existence using SHA1
    for name, policy in scripts.items():
        try:
            limiter = RateLimiter(policy=policy)
            _, sha1 = limiter.script
            exists = r.script_exists(sha1)[0]
            status = "🟢 Cached" if exists else "🔴 Missing"
            print(f"{name:<15} SHA: {sha1[:8]}... {status}")
        except Exception:
            pass

    print("\n--- 2. keys (prefix 'flux:') ---")
    keys = r.keys("flux:*")
    if not keys:
        print("No keys found.")
    else:
        print(f"Found {len(keys)} keys:")
        for k in keys:
            ttl = r.ttl(k)
            val = r.get(k)
            print(f"  {k:<30} TTL: {ttl:<5} Val: {val}")

if __name__ == "__main__":
    inspect()
