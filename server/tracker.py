#!/usr/bin/env python3
"""Flask progress tracker for Anki sync webhooks.

  uv run anki-webhook-tracker
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request

SERVER_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SERVER_DIR / "data" / "progress.db"


class ProgressStore:
    """SQLite store: latest progress per (identifier, deck_name)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists progress (
                    identifier text not null,
                    deck_name text not null,
                    deck_id integer,
                    depth integer,
                    cards integer not null default 0,
                    new integer not null default 0,
                    learning integer not null default 0,
                    young integer not null default 0,
                    mature integer not null default 0,
                    suspended integer not null default 0,
                    seen_pct real not null default 0,
                    sent_at text,
                    updated_at text not null,
                    primary key (identifier, deck_name)
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_progress_deck_seen
                on progress(deck_name, seen_pct desc)
                """
            )

    def upsert_payload(self, payload: dict[str, Any]) -> int:
        identifier = str(payload.get("identifier") or "").strip()
        if not identifier:
            raise ValueError("identifier is required")

        decks = payload.get("decks")
        if not isinstance(decks, list) or not decks:
            raise ValueError("decks must be a non-empty list")

        sent_at = str(payload.get("sent_at") or "")
        updated_at = datetime.now(UTC).isoformat()
        saved = 0

        with self.connect() as conn:
            for deck in decks:
                if not isinstance(deck, dict):
                    continue
                name = str(deck.get("name") or "").strip()
                if not name:
                    continue
                conn.execute(
                    """
                    insert into progress (
                        identifier, deck_name, deck_id, depth,
                        cards, new, learning, young, mature, suspended, seen_pct,
                        sent_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(identifier, deck_name) do update set
                        deck_id=excluded.deck_id,
                        depth=excluded.depth,
                        cards=excluded.cards,
                        new=excluded.new,
                        learning=excluded.learning,
                        young=excluded.young,
                        mature=excluded.mature,
                        suspended=excluded.suspended,
                        seen_pct=excluded.seen_pct,
                        sent_at=excluded.sent_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        identifier,
                        name,
                        int(deck["deck_id"]) if deck.get("deck_id") is not None else None,
                        int(deck["depth"]) if deck.get("depth") is not None else None,
                        int(deck.get("cards") or 0),
                        int(deck.get("new") or 0),
                        int(deck.get("learning") or 0),
                        int(deck.get("young") or 0),
                        int(deck.get("mature") or 0),
                        int(deck.get("suspended") or 0),
                        float(deck.get("seen_pct") or 0),
                        sent_at or None,
                        updated_at,
                    ),
                )
                saved += 1
        return saved

    def deck_names(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "select distinct deck_name from progress order by deck_name collate nocase"
            ).fetchall()
        return [str(r["deck_name"]) for r in rows]

    def leaderboard(self, deck_name: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if deck_name:
                rows = conn.execute(
                    """
                    select * from progress
                    where deck_name = ?
                    order by seen_pct desc, mature desc, identifier collate nocase
                    """,
                    (deck_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select * from progress
                    order by deck_name collate nocase, seen_pct desc, identifier collate nocase
                    """
                ).fetchall()
        return [dict(r) for r in rows]


class ProgressServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8787,
        webhook_path: str = "/anki",
        db_path: Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.webhook_path = webhook_path.rstrip("/") or "/"
        self.store = ProgressStore(db_path or DEFAULT_DB)
        self.app = Flask(
            __name__,
            template_folder=str(SERVER_DIR / "templates"),
            static_folder=str(SERVER_DIR / "static"),
        )
        self._register_routes()

    def _register_routes(self) -> None:
        store = self.store
        path = self.webhook_path

        @self.app.get("/")
        def index():
            decks = store.deck_names()
            selected = request.args.get("deck") or (decks[0] if decks else None)
            rows = store.leaderboard(selected) if selected else []
            return render_template(
                "index.html",
                decks=decks,
                selected=selected,
                rows=rows,
                webhook_url=f"http://{self.host}:{self.port}{path}",
            )

        @self.app.get("/deck/<path:deck_name>")
        def deck_page(deck_name: str):
            name = unquote(deck_name)
            rows = store.leaderboard(name)
            return render_template(
                "index.html",
                decks=store.deck_names(),
                selected=name,
                rows=rows,
                webhook_url=f"http://{self.host}:{self.port}{path}",
            )

        @self.app.get(path)
        def webhook_info() -> tuple[Any, int]:
            return jsonify(
                {
                    "ok": True,
                    "hint": "POST Anki progress JSON here",
                    "board": f"http://{self.host}:{self.port}/",
                }
            ), 200

        @self.app.post(path)
        @self.app.put(path)
        def ingest() -> tuple[Any, int]:
            raw = request.get_data(cache=True) or b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(f"invalid JSON ({len(raw)} bytes): {exc}")
                return jsonify({"ok": False, "error": "invalid json"}), 400

            if not isinstance(payload, dict):
                return jsonify({"ok": False, "error": "json object required"}), 400

            try:
                saved = store.upsert_payload(payload)
            except ValueError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

            identifier = payload.get("identifier")
            print(f"saved {saved} deck(s) for {identifier!r}")
            return jsonify({"ok": True, "saved": saved, "identifier": identifier}), 200

    def run(self) -> int:
        print(f"Progress board: http://{self.host}:{self.port}/")
        print(f"Webhook:        http://{self.host}:{self.port}{self.webhook_path}")
        print(f"Database:       {self.store.db_path}")
        try:
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            print("\nbye")
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Anki multiplayer progress tracker")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--path", default="/anki", help="Webhook path")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    args = p.parse_args(argv)
    return ProgressServer(
        host=args.host,
        port=args.port,
        webhook_path=args.path,
        db_path=args.db,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
