"""Anki Sync Webhook — POST deck progress after collection sync."""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import UTC, datetime
from typing import Any

import requests
from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo, tooltip


class SyncWebhook:
    name = "Anki Sync Webhook"

    def __init__(self, module: str) -> None:
        self.module = module  # add-on package name for getConfig()

    def cfg(self) -> dict[str, Any]:
        return mw.addonManager.getConfig(self.module) or {}

    def build_payload(self) -> dict[str, Any]:
        col = mw.col
        if col is None:
            raise RuntimeError("Collection is not open")

        cfg = self.cfg()
        include_subdecks = bool(cfg.get("include_subdecks", True))

        # Walk full tree for ids/names; include_subdecks only controls what we emit.
        entries: list[dict[str, Any]] = []
        children_of: dict[int, list[int]] = {}

        def walk(n: Any, depth: int, parent: str) -> int | None:
            part = str(getattr(n, "name", "") or "")
            if depth == 0 and not getattr(n, "deck_id", 0):
                path = ""
                did: int | None = None
            else:
                path = f"{parent}::{part}" if parent else part
                did = int(getattr(n, "deck_id", 0) or 0)
                entries.append({"deck_id": did, "name": path, "depth": depth})
                children_of[did] = []

            for child in getattr(n, "children", []) or []:
                child_id = walk(child, depth + 1, path)
                if did is not None and child_id is not None:
                    children_of[did].append(child_id)
            return did

        walk(col.sched.deck_due_tree(), 0, "")

        # Optional allowlist: empty [] = all; "Japanese" also matches "Japanese::Kanji".
        raw = cfg.get("decks")
        allowlist: list[str] | None = None
        if isinstance(raw, list):
            allowlist = [str(x).strip() for x in raw if str(x).strip()] or None
        elif raw is not None:
            raise ValueError("config key 'decks' must be a list of deck name strings")
        if allowlist is not None:
            entries = [
                d
                for d in entries
                if any(d["name"] == name or d["name"].startswith(name + "::") for name in allowlist)
            ]
        elif not include_subdecks:
            entries = [d for d in entries if int(d["depth"]) == 1]

        # Per-deck card progress (Anki stats: new / learning / young / mature).
        # young = review ivl < 21d, mature = review ivl >= 21d; suspended counted apart.
        by_did: dict[int, dict[str, int]] = {}
        for row in col.db.all(
            """
            select did,
                   count(*),
                   sum(queue = -100),
                   sum(queue >= 0 and type = 0),
                   sum(queue >= 0 and type in (1, 3)),
                   sum(queue >= 0 and type = 2 and ivl < 21),
                   sum(queue >= 0 and type = 2 and ivl >= 21)
            from cards
            group by did
            """
        ):
            by_did[int(row[0])] = {
                "cards": int(row[1] or 0),
                "suspended": int(row[2] or 0),
                "new": int(row[3] or 0),
                "learning": int(row[4] or 0),
                "young": int(row[5] or 0),
                "mature": int(row[6] or 0),
            }

        def rollup(did: int) -> dict[str, int]:
            ids = [did]
            stack = list(children_of.get(did, []))
            while stack:
                cur = stack.pop()
                ids.append(cur)
                stack.extend(children_of.get(cur, []))
            out = {"cards": 0, "suspended": 0, "new": 0, "learning": 0, "young": 0, "mature": 0}
            for i in ids:
                part = by_did.get(i)
                if not part:
                    continue
                for key in out:
                    out[key] += part[key]
            return out

        decks: list[dict[str, Any]] = []
        for entry in entries:
            stats = rollup(int(entry["deck_id"]))
            cards = stats["cards"]
            seen = stats["learning"] + stats["young"] + stats["mature"]
            decks.append(
                {
                    **entry,
                    **stats,
                    "seen_pct": round(100.0 * seen / cards, 1) if cards else 0.0,
                }
            )

        return {
            "schema_version": 1,
            "source": "anki-sync-webhook",
            "event": "sync_did_finish",
            "sent_at": datetime.now(UTC).isoformat(),
            "identifier": str(cfg.get("identifier") or "").strip(),
            "decks": decks,
        }

    def deliver(self, payload: dict[str, Any], *, manual: bool = False) -> None:
        cfg = self.cfg()
        if not cfg.get("enabled", True):
            print(f"[{self.name}] disabled; skipping")
            return

        url = (cfg.get("endpoint_url") or "").strip()
        if not url:
            msg = "endpoint_url is empty — set it in Tools → Add-ons → Config"
            print(f"[{self.name}] {msg}")
            if manual or cfg.get("notify_on_error", True):
                tooltip(f"{self.name}: {msg}")
            return

        method = str(cfg.get("method") or "POST").upper()
        if method not in {"POST", "PUT"}:
            method = "POST"

        headers = {"User-Agent": "anki-sync-webhook/0.1"}
        for key, value in (cfg.get("headers") or {}).items():
            text = str(value or "").strip()
            if text:
                headers[str(key)] = text

        started = time.monotonic()
        try:
            resp = requests.request(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=float(cfg.get("timeout_seconds") or 10),
            )
            ms = int((time.monotonic() - started) * 1000)
            print(f"[{self.name}] {method} {url} -> {resp.status_code} in {ms}ms")
            if resp.ok:
                if manual or cfg.get("notify_on_success", False):
                    tooltip(f"{self.name}: sent ({resp.status_code})")
            elif manual or cfg.get("notify_on_error", True):
                tooltip(f"{self.name}: HTTP {resp.status_code}")
        except requests.RequestException as exc:
            print(f"[{self.name}] delivery failed: {exc}\n{traceback.format_exc()}")
            if manual or cfg.get("notify_on_error", True):
                tooltip(f"{self.name}: {exc}")

    def _send(self, *, manual: bool) -> None:
        try:
            payload = self.build_payload()
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.name}] build failed: {exc}\n{traceback.format_exc()}")
            if manual:
                showInfo(f"{self.name}\n\nFailed to build payload:\n{exc}")
            elif self.cfg().get("notify_on_error", True):
                tooltip(f"{self.name}: build failed: {exc}")
            return
        threading.Thread(
            target=self.deliver,
            args=(payload,),
            kwargs={"manual": manual},
            daemon=True,
            name="anki-sync-webhook",
        ).start()
        if manual:
            tooltip(f"{self.name}: sending…")

    def on_sync_did_finish(self) -> None:
        self._send(manual=False)

    def send_now(self) -> None:
        self._send(manual=True)

    def preview_payload(self) -> None:
        try:
            showInfo(json.dumps(self.build_payload(), indent=2)[:4000])
        except Exception as exc:  # noqa: BLE001
            showInfo(f"{self.name}\n\nFailed to build payload:\n{exc}")

    def setup_menu(self) -> None:
        menu = mw.form.menuTools.addMenu(self.name)
        assert menu is not None
        send = QAction("Send progress now", mw)
        send.triggered.connect(self.send_now)
        menu.addAction(send)
        preview = QAction("Preview payload…", mw)
        preview.triggered.connect(self.preview_payload)
        menu.addAction(preview)

    def setup(self) -> None:
        gui_hooks.sync_did_finish.append(self.on_sync_did_finish)
        gui_hooks.main_window_did_init.append(self.setup_menu)
