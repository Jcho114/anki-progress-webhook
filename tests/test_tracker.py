"""Progress tracker server tests."""

from __future__ import annotations

from pathlib import Path

from server.tracker import ProgressServer


def _client(tmp_path: Path):
    return ProgressServer(db_path=tmp_path / "test.db").app.test_client()


def test_board_empty_ok(tmp_path: Path):
    """Test plan:
    1. GET / with an empty database.
    2. Expect 200 HTML and the empty-state copy (no rows yet).
    """
    resp = _client(tmp_path).get("/")
    assert resp.status_code == 200
    assert b"No progress yet" in resp.data


def test_ingest_and_leaderboard(tmp_path: Path):
    """Test plan:
    1. POST two learners' Kaishi progress to /anki.
    2. Expect saved counts in JSON responses.
    3. GET /?deck=Kaishi 1.5k → higher seen_pct learner appears first.
    """
    client = _client(tmp_path)
    payload_a = {
        "identifier": "a@example.com",
        "sent_at": "2026-01-01T00:00:00+00:00",
        "decks": [
            {
                "name": "Kaishi 1.5k",
                "deck_id": 1,
                "depth": 1,
                "cards": 100,
                "new": 40,
                "learning": 10,
                "young": 30,
                "mature": 20,
                "suspended": 0,
                "seen_pct": 60.0,
            }
        ],
    }
    payload_b = {
        "identifier": "b@example.com",
        "decks": [
            {
                "name": "Kaishi 1.5k",
                "cards": 100,
                "new": 80,
                "learning": 5,
                "young": 10,
                "mature": 5,
                "suspended": 0,
                "seen_pct": 20.0,
            }
        ],
    }
    assert client.post("/anki", json=payload_a).get_json()["saved"] == 1
    assert client.post("/anki", json=payload_b).get_json()["saved"] == 1

    page = client.get("/?deck=Kaishi 1.5k")
    assert page.status_code == 200
    html = page.data.decode()
    assert html.index("a@example.com") < html.index("b@example.com")
    assert "60.0%" in html


def test_ingest_requires_identifier(tmp_path: Path):
    """Test plan:
    1. POST a payload missing identifier.
    2. Expect HTTP 400 with a clear error (add-on misconfig).
    """
    resp = _client(tmp_path).post("/anki", json={"decks": [{"name": "X", "cards": 1}]})
    assert resp.status_code == 400
    assert "identifier" in resp.get_json()["error"]


def test_ingest_rejects_invalid_json(tmp_path: Path):
    """Test plan:
    1. POST non-JSON to /anki.
    2. Expect HTTP 400 invalid json.
    """
    resp = _client(tmp_path).post("/anki", data=b"nope", content_type="application/json")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid json"
