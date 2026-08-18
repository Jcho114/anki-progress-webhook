"""Anki loads this file at startup; logic is in SyncWebhook."""

from __future__ import annotations

import sys
from pathlib import Path

# Bundled third-party libs (requests, …) ship in vendor/ for Anki's Python.
_vendor = Path(__file__).resolve().parent / "vendor"
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

from .webhook import SyncWebhook

addon = SyncWebhook(module=__name__)
addon.setup()
