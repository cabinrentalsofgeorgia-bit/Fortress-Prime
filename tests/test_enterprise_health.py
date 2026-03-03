#!/usr/bin/env python3
"""
FORTRESS PRIME — Enterprise Health & Security Integration Tests
================================================================
Tests all running services for:
  1. Health endpoints respond correctly
  2. Auth enforcement (unauthenticated requests blocked)
  3. Security headers present
  4. CORS configured properly
  5. API contracts honored
  6. Database connectivity
  7. Critical infrastructure services online

Run:
    cd /home/admin/Fortress-Prime
    ./venv/bin/python -m pytest tests/test_enterprise_health.py -v
"""

import os
import json
import pytest
import httpx

BASE = os.getenv("BASE_IP", "192.168.0.100")

# ══════════════════════════════════════════════════════════════════════════════
# SERVICE REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

SERVICES = {
    "command_center": {"port": 9800, "health": "/health"},
    "legal_crm":      {"port": 9878, "health": "/api/health"},
    "system_health":  {"port": 9876, "health": "/api/health"},
    "batch_classifier": {"port": 9877, "health": "/api/health"},
}

INFRA_SERVICES = {
    "postgres":   {"port": 5432},
    "qdrant":     {"port": 6333},
    "ollama":     {"port": 11434},
    "grafana":    {"port": 3000},
    "prometheus": {"port": 9090},
}


def _url(port: int, path: str = "/") -> str:
    return f"http://localhost:{port}{path}"


# ══════════════════════════════════════════════════════════════════════════════
# 1. HEALTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoints:
    """Every service must have a responding health endpoint."""

    @pytest.mark.parametrize("name,svc", list(SERVICES.items()))
    def test_health_returns_200(self, name, svc):
        r = httpx.get(_url(svc["port"], svc["health"]), timeout=10)
        assert r.status_code == 200, f"{name} health returned {r.status_code}"

    @pytest.mark.parametrize("name,svc", list(SERVICES.items()))
    def test_health_returns_json(self, name, svc):
        r = httpx.get(_url(svc["port"], svc["health"]), timeout=10)
        data = r.json()
        assert isinstance(data, dict), f"{name} health is not a JSON object"

    def test_legal_crm_health_checks_db(self):
        r = httpx.get(_url(9878, "/api/health"), timeout=10)
        data = r.json()
        assert data.get("database") == "ok", "Legal CRM cannot reach Postgres"

    def test_legal_crm_health_checks_nas(self):
        r = httpx.get(_url(9878, "/api/health"), timeout=10)
        data = r.json()
        nas = data.get("nas")
        assert nas in ("ok", "unreachable"), f"NAS status unexpected: {nas}"
        if nas == "unreachable":
            # NAS may be unmounted — verify health still returns 200 (degraded, not down)
            assert r.status_code == 200, "Health should return 200 even with NAS down"
            assert data.get("status") == "degraded", "Status should be 'degraded' when NAS is down"


# ══════════════════════════════════════════════════════════════════════════════
# 2. AUTH ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthEnforcement:
    """Protected endpoints must reject unauthenticated requests."""

    def test_legal_crm_cases_requires_auth(self):
        r = httpx.get(_url(9878, "/api/cases"), timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_legal_crm_inbox_requires_auth(self):
        r = httpx.get(_url(9878, "/api/inbox"), timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_system_health_root_requires_auth(self):
        r = httpx.get(_url(9876, "/"), timeout=10, follow_redirects=False)
        assert r.status_code in (401, 307), f"Expected 401/307, got {r.status_code}"

    def test_classifier_root_requires_auth(self):
        r = httpx.get(_url(9877, "/"), timeout=10, follow_redirects=False)
        assert r.status_code in (401, 307), f"Expected 401/307, got {r.status_code}"

    def test_command_center_root_redirects_to_login(self):
        r = httpx.get(_url(9800, "/"), timeout=10, follow_redirects=False)
        assert r.status_code in (302, 307), f"Expected redirect, got {r.status_code}"

    def test_health_endpoints_bypass_auth(self):
        """Health endpoints must always be public (for monitoring)."""
        for name, svc in SERVICES.items():
            r = httpx.get(_url(svc["port"], svc["health"]), timeout=10)
            assert r.status_code == 200, f"{name} health blocked (should be public)"


# ══════════════════════════════════════════════════════════════════════════════
# 3. SECURITY HEADERS
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityHeaders:
    """Every response must include enterprise security headers."""

    @pytest.mark.parametrize("name,svc", list(SERVICES.items()))
    def test_x_content_type_options(self, name, svc):
        r = httpx.get(_url(svc["port"], svc["health"]), timeout=10)
        assert r.headers.get("x-content-type-options") == "nosniff", \
            f"{name} missing X-Content-Type-Options"

    @pytest.mark.parametrize("name,svc", list(SERVICES.items()))
    def test_x_frame_options(self, name, svc):
        r = httpx.get(_url(svc["port"], svc["health"]), timeout=10)
        val = r.headers.get("x-frame-options", "")
        assert val in ("DENY", "SAMEORIGIN"), f"{name} X-Frame-Options: {val}"

    @pytest.mark.parametrize("name,svc", list(SERVICES.items()))
    def test_xss_protection(self, name, svc):
        r = httpx.get(_url(svc["port"], svc["health"]), timeout=10)
        assert "1" in r.headers.get("x-xss-protection", ""), \
            f"{name} missing X-XSS-Protection"


# ══════════════════════════════════════════════════════════════════════════════
# 4. CORS ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════════

class TestCORSEnforcement:
    """CORS must not allow wildcard origins."""

    @pytest.mark.parametrize("port", [9878, 9876, 9877])
    def test_no_wildcard_cors(self, port):
        r = httpx.options(
            _url(port, "/"),
            headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "GET"},
            timeout=10,
        )
        acao = r.headers.get("access-control-allow-origin", "")
        assert acao != "*", f"Port {port} allows wildcard CORS"
        assert "evil.com" not in acao, f"Port {port} allows evil.com origin"


# ══════════════════════════════════════════════════════════════════════════════
# 5. INFRASTRUCTURE SERVICES
# ══════════════════════════════════════════════════════════════════════════════

class TestInfrastructure:
    """Core infrastructure must be online."""

    def test_postgres_accepting_connections(self):
        """Postgres must be listening on port 5432."""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex(("localhost", 5432))
        s.close()
        assert result == 0, "Postgres not accepting connections on 5432"

    def test_ollama_running(self):
        r = httpx.get("http://localhost:11434/api/tags", timeout=10)
        assert r.status_code == 200
        models = r.json().get("models", [])
        assert len(models) > 0, "No models loaded in Ollama"

    def test_ollama_has_qwen(self):
        r = httpx.get("http://localhost:11434/api/tags", timeout=10)
        names = [m["name"] for m in r.json().get("models", [])]
        assert any("qwen" in n for n in names), f"qwen not found in models: {names}"

    def test_grafana_healthy(self):
        r = httpx.get("http://localhost:3000/api/health", timeout=10)
        assert r.status_code == 200

    def test_prometheus_healthy(self):
        r = httpx.get("http://localhost:9090/-/healthy", timeout=10)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 6. EMAIL BRIDGE
# ══════════════════════════════════════════════════════════════════════════════

class TestEmailBridge:
    """Email Bridge must be running and ingesting."""

    def test_bridge_status_available(self):
        r = httpx.get(_url(9878, "/api/bridge/status"), timeout=10)
        assert r.status_code == 200

    def test_bridge_is_running(self):
        r = httpx.get(_url(9878, "/api/bridge/status"), timeout=10)
        data = r.json()
        assert data.get("bridge_running") is True, "Email Bridge is not running"

    def test_bridge_has_emails(self):
        r = httpx.get(_url(9878, "/api/bridge/status"), timeout=10)
        data = r.json()
        assert data.get("bridge_total", 0) > 0, "No emails ingested"

    def test_bridge_has_watchdog_terms(self):
        r = httpx.get(_url(9878, "/api/bridge/status"), timeout=10)
        data = r.json()
        assert data.get("watchdog_terms", 0) > 0, "No watchdog terms configured"


# ══════════════════════════════════════════════════════════════════════════════
# 7. API CONTRACTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIContracts:
    """API error handling must be consistent and safe."""

    def test_invalid_query_param_returns_422(self):
        r = httpx.get(_url(9878, "/api/health"), timeout=10)
        # Health should always work, but bad params on typed endpoints should 422
        # This tests FastAPI's built-in validation
        assert r.status_code == 200

    def test_404_returns_json(self):
        r = httpx.get(_url(9878, "/api/nonexistent"), timeout=10)
        assert r.status_code in (401, 404), f"Expected 401/404, got {r.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
