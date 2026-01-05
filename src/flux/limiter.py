import time
import random
import hashlib
import redis # type: ignore
from pathlib import Path
from typing import Optional, Tuple, List, Callable, Dict, Any, Union
from dataclasses import dataclass

from ._flux_core import RedisClient
from .config import get_config, FluxConfig, RateLimitPolicy, RateLimitDefaults
from .exceptions import RateLimitExceeded, ConnectionError
from .analytics import AnalyticsServer
from .stats import StatsProvider

# Global singleton for the analytics server
_ANALYTICS_SERVER: Optional[AnalyticsServer] = None


# =============================================================================
# LUA SCRIPT LOADER
# =============================================================================

_SCRIPTS: Dict[RateLimitPolicy, Tuple[str, str]] = {}


def _get_script(policy: RateLimitPolicy) -> Tuple[str, str]:
    """Load the Lua script and its SHA1 hash for the given policy."""
    global _SCRIPTS
    
    if policy not in _SCRIPTS:
        # Map policy to script filename
        script_map = {
            RateLimitPolicy.GCRA: "gcra.lua",
            RateLimitPolicy.TOKEN_BUCKET: "token_bucket.lua",
            RateLimitPolicy.LEAKY_BUCKET: "leaky_bucket.lua",
            RateLimitPolicy.FIXED_WINDOW: "fcfs.lua",
        }
        
        script_name = script_map.get(policy)
        if not script_name:
            raise ValueError(f"Unknown rate limit policy: {policy}")
        
        # Find the Lua script relative to this module
        module_dir = Path(__file__).parent
        script_path = module_dir / "lua" / script_name
        
        if not script_path.exists():
            # Fallback for dev environment or alternative layouts
            search_paths = [
                module_dir.parent / "lua" / script_name,
                module_dir.parent.parent / "src" / "lua" / script_name,
            ]
            for path in search_paths:
                if path.exists():
                    script_path = path
                    break

        if not script_path.exists():
            raise FileNotFoundError(
                f"Lua script '{script_name}' not found. Looked in {module_dir}/lua"
            )

        
        content = script_path.read_text()
        sha1 = hashlib.sha1(content.encode()).hexdigest()
        _SCRIPTS[policy] = (content, sha1)
    
    return _SCRIPTS[policy]


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    remaining: int = 0
    reset_after: Optional[int] = None
    retry_after: Optional[float] = None
    limit: int = 0
    usage: int = 0 # Used capacity (tokens used, or tat offset)
    
    def to_headers(self) -> Dict[str, str]:
        """Generate standard HTTP rate limit headers."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
        }
        if self.reset_after is not None:
            headers["X-RateLimit-Reset"] = str(self.reset_after)
        if not self.allowed and self.retry_after is not None:
            headers["Retry-After"] = str(int(self.retry_after))
        return headers


# =============================================================================
# RATE LIMITER - FRAMEWORK AGNOSTIC
# =============================================================================

class RateLimiter:
    """
    Framework-agnostic rate limiter using Redis.
    Supports: GCRA, Token Bucket, Leaky Bucket, Fixed Window.
    """
    
    def __init__(
        self,
        requests: Optional[int] = None,
        period: Optional[int] = None,
        *,
        burst: Optional[int] = None,
        policy: Optional[Union[RateLimitPolicy, str]] = None,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        config: Optional[FluxConfig] = None,
    ):
        """
        Initialize the rate limiter.
        
        Args:
            requests: Number of requests allowed per period (default from config)
            period: Time period in seconds (default from config)
            burst: Max burst size (defaults to requests)
            policy: Rate limiting algorithm (default from config)
            redis_host: Redis host (default from config)
            redis_port: Redis port (default from config)
            config: Optional FluxConfig to use instead of global
        """
        # Load config
        self._config = config or get_config()
        

        
        # Rate limit parameters (use provided values or defaults from config)
        defaults = self._config.rate_limit_defaults
        self.requests = requests or defaults.requests
        self.period = period or defaults.period
        
        if burst is not None:
            self.burst = burst
        elif requests is not None:
            # If requests is explicit, default burst to it (ignore global default)
            self.burst = requests
        else:
            # Use global default
            self.burst = defaults.burst or self.requests
        if isinstance(policy, str):
            try:
                policy = RateLimitPolicy(policy.lower())
            except ValueError:
                raise ValueError(f"Invalid policy name: {policy}")
                
        self.policy = policy or self._config.policy
        
        # Redis config (use provided values or from config)
        self._redis_config = {
            "host": redis_host or self._config.redis_host,
            "port": redis_port or self._config.redis_port,
            "pool_size": self._config.pool_size,
            "timeout_ms": self._config.timeout_ms,
            "log_file": self._config.log_file,
        }
        
        # Initialize Analytics Server if enabled (Singleton)
        if self._config.analytics_enabled:
            # We need a StatsProvider. It needs a Redis client.
            # We can use the same redis-py client we use for metrics.
            provider = StatsProvider(self.metrics_client, self._config.key_prefix)
            self.analytics = self._get_analytics_server(self._config, provider)
        
        self._client = None
        self._script_content: Optional[str] = None
        self._script_sha: Optional[str] = None
    
    @classmethod
    def from_config(cls, name: str, config: Optional[FluxConfig] = None) -> "RateLimiter":
        """
        Create a RateLimiter from a named config in flux.toml.
        """
        cfg = config or get_config()
        
        if name not in cfg.rate_limits:
            raise ValueError(
                f"Rate limit config '{name}' not found. "
                f"Available: {list(cfg.rate_limits.keys())}"
            )
        
        limit_cfg = cfg.rate_limits[name]
        
        # Parse policy if provided as string
        policy = None
        if "policy" in limit_cfg:
            policy_str = limit_cfg["policy"].lower()
            try:
                policy = RateLimitPolicy(policy_str)
            except ValueError:
                pass
        
        return cls(
            requests=limit_cfg.get("requests"),
            period=limit_cfg.get("period"),
            burst=limit_cfg.get("burst"),
            policy=policy,
            config=cfg,
        )
    
    @property
    def client(self):
        """Lazy-load Redis client."""
        if self._client is None:
            try:
                self._client = RedisClient(
                    self._redis_config["host"],
                    self._redis_config["port"],
                    self._redis_config["pool_size"],
                    self._redis_config["timeout_ms"],
                    self._redis_config["log_file"],
                    self._config.console_logging,
                )
            except ImportError:
                raise ConnectionError("Flux C++ core not found. Run 'pip install .'")
            except RuntimeError as e:
                raise ConnectionError(f"Redis connection failed: {e}")
        return self._client
    
    @property
    def metrics_client(self):
        """Lazy-load standard Redis client for metrics."""
        if not hasattr(self, "_metrics_r"):
            try:
                self._metrics_r = redis.Redis(
                    host=self._redis_config["host"],
                    port=self._redis_config["port"],
                    decode_responses=True,
                    socket_timeout=self._redis_config["timeout_ms"] / 1000.0,
                    socket_connect_timeout=self._redis_config["timeout_ms"] / 1000.0,
                )
            except Exception:
                self._metrics_r = None
        return self._metrics_r
    
    @property
    def script(self) -> Tuple[str, str]:
        """Lazy-load the Lua script content and SHA1."""
        if self._script_content is None:
            self._script_content, self._script_sha = _get_script(self.policy)
        return self._script_content, self._script_sha
    
    def _full_key(self, key: str) -> str:
        """
        Return key as-is. 
        Prefixing and hashing are now handled by the C++ engine.
        """
        return key
    
    def _now_ms(self) -> int:
        """Current time in milliseconds."""
        return int(time.time() * 1000)
    
    def _build_script_params(self, key: str, now_ms: int, endpoint: str = "") -> Tuple[List[str], List[Union[str, int]]]:
        """
        Build the keys and args for the Lua script based on the policy.
        
        Returns:
            Tuple of (keys, args) to pass to eval_script
        """
        full_key = self._full_key(key)
        
        # Base KEYS and ARGV
        keys = [full_key]
        args = []
        
        # Policy Specific Args
        if self.policy == RateLimitPolicy.GCRA:
            emission_interval_ms = int((self.period * 1000) / self.requests)
            delay_tolerance_ms = emission_interval_ms * self.burst
            args = [emission_interval_ms, delay_tolerance_ms, now_ms]
        
        elif self.policy == RateLimitPolicy.TOKEN_BUCKET:
            capacity = self.burst
            refill_time_ms = int((self.period * 1000) / self.requests)
            args = [capacity, refill_time_ms, now_ms]
            
        elif self.policy == RateLimitPolicy.LEAKY_BUCKET:
            capacity = self.burst
            leak_time_ms = int((self.period * 1000) / self.requests)
            args = [capacity, leak_time_ms, now_ms]
            
        elif self.policy == RateLimitPolicy.FIXED_WINDOW:
            keys.append(f"{full_key}:queue")
            window_ms = self.period * 1000
            args = [self.requests, window_ms, now_ms]
            
        else:
            raise ValueError(f"Unsupported policy: {self.policy}")

        # Analytics Arguments (if enabled)
        # KEYS: [1]... [2] stats_ep_key, [3] stats_global_key, [4] stats_ep_set
        # ARGV: ... [4] record_analytics, [5] endpoint_name, [6] meta_requests ...
        
        if self._config.analytics_enabled and endpoint:
            # Sampling Check
            # If sample_rate < 1.0, we probabilistically skip analytics
            record_analytics = 1
            if self._config.analytics_sample_rate < 1.0:
                if random.random() > self._config.analytics_sample_rate:
                    record_analytics = 0
            
            # If skipping, we effectively pass 0 unless we want to "send but flag".
            # The most efficient way is to send 0 so Lua skips XADD entirely.
            
            if record_analytics == 1:
                keys.append(self._config.analytics_stream)
                
                args.append(1) # record_analytics = true
                args.append(endpoint)
                args.append(self.requests)
                args.append(self.period)
                args.append(self.burst)
                args.append(self.policy.value)
                args.append(self._config.analytics_retention) # maxlen
            else:
                 # Sampled out
                 args.append(0)
        else:
            # Pass 0 to indicate no analytics
            args.append(0)
            
        return keys, args
    
    def _parse_result(self, status: int, value: Union[int, list], now_ms: int) -> RateLimitResult:
        """Parse the result from the Lua script."""
        usage = 0
        
        # New Lua scripts return {allowed_code, value, usage}
        if isinstance(value, list) and len(value) >= 2:
            retry_after_or_tokens = value[1]
            if len(value) >= 3:
                usage = int(value[2])
        else:
            retry_after_or_tokens = value

        if status == 0:  # Allowed
            # Add Jitter if enabled
            if self._config.jitter_enabled and self._config.jitter_max_ms > 0:
                jitter = random.uniform(0, self._config.jitter_max_ms / 1000.0)
                retry_after_or_tokens += jitter
            
            return RateLimitResult(
                allowed=True,
                limit=self.requests,
                remaining=retry_after_or_tokens if self.policy != RateLimitPolicy.GCRA else self.requests,
                reset_after=1 if self.policy == RateLimitPolicy.GCRA else 0, # Approximation for now
                retry_after=0.0,
                usage=usage
            )
        else:  # Denied (-1)
            # Add Jitter if enabled
            if self._config.jitter_enabled and self._config.jitter_max_ms > 0:
                jitter = random.uniform(0, self._config.jitter_max_ms / 1000.0)
                retry_after_or_tokens += jitter
            
            return RateLimitResult(
                allowed=False,
                limit=self.requests,
                remaining=0,
                reset_after=retry_after_or_tokens,
                retry_after=float(retry_after_or_tokens),
                usage=usage
            )
    

    @classmethod
    def _get_analytics_server(cls, config: FluxConfig, provider: StatsProvider) -> Optional[AnalyticsServer]:
        """Get or create singleton analytics server."""
        global _ANALYTICS_SERVER
        if _ANALYTICS_SERVER is None and config.analytics_enabled:
            _ANALYTICS_SERVER = AnalyticsServer(config, provider)
            try:
                _ANALYTICS_SERVER.start()
            except Exception as e:
                print(f"[flux] Warning: Failed to start analytics server: {e}")
                # Don't crash, just proceed without analytics
                _ANALYTICS_SERVER = None
        return _ANALYTICS_SERVER

    def hit(self, key: str, endpoint: Optional[str] = None) -> RateLimitResult:
        """
        Record a request and check if allowed.
        
        This method passes the configuration parameters to the C++ engine,
        which executes the appropriate Lua script atomically on Redis.
        
        Args:
            key: Unique identifier (e.g., "user:123" or "ip:1.2.3.4")
            endpoint: Optional name of the endpoint/function for metrics.
        
        Returns:
            RateLimitResult with allowed status
        """
        now_ms = self._now_ms()
        
        try:
            # Measure time
            start_time = time.time()

            # Note: We pass the RAW key to C++.
            # The C++ engine handles SHA256 hashing and prefixing.
            # This improves performance and security centralization.
            
            
            keys, args = self._build_script_params(key, now_ms, endpoint)
            content, sha1 = self.script
            
            # Pass the prefix separately
            prefix = self._config.key_prefix
            
            # Bypass C++ client to handle list returns correctly (until rebuild)
            hashed_keys = [f"{prefix}{hashlib.sha256(k.encode()).hexdigest()}" if i == 0 else k for i, k in enumerate(keys)]
            # The analytics keys (indices 1+) are already fully formed in _build_script_params and don't need hashing.
            # But the logic above hashed everything.
            # Actually _build_script_params returns the raw keys.
            # The C++ client hashed the first key (limit key).
            # The analytics keys are "system keys" and usually shared/not hashed the same way or already have prefix.
            # Let's fix the hashing logic here for the temporary python bypass.
            
            final_keys = []
            for i, k in enumerate(keys):
                if i == 0 and not k.startswith(prefix): 
                    # Hash the user key
                    final_keys.append(f"{prefix}{hashlib.sha256(k.encode()).hexdigest()}")
                elif i == 1 and self.policy == RateLimitPolicy.FIXED_WINDOW:
                     # Hash the queue key too
                     final_keys.append(f"{prefix}{hashlib.sha256(k.encode()).hexdigest()}")
                else:
                    # Analytics Stream Key (or other args)
                    # Use as-is (do NOT hash global connection strings/stream keys)
                    final_keys.append(k)
            
            try:
                response = self.metrics_client.evalsha(sha1, len(final_keys), *final_keys, *args)
            except redis.exceptions.NoScriptError:
                self.metrics_client.script_load(content)
                response = self.metrics_client.evalsha(sha1, len(final_keys), *final_keys, *args)
            
            # response is [status, val1, usage...]
            if isinstance(response, list):
                status = response[0]
                value = response # Pass full list
            else:
                # Should not happen with current Lua, but fallback
                status = response
                value = 0

            # DEBUG
            # print(f"[debug] redis response: {response}") 

            result = self._parse_result(int(status), value, now_ms)
            
            # Duration calculation is no longer used for metrics in Lua (captured as count only)
            # duration_ms = (time.time() - start_time) * 1000.0

            # Metrics are now recorded INSIDE the Lua script (1 RTT)
                
            return result
        
        except Exception as e:
            if self._config.fail_silently:
                # Fail Open: Log error and allow request
                import sys
                print(f"[flux] [error] Rate limit check failed (Fail Open active): {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                
                return RateLimitResult(
                    allowed=True,
                    remaining=1,
                    retry_after=0,
                    limit=self.requests
                )
            else:
                # Fail Closed: Re-raise exception
                raise ConnectionError(f"Rate limit check failed: {e}")


def preload_scripts(config: Optional[FluxConfig] = None):
    """
    Preload all Lua scripts into Redis.
    
    This ensures that the scripts are cached on the server and their SHA1 hashes
    are available for optimized EVALSHA execution. This should be called at
    application startup.
    """
    cfg = config or get_config()
    
    # Create a temporary client just for loading
    try:
        from ._flux_core import RedisClient
        client = RedisClient(
            cfg.redis_host, 
            cfg.redis_port, 
            cfg.pool_size, 
            cfg.timeout_ms,
            cfg.log_file,
            cfg.console_logging
        )
        
        # Load all policies
        count = 0
        for policy in RateLimitPolicy:
            try:
                content, sha1 = _get_script(policy)
                # Use the C++ load_script method
                server_sha = client.load_script(content)
                if server_sha == sha1:
                    count += 1
            except Exception as e:
                # Log warning but don't crash startup?
                print(f"Warning: Failed to preload script for {policy}: {e}")
                
        return count
        
    except ImportError:
        pass  # C++ extension not found
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Redis for preloading: {e}")

        
    
    def is_allowed(self, key: str) -> bool:
        """
        Check if a request is allowed.
        
        Args:
            key: Unique identifier
        
        Returns:
            True if allowed, False if rate limited
        """
        return self.hit(key).allowed
    
    def check(self, key: str) -> RateLimitResult:
        """Alias for hit()."""
        return self.hit(key)
    
    def require(self, key: str) -> RateLimitResult:
        """
        Check rate limit and raise if exceeded.
        
        Args:
            key: Unique identifier
        
        Returns:
            RateLimitResult if allowed
        
        Raises:
            RateLimitExceeded: If rate limit is exceeded
        """
        result = self.hit(key)
        
        if not result.allowed:
            raise RateLimitExceeded(key=key, retry_after=result.retry_after)
        
        return result
    
    def __repr__(self) -> str:
        return (
            f"RateLimiter(policy={self.policy.value}, "
            f"requests={self.requests}, period={self.period})"
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_limiter(
    name: Optional[str] = None,
    *,
    requests: Optional[int] = None,
    period: Optional[int] = None,
    burst: Optional[int] = None,
    policy: Optional[str] = None,
) -> RateLimiter:
    """
    Convenience function to create a rate limiter.
    """
    if name:
        return RateLimiter.from_config(name)
    
    policy_enum = None
    if policy:
        try:
            policy_enum = RateLimitPolicy(policy.lower())
        except ValueError:
            pass
    
    return RateLimiter(
        requests=requests,
        period=period,
        burst=burst,
        policy=policy_enum,
    )
