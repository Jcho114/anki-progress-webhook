"""SyncWebhook unit tests (Anki mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_build_payload_deck_progress_and_allowlist(webhook_mod, deck_tree):
    """Test plan:
    1. Stub deck tree: Japanese→Kanji, Spanish.
    2. Stub cards group-by-did: Kanji has progress, Spanish ignored by allowlist.
    3. Allowlist ["Japanese"] → both Japanese (rolled up) and Japanese::Kanji.
    4. Japanese.seen_pct uses learning+young+mature over cards; schema_version == 1.
    """
    mw = webhook_mod.mw
    mw.col = MagicMock()
    mw.col.sched.deck_due_tree.return_value = deck_tree
    # did, cards, suspended, new, learning, young, mature
    mw.col.db.all.return_value = [
        (2, 100, 0, 40, 10, 30, 20),  # Kanji
        (3, 50, 0, 50, 0, 0, 0),  # Spanish
    ]
    mw.addonManager.getConfig.return_value = {
        "identifier": "learner@example.com",
        "include_subdecks": True,
    }

    wh = webhook_mod.SyncWebhook(module="anki_webhook")
    payload = wh.build_payload(decks_allowlist=["Japanese"])

    assert payload["schema_version"] == 1
    assert payload["identifier"] == "learner@example.com"
    assert [d["name"] for d in payload["decks"]] == ["Japanese", "Japanese::Kanji"]

    parent, child = payload["decks"]
    assert parent["cards"] == 100  # only Kanji has cards; parent rolls up children
    assert parent["new"] == 40
    assert parent["learning"] == 10
    assert parent["young"] == 30
    assert parent["mature"] == 20
    assert parent["seen_pct"] == 60.0  # (10+30+20)/100

    assert child["deck_id"] == 2
    assert child["seen_pct"] == 60.0
    assert "learn" not in child
    assert "review" not in child


def test_deliver_posts_json_with_requests(webhook_mod):
    """Test plan:
    1. Config enabled + legacy endpoint_url + Authorization header.
    2. Mock requests.request to return ok=True / 200.
    3. deliver({...}) → one POST with json=payload and Authorization header set.
    """
    mw = webhook_mod.mw
    mw.addonManager.getConfig.return_value = {
        "enabled": True,
        "endpoint_url": "http://example.test/anki",
        "method": "POST",
        "timeout_seconds": 5,
        "headers": {"Authorization": "Bearer secret"},
        "notify_on_success": False,
        "notify_on_error": False,
    }
    wh = webhook_mod.SyncWebhook(module="anki_webhook")
    payload = {"schema_version": 1, "decks": []}

    fake = MagicMock()
    fake.ok = True
    fake.status_code = 200
    with patch.object(webhook_mod.requests, "request", return_value=fake) as req:
        wh.deliver(payload, manual=False)

    req.assert_called_once()
    args, kwargs = req.call_args
    assert args[0] == "POST"
    assert args[1] == "http://example.test/anki"
    assert kwargs["json"] == payload
    assert kwargs["headers"]["Authorization"] == "Bearer secret"


def test_endpoints_list_with_per_endpoint_decks(webhook_mod, deck_tree):
    """Test plan:
    1. Config endpoints[] with two URLs and different decks allowlists.
    2. endpoints() resolves both; send worker posts filtered payloads.
    3. First URL gets only Japanese*; second gets only Spanish.
    """
    mw = webhook_mod.mw
    mw.col = MagicMock()
    mw.col.sched.deck_due_tree.return_value = deck_tree
    mw.col.db.all.return_value = [
        (2, 100, 0, 40, 10, 30, 20),
        (3, 50, 0, 50, 0, 0, 0),
    ]
    mw.addonManager.getConfig.return_value = {
        "enabled": True,
        "identifier": "learner@example.com",
        "include_subdecks": True,
        "notify_on_success": False,
        "notify_on_error": False,
        "endpoints": [
            {"url": "http://a.test/anki", "decks": ["Japanese"]},
            {"url": "http://b.test/anki", "decks": ["Spanish"]},
        ],
    }
    wh = webhook_mod.SyncWebhook(module="anki_webhook")
    eps = wh.endpoints()
    assert [e["url"] for e in eps] == ["http://a.test/anki", "http://b.test/anki"]

    fake = MagicMock()
    fake.ok = True
    fake.status_code = 200
    with patch.object(webhook_mod.requests, "request", return_value=fake) as req:
        all_decks = wh.collect_deck_progress()
        for ep in eps:
            allowlist = wh.normalize_allowlist(ep.get("decks"))
            payload = {
                "schema_version": 1,
                "identifier": "learner@example.com",
                "decks": wh.filter_decks(all_decks, allowlist),
            }
            wh.deliver_one(payload, ep, manual=False)

    assert req.call_count == 2
    first_decks = req.call_args_list[0].kwargs["json"]["decks"]
    second_decks = req.call_args_list[1].kwargs["json"]["decks"]
    assert [d["name"] for d in first_decks] == ["Japanese", "Japanese::Kanji"]
    assert [d["name"] for d in second_decks] == ["Spanish"]


def test_deliver_skips_when_disabled(webhook_mod):
    """Test plan:
    1. Config enabled=false.
    2. deliver(...) must not call requests.request (no network when toggled off).
    """
    mw = webhook_mod.mw
    mw.addonManager.getConfig.return_value = {"enabled": False}
    wh = webhook_mod.SyncWebhook(module="anki_webhook")

    with patch.object(webhook_mod.requests, "request") as req:
        wh.deliver({"decks": []}, manual=False)
    req.assert_not_called()


def test_build_payload_requires_open_collection(webhook_mod):
    """Test plan:
    1. mw.col is None (Anki has no collection open).
    2. build_payload() raises RuntimeError — Preview/Send should surface this.
    """
    webhook_mod.mw.col = None
    wh = webhook_mod.SyncWebhook(module="anki_webhook")
    with pytest.raises(RuntimeError, match="Collection is not open"):
        wh.build_payload()
