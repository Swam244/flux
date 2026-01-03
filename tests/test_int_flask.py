import pytest
import sys
import os
import json

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux import rate_limit

# ------------------------------------------------------------------
# TESTS
# ------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("SKIP_REDIS_TESTS", "0") == "1", 
    reason="Redis not available"
)
class TestFlaskIntegration:
    
    @pytest.fixture
    def client(self):
        try:
            from flask import Flask
        except ImportError:
            pytest.skip("Flask not installed")
            
        app = Flask(__name__)
        
        @app.route("/test")
        @rate_limit(requests=10, period=10, policy="gcra")
        def test_route():
            return {"status": "ok"}
            
        return app.test_client()

    def test_flask_rate_limit(self, client):
        # 1. Allow (limit 10)
        for _ in range(10):
            resp = client.get("/test")
            assert resp.status_code == 200
        
        # 2. Block
        resp = client.get("/test")
        assert resp.status_code == 429
        
        assert "retry_after" in resp.json
        assert resp.json["error"] == "Too Many Requests"
