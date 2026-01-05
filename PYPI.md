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

The `flux.toml` file is where you configure the behavior of the rate limiter. Here are all the available options:

```toml
[redis]
host = "127.0.0.1"
port = 6379
pool_size = 10
timeout_ms = 200

[flux]
# Prefix for all keys stored in Redis
key_prefix = "flux:"

# If Redis is unreachable, fail_silently=true allows the request to proceed (Fail Open).
# fail_silently=false raises a ConnectionError (Fail Closed).
fail_silently = true       

# Enable debug logging to stdout for development
console_logging = false    

# Jitter adds random variance to the Retry-After header calculations.
# This prevents "thundering herd" issues where all clients retry at the exact same millisecond.
jitter_enabled = true      
jitter_max_ms = 500        # Max jitter in milliseconds

[rate_limit]
# Default policy for rate limiters that don't specify one
# Options: "gcra", "token_bucket", "leaky_bucket", "fixed_window"
policy = "gcra"
requests = 100
period = 60
```

### Named Limits

Instead of hardcoding numbers in your code, you can define them in `flux.toml`:

```toml
[rate_limits.api_tier_1]
requests = 1000
period = 3600
policy = "gcra"
```

And then use them by name:

```python
@rate_limit(name="api_tier_1")
def expensive_call():
    pass
```

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
