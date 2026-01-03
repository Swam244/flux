import pytest
import sys
import os
import json

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from flux import rate_limit

# ------------------------------------------------------------------
# DJANGO CONFIGURATION
# ------------------------------------------------------------------
try:
    from django.conf import settings
    if not settings.configured:
        settings.configure(
            SECRET_KEY="test-secret",
            ROOT_URLCONF=__name__,
            MIDDLEWARE=[
                "django.middleware.common.CommonMiddleware",
            ],
            INSTALLED_APPS=[],
            ALLOWED_HOSTS=["testserver"],
        )
    import django
    django.setup()
    
    from django.http import HttpResponse, JsonResponse
    from django.urls import path
    from django.urls import path
    from django.test import Client, RequestFactory

    # ------------------------------------------------------------------
    # VIEWS
    # ------------------------------------------------------------------
    @rate_limit(requests=10, period=10, policy="gcra")
    def my_view(request):
        return JsonResponse({"status": "ok"})

    urlpatterns = [
        path("test", my_view),
    ]

except ImportError:
    pass


# ------------------------------------------------------------------
# TESTS
# ------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("SKIP_REDIS_TESTS", "0") == "1", 
    reason="Redis not available"
)
@pytest.mark.skipif("django" not in sys.modules, reason="Django not installed")
class TestDjangoIntegration:
    
    def test_django_rate_limit(self):
        client = Client()
        
        # 1. Allow (limit 10)
        for _ in range(10):
            resp = client.get("/test")
            assert resp.status_code == 200
        
        # 2. Block
        resp = client.get("/test")
        assert resp.status_code == 429
        
        content = json.loads(resp.content)
        assert "retry_after" in content
        assert content["error"] == "Too Many Requests"
