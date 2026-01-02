
import pytest
import sys
import os
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux import rate_limit, RateLimitExceeded, preload_scripts

# Initialize App
app = FastAPI()

# Preload scripts (mock startup)
try:
    preload_scripts()
except Exception:
    pass # Redis might be down, handled in tests

# 1. Basic Rate Limit: IP based (default)
@app.get("/ip-limit")
@rate_limit(requests=1, period=10, burst=1)
async def ip_limit(request: Request):
    return {"status": "ok"}

# 2. User ID based Limit (Header)
@app.get("/user-limit")
@rate_limit(requests=1, period=10, burst=1, key=lambda r: r.headers.get("X-User-ID"))
async def user_limit(request: Request):
    return {"user": request.headers.get("X-User-ID")}

# 3. Custom Error Handling (Flux raises RateLimitExceeded, FastAPI can catch it)
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": "Too Fast!", "retry": exc.retry_after},
        headers=exc.to_headers()
    )


client = TestClient(app)

@pytest.mark.skipif(
    os.environ.get("SKIP_REDIS_TESTS", "0") == "1",
    reason="Redis not available"
)
class TestFastAPI:
    def test_ip_rate_limiting(self):
        # 1. Allow
        resp = client.get("/ip-limit")
        assert resp.status_code == 200
        
        # 2. Block
        resp = client.get("/ip-limit")
        assert resp.status_code == 429
        data = resp.json()
        assert data["detail"] == "Too Fast!"

    def test_user_id_isolation(self):
        # User A: 1 request (Allowed)
        client.get("/user-limit", headers={"X-User-ID": "alice"})
        
        # User A: Blocked
        resp = client.get("/user-limit", headers={"X-User-ID": "alice"})
        assert resp.status_code == 429
        
        # User B: Allowed (different key)
        resp = client.get("/user-limit", headers={"X-User-ID": "bob"})
        assert resp.status_code == 200
