import redis # type: ignore
from typing import List, Dict, Any
from .config import get_config

class StatsProvider:
    def __init__(self, redis_client=None, key_prefix="flux:"):
        self.config = get_config()
        self.key_prefix = key_prefix
        
        if redis_client:
            self.r = redis_client
        else:
            self.r = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                decode_responses=True,
                socket_timeout=1.0,
            )
        
    def get_stats(self) -> List[Dict[str, Any]]:
        prefix = self.key_prefix
        endpoint_key = f"{prefix}stats:endpoints"
        
        try:
            endpoints = self.r.smembers(endpoint_key)
        except Exception:
            # Return empty if Redis is down
            return []
        
        if not endpoints:
            return []
            
        sorted_endpoints = sorted(list(endpoints))
        
        # Use pipeline for efficiency
        pipe = self.r.pipeline()
        
        # 1. Get Latency Stats (Global)
        pipe.hgetall(f"{prefix}stats:global")
        
        # 2. Get Endpoint Stats (All in one HGETALL per endpoint)
        for ep in sorted_endpoints:
            pipe.hgetall(f"{prefix}stats:ep:{ep}")
            
        try:
            values = pipe.execute()
        except Exception:
            return []
        
        # Parse global latency
        global_stats = values[0] or {}
        lat_total_us = int(global_stats.get("l:total", 0))
        lat_count = int(global_stats.get("l:count", 0))
        avg_latency_ms = round((lat_total_us / lat_count / 1000.0), 3) if lat_count > 0 else 0
        
        results = []
        # Endpoint stats start at index 1
        
        for i, ep in enumerate(sorted_endpoints):
            data = values[i + 1] or {}
            
            allowed = int(data.get("c:allowed", 0))
            blocked = int(data.get("c:blocked", 0))
            utilization_raw = int(data.get("u:raw", 0))
            last_updated = int(data.get("m:last_updated", 0))
            
            # Parse limit info
            limit_info = {
                "requests": int(data.get("m:requests", 0)),
                "period": int(data.get("m:period", 1)),
                "burst": int(data.get("m:burst", 0)),
                "policy": data.get("m:policy", "unknown")
            }
            
            total = allowed + blocked
            block_rate = (blocked / total * 100) if total > 0 else 0
            
            results.append({
                "endpoint": ep,
                "allowed": allowed,
                "blocked": blocked,
                "total": total,
                "block_rate": round(block_rate, 2),
                "avg_latency": avg_latency_ms,
                "limit_info": limit_info,
                "utilization_raw": utilization_raw,
                "last_updated": last_updated
            })
            
        return results
