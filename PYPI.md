# flux-limiter

**Flux** is a high-performance framework-agnostic rate limiter for Python that just works. It's built on a C++ core to respect your latency budget, and it plugs straight into **Django**, **FastAPI**, and **Flask**.

Whether you're protecting a public API or just trying to stop a single user from spamming your login form, Flux handles it without the boilerplate.

## Installation

```bash
pip install flux-limiter
```
or
```bash
uv add flux-limiter
```

*(You'll need a Redis server running, but you probably already have one of those.)*

## How to use it

The easiest way is the decorator. It figures out what framework you're using and sends the right 429 response automatically.

```python
from flux import rate_limit

# Allow 100 requests every minute
@rate_limit(requests=100, period=60)
def my_api_endpoint(request):
    return {"data": "This is protected"}
```

That's it. No middleware to configure, no exception handlers to write.

### Framework Examples

**FastAPI**
```python
from fastapi import FastAPI, Request
from flux import rate_limit

app = FastAPI()

@app.get("/")
@rate_limit(requests=5, period=10)
async def root(request: Request):
    return {"message": "Hello World"}
```

**Django**
```python
from django.http import JsonResponse
from flux import rate_limit

@rate_limit(requests=20, period=60)
def my_view(request):
    return JsonResponse({"ok": True})
```

**Flask**
```python
from flask import Flask
from flux import rate_limit

app = Flask(__name__)

@app.route("/login")
@rate_limit(requests=5, period=300) # 5 tries every 5 minutes
def login():
    return "Login Page"
```

## Configuration

You don't need a config file to get started, but when you're ready to tweak things, run:

```bash
python -m flux.cli init
```

This generates a `flux.toml` file where you can adjust everything:

### flux.toml Reference

The `flux.toml` file is where you configure the behavior of the rate limiter.

#### Redis Settings `[redis]`

| Option | Default | Description |
| :--- | :--- | :--- |
| `host` | `"127.0.0.1"` | Redis server hostname. |
| `port` | `6379` | Redis server port. |
| `pool_size` | `5` | Number of connections in the pool. |
| `timeout_ms` | `200` | Connection timeout in milliseconds. |

#### Flux Core Settings `[flux]`

| Option | Default | Description |
| :--- | :--- | :--- |
| `key_prefix` | `"flux:"` | Prefix for all keys stored in Redis. |
| `fail_silently` | `true` | If `true`, allows requests to proceed if Redis is down (Fail Open). |
| `console_logging` | `false` | Enable debug logging to stdout. |
| `jitter_enabled` | `true` | Adds random variance to `Retry-After` to prevent thundering herds. |
| `jitter_max_ms` | `500` | Max jitter in milliseconds (if enabled). |

#### Analytics Settings `[analytics]`

| Option | Default | Description |
| :--- | :--- | :--- |
| `enabled` | `false` | Enable the background analytics server. |
| `port` | `4444` | Port for the metrics server (`/metrics`). |
| `stream` | `"flux:events"` | Redis stream key for events. |
| `retention` | `100000` | Max stream length (events). |
| `sample_rate` | `1.0` | Sampling rate (0.0 to 1.0) for logging. |

#### Rate Limit Defaults `[rate_limit]`

| Option | Default | Description |
| :--- | :--- | :--- |
| `policy` | `"gcra"` | Algorithm: `"gcra"`, `"token_bucket"`, `"leaky_bucket"`, `"fixed_window"`. |
| `requests` | `100` | Number of requests allowed per period. |
| `period` | `60` | Time period in seconds. |
| `burst` | `requests` | Burst capacity (defaults to `requests` count). |

---

### Complete Configuration Example

Here is a complete `flux.toml` file with all options explained:

```toml
# =============================================================================
# Flux Configuration
# =============================================================================

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
fail_silently = true        # Fail Open: Allow requests if Redis is down
console_logging = false     # Enable for dev debugging

# Jitter prevents Thundering Herd
jitter_enabled = true
jitter_max_ms = 500

# -----------------------------------------------------------------------------
# Analytics & Monitoring
# -----------------------------------------------------------------------------
[analytics]
enabled = true
port = 4444
stream = "flux:events"
retention = 100000
sample_rate = 1.0           # 1.0 = Log 100% of requests

# -----------------------------------------------------------------------------
# Default Rate Limiting Settings
# -----------------------------------------------------------------------------
[rate_limit]
policy = "gcra"             # Recommended: Smooths out traffic
requests = 100              # 100 requests...
period = 60                 # ...per 60 seconds

# -----------------------------------------------------------------------------
# Named Rate Limits
# -----------------------------------------------------------------------------
[rate_limits.api_tier_1]
requests = 1000
period = 3600
policy = "gcra"

[rate_limits.strict_login]
requests = 5
period = 300
policy = "token_bucket"
```

### Named Limits

Instead of hardcoding numbers in your code, you can define them in `flux.toml` (as seen above) and use them by name:

```python
@rate_limit(name="api_tier_1")
def expensive_call():
    pass
```


## Analytics & Monitoring

Flux comes with a built-in lightweight analytics server that exposes metrics.

To enable it, add this to your `flux.toml`:

```toml
[analytics]
enabled = true
port = 4444          # Default port
sample_rate = 1.0    # Log 100% of requests
```

Once enabled, Flux will start a background thread serving metrics at:
`http://localhost:4444/metrics`

You can view the metrics by running this:
```bash
python -m flux monitor
```

You can hit `/metrics` to get the follwing data:
- Total requests
- Rate limit hits (allowed)
- Rate limit blocks (429s)

## Why isn't this just Python?

Because speed matters. The core logic of Flux is written in **C++** and communicates directly with Redis using optimized Lua scripts. 

It supports multiple algorithms depending on your needs:

- **GCRA**: The default. Smooth, leaky-bucket style limiting. Great for APIs.
- **Token Bucket**: Allows for bursts (e.g., let users traverse a paginated list quickly) but enforces a long-term average.
- **Fixed Window**: Simple counters. Good for "N actions per day".

## Read More

👉 **[Check out blog for more details](https://swayamjain.com/blog/building-flux)**

## License

MIT
