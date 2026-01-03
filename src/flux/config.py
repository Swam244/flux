"""
Flux Configuration Loader

Loads Redis connection settings and rate limiting configuration from flux.toml
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Union, Dict, Any
from enum import Enum

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


class RateLimitPolicy(Enum):
    """Supported rate limiting algorithms."""
    GCRA = "gcra"                    # Generic Cell Rate Algorithm
    TOKEN_BUCKET = "token_bucket"    # Token Bucket
    LEAKY_BUCKET = "leaky_bucket"    # Leaky Bucket
    FIXED_WINDOW = "fixed_window"    # Fixed Window (FCFS)


@dataclass
class RateLimitDefaults:
    """Default rate limiting settings."""
    requests: int = 100              # Requests per period
    period: int = 60                 # Period in seconds
    burst: Optional[int] = None      # Burst capacity (defaults to requests)
    
    def __post_init__(self):
        if self.burst is None:
            self.burst = self.requests


@dataclass
class FluxConfig:
    """Flux configuration."""
    # Redis settings
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    pool_size: int = 5
    timeout_ms: int = 200
    
    # Flux settings
    key_prefix: str = "flux:"
    log_file: str = "flux_debug.log"
    fail_silently: bool = True  # If True, allow requests when Redis is down
    console_logging: bool = False # If True, enable console logging
    
    # Rate limiting settings
    policy: RateLimitPolicy = RateLimitPolicy.GCRA
    rate_limit_defaults: RateLimitDefaults = field(default_factory=RateLimitDefaults)
    
    # Named rate limit configs (e.g., {"api": {...}, "login": {...}})
    rate_limits: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def load_config(config_path: Optional[Union[str, Path]] = None) -> FluxConfig:
    """
    Load configuration from flux.toml
    
    Args:
        config_path: Path to config file. If None, searches common locations.
    
    Returns:
        FluxConfig instance
    """
    if tomllib is None:
        # No TOML parser, return defaults
        return FluxConfig()
    
    # Find config file
    if config_path is None:
        config_path = os.environ.get("FLUX_CONFIG")
    
    if config_path is None:
        search_paths = [
            Path.cwd() / "flux.toml",
            Path.cwd() / "config" / "flux.toml",
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break
    
    if config_path is None or not Path(config_path).exists():
        return FluxConfig()
    
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return FluxConfig()
    
    redis = data.get("redis", {})
    flux = data.get("flux", {})
    rate_limit = data.get("rate_limit", {})
    rate_limits = data.get("rate_limits", {})
    
    # Parse policy
    policy_str = rate_limit.get("policy", "gcra").lower()
    try:
        policy = RateLimitPolicy(policy_str)
    except ValueError:
        policy = RateLimitPolicy.GCRA
    
    # Parse defaults
    defaults = RateLimitDefaults(
        requests=rate_limit.get("requests", 100),
        period=rate_limit.get("period", 60),
        burst=rate_limit.get("burst"),
    )
    
    return FluxConfig(
        redis_host=redis.get("host", "127.0.0.1"),
        redis_port=redis.get("port", 6379),
        pool_size=redis.get("pool_size", 5),
        timeout_ms=redis.get("timeout_ms", 200),
        key_prefix=flux.get("key_prefix", "flux:"),
        log_file=flux.get("log_file", "flux_debug.log"),
        fail_silently=flux.get("fail_silently", True),
        console_logging=flux.get("console_logging", False),
        policy=policy,
        rate_limit_defaults=defaults,
        rate_limits=rate_limits,
    )


# Global config (lazy loaded)
_config: Optional[FluxConfig] = None


def get_config() -> FluxConfig:
    """Get the global config (loads once)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> FluxConfig:
    """Force reload the config from disk."""
    global _config
    _config = load_config()
    return _config

