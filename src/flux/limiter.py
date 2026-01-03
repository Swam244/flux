import time
import random
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Callable, Dict, Any, Union
from dataclasses import dataclass

from ._flux_core import RedisClient
from .config import get_config, FluxConfig, RateLimitPolicy, RateLimitDefaults
from .exceptions import RateLimitExceeded, ConnectionError


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
    remaining: int
    retry_after: float
    limit: int = 0
    
    def to_headers(self) -> dict:
        """Generate standard HTTP rate limit headers."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
        }
        if not self.allowed:
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
    
    def _build_script_params(self, key: str, now_ms: int) -> Tuple[List[str], List[int]]:
        """
        Build the keys and args for the Lua script based on the policy.
        
        Returns:
            Tuple of (keys, args) to pass to eval_script
        """
        full_key = self._full_key(key)
        
        if self.policy == RateLimitPolicy.GCRA:
            # GCRA: emission_interval, delay_tolerance, now
            emission_interval_ms = int((self.period * 1000) / self.requests)
            delay_tolerance_ms = emission_interval_ms * self.burst
            return (
                [full_key],
                [emission_interval_ms, delay_tolerance_ms, now_ms]
            )
        
        elif self.policy == RateLimitPolicy.TOKEN_BUCKET:
            # Token Bucket: capacity, refill_rate, now
            capacity = self.burst
            refill_rate = self.requests / self.period  # tokens per second
            return (
                [full_key],
                [capacity, int(refill_rate), now_ms]
            )
        
        elif self.policy == RateLimitPolicy.LEAKY_BUCKET:
            # Leaky Bucket: capacity, leak_rate, now
            capacity = self.burst
            leak_rate = self.requests / self.period  # units per second
            return (
                [full_key],
                [capacity, int(leak_rate), now_ms]
            )
        
        elif self.policy == RateLimitPolicy.FIXED_WINDOW:
            # Fixed Window (FCFS): max_requests, window_ms, now
            # FCFS uses 2 keys: limit_key and queue_key
            queue_key = f"{full_key}:queue"
            window_ms = self.period * 1000
            return (
                [full_key, queue_key],
                [self.requests, window_ms, now_ms]
            )
        
        else:
            raise ValueError(f"Unsupported policy: {self.policy}")
    
    def _parse_result(self, status: int, value: float, now_ms: int) -> RateLimitResult:
        """
        Parse the Lua script result into a RateLimitResult.
        
        The interpretation depends on the policy and status.
        """
        if status == 0:
            # Allowed
            if self.policy == RateLimitPolicy.GCRA:
                # value is new TAT, calculate remaining
                new_tat = int(value)
                emission_interval_ms = int((self.period * 1000) / self.requests)
                delay_tolerance_ms = emission_interval_ms * self.burst
                remaining = int((delay_tolerance_ms - (new_tat - now_ms)) / emission_interval_ms)
                remaining = max(0, min(remaining, self.burst - 1))
            elif self.policy in (RateLimitPolicy.TOKEN_BUCKET, RateLimitPolicy.LEAKY_BUCKET):
                # value is remaining tokens/capacity
                remaining = int(value)
            else:
                # Fixed window - value is queue position (0 = immediate)
                remaining = self.requests - 1
            
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                retry_after=0,
                limit=self.requests,
            )
        else:
            # Denied - value is retry_after in seconds
            retry_after = float(value)
            
            # Add Jitter if enabled
            if self._config.jitter_enabled and self._config.jitter_max_ms > 0:
                jitter = random.uniform(0, self._config.jitter_max_ms / 1000.0)
                retry_after += jitter
            
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=retry_after,
                limit=self.requests,
            )
    
    def hit(self, key: str) -> RateLimitResult:
        """
        Record a request and check if allowed.
        
        This method passes the configuration parameters to the C++ engine,
        which executes the appropriate Lua script atomically on Redis.
        
        Args:
            key: Unique identifier (e.g., "user:123" or "ip:1.2.3.4")
        
        Returns:
            RateLimitResult with allowed status
        """
        now_ms = self._now_ms()
        
        try:
            # Note: We pass the RAW key to C++.
            # The C++ engine handles SHA256 hashing and prefixing.
            # This improves performance and security centralization.
            
            
            keys, args = self._build_script_params(key, now_ms)
            content, sha1 = self.script
            
            # Pass the prefix separately
            prefix = self._config.key_prefix
            
            # Call the C++ engine with raw keys and prefix
            status, value = self.client.eval_script(sha1, content, keys, args, prefix)
            
            return self._parse_result(int(status), value, now_ms)
        
        except Exception as e:
            if self._config.fail_silently:
                # Fail Open: Log error and allow request
                import sys
                print(f"[flux] [error] Rate limit check failed (Fail Open active): {e}", file=sys.stderr)
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
