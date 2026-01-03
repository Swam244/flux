import pytest
import sys
import os
import time
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux import rate_limit, RateLimitExceeded, preload_scripts

app = FastAPI()

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
from flux.config import get_config
get_config().fail_silently = False

@app.on_event("startup")
async def startup_event():
    try:
        preload_scripts()
    except Exception:
        pass

# ------------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------------

# 1. GCRA (Default)
@app.get("/gcra")
@rate_limit(requests=10, period=10, policy="gcra")
async def gcra_endpoint():
    return {"status": "ok"}

# 2. Token Bucket
@app.get("/token_bucket")
@rate_limit(requests=10, period=10, policy="token_bucket")
async def tb_endpoint():
    return {"status": "ok"}

# 3. Leaky Bucket
@app.get("/leaky_bucket")
@rate_limit(requests=10, period=10, policy="leaky_bucket")
async def lb_endpoint():
    return {"status": "ok"}

# 4. Fixed Window
@app.get("/fixed_window")
@rate_limit(requests=10, period=10, policy="fixed_window")
async def fw_endpoint():
    return {"status": "ok"}

# 5. User ID Limit
@app.get("/user")
@rate_limit(requests=5, period=5, key=lambda r: r.headers.get("X-User-ID"))
async def user_endpoint(request: Request):
    return {"user": request.headers.get("X-User-ID")}

client = TestClient(app)

# ------------------------------------------------------------------
# TESTS
# ------------------------------------------------------------------
@pytest.mark.skipif(os.environ.get("SKIP_REDIS_TESTS", "0") == "1", reason="Redis not available")
class TestFastAPIIntegration:
    
    @pytest.mark.parametrize("endpoint", ["/gcra", "/token_bucket", "/leaky_bucket", "/fixed_window"])
    def test_policies(self, endpoint):
        """Verify all policies allow up to limit and then block."""
        # 1. Exhaust limit (10 requests)
        for _ in range(10):
            resp = client.get(endpoint)
            assert resp.status_code == 200
            
        # 2. Exceed limit
        resp = client.get(endpoint)
        assert resp.status_code == 429
        data = resp.json()
        assert "retry_after" in data
        
    def test_user_isolation(self):
        """Verify different users have independent limits."""
        # User A exhausts limit (5)
        for _ in range(5):
            client.get("/user", headers={"X-User-ID": "alice"})
            
        resp = client.get("/user", headers={"X-User-ID": "alice"})
        assert resp.status_code == 429
        
        # User B still allowed
        resp = client.get("/user", headers={"X-User-ID": "bob"})
        assert resp.status_code == 200
