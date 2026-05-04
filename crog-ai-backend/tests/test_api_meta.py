from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_exposes_staging_service_identity(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "staging")

    client = TestClient(create_app())

    assert client.get("/healthz").json() == {
        "status": "ok",
        "env": "staging",
        "service": "crog-ai-backend",
    }


def test_version_exposes_deploy_metadata(monkeypatch) -> None:
    monkeypatch.setenv("COMMIT_SHA", "abc123")
    monkeypatch.setenv("GIT_BRANCH", "main")
    monkeypatch.setenv("BUILD_TIME", "2026-05-04T21:00:00Z")

    client = TestClient(create_app())

    assert client.get("/version").json() == {
        "commit": "abc123",
        "branch": "main",
        "build_time": "2026-05-04T21:00:00Z",
    }


def test_version_falls_back_without_deploy_metadata(monkeypatch) -> None:
    monkeypatch.delenv("COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_BRANCH", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)

    client = TestClient(create_app())
    payload = client.get("/version").json()

    assert payload["commit"] == "unknown"
    assert payload["branch"] == "unknown"
    assert payload["build_time"]
