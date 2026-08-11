from pathlib import Path

from fastapi.testclient import TestClient

from resumeranker_server import (
    DEFAULT_CORS_ORIGINS,
    LlmContextualScores,
    app,
    get_cors_origins,
    get_server_host,
    is_safe_path,
)


def test_is_safe_path_allows_child_path(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "resumes"
    root.mkdir()
    resume = root / "candidate.txt"
    resume.write_text("sample", encoding="utf-8")
    monkeypatch.setenv("RESUMERANKER_APPROVED_ROOT", str(root))

    assert is_safe_path(str(resume), str(root)) is True


def test_is_safe_path_rejects_sibling_with_matching_prefix(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "resumes"
    sibling = tmp_path / "resumes_backup"
    root.mkdir()
    sibling.mkdir()
    outside = sibling / "candidate.txt"
    outside.write_text("sample", encoding="utf-8")
    monkeypatch.setenv("RESUMERANKER_APPROVED_ROOT", str(root))

    assert is_safe_path(str(outside), str(root)) is False


def test_filesystem_access_is_disabled_without_approved_root(tmp_path: Path, monkeypatch) -> None:
    resume = tmp_path / "candidate.txt"
    resume.write_text("sample", encoding="utf-8")
    monkeypatch.delenv("RESUMERANKER_APPROVED_ROOT", raising=False)

    assert is_safe_path(str(resume), str(tmp_path)) is False


def test_server_host_stays_loopback_without_explicit_exposure(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.delenv("RESUMERANKER_ALLOW_NETWORK_EXPOSURE", raising=False)

    assert get_server_host() == "127.0.0.1"


def test_contextual_score_defaults_are_independent() -> None:
    first = LlmContextualScores()
    second = LlmContextualScores()

    first.projects.score = 90

    assert second.projects.score == 0


def test_status_endpoint_reports_ready() -> None:
    client = TestClient(app)

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_cors_origins_default_to_explicit_local_hosts(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert get_cors_origins() == DEFAULT_CORS_ORIGINS.split(",")


def test_cors_origins_are_parsed_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, http://localhost:5173 ")

    assert get_cors_origins() == ["https://app.example.com", "http://localhost:5173"]


def test_browser_cors_preflight_allows_configured_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/status",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
