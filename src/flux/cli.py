"""
Flux CLI - Configuration Generation Tool
"""

import sys
import argparse
from pathlib import Path

# Template for flux.toml
FLUX_TOML_TEMPLATE = """# =============================================================================
# Flux Configuration
# =============================================================================
# This file configures the Flux rate limiter.
# Works with Django, FastAPI, Flask, or any Python application.

# -----------------------------------------------------------------------------
# Redis Connection Settings
# -----------------------------------------------------------------------------
[redis]
host = "127.0.0.1"
port = 6379
pool_size = 5
timeout_ms = 200

# -----------------------------------------------------------------------------
# Flux Core Settings
# -----------------------------------------------------------------------------
[flux]
key_prefix = "flux:"
log_file = "flux_debug.log"

# -----------------------------------------------------------------------------
# Default Rate Limiting Settings
# -----------------------------------------------------------------------------
# These are used when creating a RateLimiter() without explicit parameters.
#
# Supported policies:
#   - "gcra"          : Generic Cell Rate Algorithm (smooth, recommended)
#   - "token_bucket"  : Token Bucket (bursty traffic)
#   - "leaky_bucket"  : Leaky Bucket (smooth output)
#   - "fixed_window"  : Fixed Window / FCFS (simple, but can have burst at window edges)

[rate_limit]
policy = "gcra"
requests = 100          # Requests per period
period = 60             # Period in seconds
burst = 10              # Burst capacity (optional, defaults to requests)

# -----------------------------------------------------------------------------
# Named Rate Limit Configurations
# -----------------------------------------------------------------------------
# Define presets for different application parts.
# Usage: @rate_limit(name="api", key=...)
#
# Example:
#   [rate_limits.api]
#   requests = 1000
#   period = 60

[rate_limits.default]
requests = 100
period = 60
policy = "gcra"

[rate_limits.strict]
requests = 5
period = 60
policy = "token_bucket"

[rate_limits.high_throughput]
requests = 10000
period = 60
policy = "gcra"
"""


def init_config():
    """Generate a flux.toml configuration file."""
    parser = argparse.ArgumentParser(description="Initialize Flux configuration")
    parser.add_argument(
        "path", 
        nargs="?", 
        default="flux.toml",
        help="Path where flux.toml should be created (default: ./flux.toml) where your uv.lock or requirements.txt lives."
    )
    parser.add_argument(
        "--force", "-f", 
        action="store_true", 
        help="Overwrite existing file"
    )
    
    args = parser.parse_args()
    target_path = Path(args.path)
    
    if target_path.exists() and not args.force:
        print(f"Error: '{target_path}' already exists. Use --force to overwrite.")
        sys.exit(1)
        
    try:
        target_path.write_text(FLUX_TOML_TEMPLATE)
        print(f"Generated configuration file at: {target_path.absolute()}")
    except Exception as e:
        print(f"Error writing file: {e}")
        sys.exit(1)


def main():
    """Entry point for python -m flux.cli"""
    parser = argparse.ArgumentParser(description="Flux Rate Limiter CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # init command
    init_parser = subparsers.add_parser("init", help="Generate flux.toml config file")
    init_parser.add_argument(
        "path", 
        nargs="?", 
        default="flux.toml",
        help="Path where flux.toml should be created"
    )
    init_parser.add_argument(
        "--force", "-f", 
        action="store_true", 
        help="Overwrite existing file"
    )
    
    args = parser.parse_args()
    
    if args.command == "init":
        # Manually reconstruct args for init_config
        # This is a bit hacky but keeps logic simple
        sys.argv = [sys.argv[0]] 
        if args.force:
            sys.argv.append("--force")
        if args.path:
            sys.argv.append(args.path)
        init_config()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
