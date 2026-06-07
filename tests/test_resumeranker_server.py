from pathlib import Path

from fastapi.testclient import TestClient

from resumeranker_server import LlmContextualScores, app, is_safe_path


def test_is_safe_path_allows_child_path(tmp_path: Path) -> None:
    root = tmp_path / "resumes"
    root.mkdir()
    resume = root / "candidate.txt"
    resume.write_text("sample", encoding="utf-8")

    assert is_safe_path(str(resume), str(root)) is True


def test_is_safe_path_rejects_sibling_with_matching_prefix(tmp_path: Path) -> None:
    root = tmp_path / "resumes"
    sibling = tmp_path / "resumes_backup"
    root.mkdir()
    sibling.mkdir()
    outside = sibling / "candidate.txt"
    outside.write_text("sample", encoding="utf-8")

    assert is_safe_path(str(outside), str(root)) is False


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
