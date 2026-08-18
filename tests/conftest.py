"""Shared fixtures. Anki APIs are mocked so addon/webhook.py can import offline."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon"
VENDOR = ADDON / "vendor"


@pytest.fixture(scope="session")
def webhook_mod():
    """Load addon/webhook.py with fake aqt + vendored requests on sys.path."""
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))

    aqt = MagicMock()
    sys.modules["aqt"] = aqt
    sys.modules["aqt.qt"] = MagicMock()
    sys.modules["aqt.utils"] = MagicMock()

    spec = importlib.util.spec_from_file_location("anki_sync_webhook_mod", ADDON / "webhook.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def deck_tree():
    """Small due-tree: root → Japanese → Kanji, and Spanish."""

    def n(name: str, deck_id: int, children=None, new=0, learn=0, review=0):
        return SimpleNamespace(
            name=name,
            deck_id=deck_id,
            children=children or [],
            new_count=new,
            learn_count=learn,
            review_count=review,
        )

    return n(
        "",
        0,
        children=[
            n("Japanese", 1, children=[n("Kanji", 2, new=1, review=3)], new=2, review=4),
            n("Spanish", 3, new=5),
        ],
    )
