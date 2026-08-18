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

    @staticmethod
    def normalize_allowlist(raw: Any) -> list[str] | None:
        """None = all decks; non-empty list = allowlist (parent matches children)."""
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise ValueError("'decks' must be a list of deck name strings")
        names = [str(x).strip() for x in raw if str(x).strip()]
        return names or None

    @staticmethod
    def filter_decks(
        decks: list[dict[str, Any]], allowlist: list[str] | None
    ) -> list[dict[str, Any]]:
        if allowlist is None:
            return decks
        return [
            d
            for d in decks
            if any(d["name"] == name or d["name"].startswith(name + "::") for name in allowlist)
        ]

    def collect_deck_progress(self) -> list[dict[str, Any]]:
        """All deck progress rows (optionally top-level only via include_subdecks)."""
        col = mw.col
        if col is None:
            raise RuntimeError("Collection is not open")

        cfg = self.cfg()
        include_subdecks = bool(cfg.get("include_subdecks", True))

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
        if not include_subdecks:
            entries = [d for d in entries if int(d["depth"]) == 1]

        # Per-deck card progress (Anki stats: new / learning / young / mature).
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
        return decks

    def build_payload(self, *, decks_allowlist: Any = None) -> dict[str, Any]:
        """Build progress JSON. decks_allowlist is endpoint-scoped (None = all decks)."""
        cfg = self.cfg()
        allowlist = self.normalize_allowlist(decks_allowlist)
        decks = self.filter_decks(self.collect_deck_progress(), allowlist)
        return {
            "schema_version": 1,
            "source": "anki-sync-webhook",
            "event": "sync_did_finish",
            "sent_at": datetime.now(UTC).isoformat(),
            "identifier": str(cfg.get("identifier") or "").strip(),
            "decks": decks,
        }

    def endpoints(self) -> list[dict[str, Any]]:
        """Resolved delivery targets. `endpoints` wins; else legacy `endpoint_url`."""
        cfg = self.cfg()
        global_headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
        global_method = str(cfg.get("method") or "POST").upper()
        global_timeout = float(cfg.get("timeout_seconds") or 10)

        raw = cfg.get("endpoints")
        if isinstance(raw, list) and raw:
            out: list[dict[str, Any]] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                method = str(item.get("method") or global_method).upper()
                if method not in {"POST", "PUT"}:
                    method = "POST"
                if isinstance(item.get("headers"), dict):
                    headers = item["headers"]
                else:
                    headers = global_headers
                timeout = float(item.get("timeout_seconds") or global_timeout)
                out.append(
                    {
                        "url": url,
                        "method": method,
                        "headers": headers,
                        "decks": item.get("decks"),
                        "timeout_seconds": timeout,
                    }
                )
            return out

        url = str(cfg.get("endpoint_url") or "").strip()
        if not url:
            return []
        method = global_method if global_method in {"POST", "PUT"} else "POST"
        return [
            {
                "url": url,
                "method": method,
                "headers": global_headers,
                "decks": None,
                "timeout_seconds": global_timeout,
            }
        ]

    def deliver_one(
        self,
        payload: dict[str, Any],
        endpoint: dict[str, Any],
        *,
        manual: bool = False,
    ) -> None:
        cfg = self.cfg()
        url = endpoint["url"]
        method = endpoint["method"]
        headers = {"User-Agent": "anki-sync-webhook/0.1"}
        for key, value in (endpoint.get("headers") or {}).items():
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
                timeout=float(endpoint.get("timeout_seconds") or 10),
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

    def deliver(self, payload: dict[str, Any], *, manual: bool = False) -> None:
        """Back-compat: send one payload to every configured endpoint (same decks)."""
        cfg = self.cfg()
        if not cfg.get("enabled", True):
            print(f"[{self.name}] disabled; skipping")
            return
        targets = self.endpoints()
        if not targets:
            msg = "no endpoints — set endpoints[] or endpoint_url in Config"
            print(f"[{self.name}] {msg}")
            if manual or cfg.get("notify_on_error", True):
                tooltip(f"{self.name}: {msg}")
            return
        for ep in targets:
            self.deliver_one(payload, ep, manual=manual)

    def _send(self, *, manual: bool = False) -> None:
        cfg = self.cfg()
        if not cfg.get("enabled", True):
            print(f"[{self.name}] disabled; skipping")
            return

        targets = self.endpoints()
        if not targets:
            msg = "no endpoints — set endpoints[] or endpoint_url in Config"
            print(f"[{self.name}] {msg}")
            if manual or cfg.get("notify_on_error", True):
                tooltip(f"{self.name}: {msg}")
            return

        try:
            all_decks = self.collect_deck_progress()
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.name}] build failed: {exc}\n{traceback.format_exc()}")
            if manual:
                showInfo(f"{self.name}\n\nFailed to build payload:\n{exc}")
            elif cfg.get("notify_on_error", True):
                tooltip(f"{self.name}: build failed: {exc}")
            return

        def worker() -> None:
            for ep in targets:
                allowlist = self.normalize_allowlist(ep.get("decks"))
                payload = {
                    "schema_version": 1,
                    "source": "anki-sync-webhook",
                    "event": "sync_did_finish",
                    "sent_at": datetime.now(UTC).isoformat(),
                    "identifier": str(cfg.get("identifier") or "").strip(),
                    "decks": self.filter_decks(all_decks, allowlist),
                }
                self.deliver_one(payload, ep, manual=manual)

        threading.Thread(target=worker, daemon=True, name="anki-sync-webhook").start()
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
