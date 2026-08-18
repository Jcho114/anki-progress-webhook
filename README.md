# Anki Sync Webhook (PoC)

Anki add-on that fires after **collection sync** and POSTs **deck progress** JSON to one or more endpoints (optional shared leaderboard server included).

## Scope

**In scope:** `sync_did_finish` → deck progress payload → HTTP POST/PUT (per-endpoint deck filters).  
**Out of scope (for now):** other Anki triggers, non-progress payloads, generic plugin/ops framework.

## Idea

Hook `gui_hooks.sync_did_finish` → snapshot deck progress → POST to configured endpoints. The sample tracker stores per-person stats in SQLite and renders a shared board.

Also exposes **Tools → Anki Sync Webhook → Send progress now** so you can test without syncing.

## User journey

1. **Setup (once)** — Install the add-on, set `identifier` + `endpoints`, start the tracker. Restart Anki if needed.
2. **Everyday** — Study as usual, then Sync. Progress is upserted for your identifier + deck(s).
3. **If something’s wrong** — Failures toast by default. Use **Preview payload…** / **Send progress now**.
4. **On the board** — Open the tracker homepage to see a multiplayer leaderboard by `seen_pct`.

## Payload shape

```json
{
  "schema_version": 1,
  "source": "anki-sync-webhook",
  "event": "sync_did_finish",
  "sent_at": "2026-08-18T03:00:00+00:00",
  "identifier": "you@example.com",
  "decks": [
    {
      "deck_id": 1,
      "name": "Kaishi 1.5k",
      "depth": 1,
      "cards": 1500,
      "new": 1200,
      "learning": 15,
      "young": 180,
      "mature": 105,
      "suspended": 0,
      "seen_pct": 20.0
    }
  ]
}
```

Deck fields use Anki stats meanings: **young** = review interval &lt; 21d, **mature** ≥ 21d. `seen_pct` is `(learning + young + mature) / cards`. Parent decks roll up their subdecks.

## Quick start

### 1. Run the progress tracker

```bash
uv run anki-webhook-tracker
# or: uv run server/tracker.py
```

- Board: `http://127.0.0.1:8787/`
- Webhook (add-on `endpoint_url`): `http://127.0.0.1:8787/anki`
- SQLite DB: `server/data/progress.db`

### 2. Install the add-on

**Windows Anki + WSL (this machine):** Anki data lives under
`C:\Users\<you>\AppData\Roaming\Anki2\addons21`, not `~/.local/share/...`.
A `ln -s` from WSL into that folder also fails for Anki — Windows won’t follow a
symlink into the Linux filesystem. Use a **copy** or **Install from file** instead.

```bash
# copy addon/ → Windows addons21/anki_webhook (auto-detects common paths)
bash scripts/install-dev.sh
# or point it yourself:
# ANKI_ADDONS="/mnt/c/Users/josep/AppData/Roaming/Anki2/addons21" bash scripts/install-dev.sh
```

**Linux-native Anki** (only if Anki itself runs in Linux):

```bash
ADDONS="$HOME/.local/share/Anki2/addons21"
mkdir -p "$ADDONS"
ln -sfn "$(pwd)/addon" "$ADDONS/anki_webhook"
```

**Or package and import** (works everywhere):

```bash
uv run python scripts/package.py
# Anki → Tools → Add-ons → Install from file → anki-sync-webhook.ankiaddon
```

See the [Anki add-ons manual](https://docs.ankiweb.net/addons.html) for managing installed add-ons, and the [add-on writing guide](https://addon-docs.ankiweb.net/) for development details.

### 3. Configure

Tools → Add-ons → **Anki Sync Webhook** → Config:

```json
{
  "enabled": true,
  "identifier": "you@example.com",
  "endpoints": [
    {
      "url": "http://127.0.0.1:8787/anki",
      "decks": ["Kaishi 1.5k"]
    }
  ]
}
```

`decks` is endpoint-scoped (omit or `[]` = all decks for that URL). Legacy `endpoint_url` still works and sends all decks.

The add-on POSTs with **requests**, vendored under `addon/vendor/` so Anki does not need a separate pip install. Refresh with:

```bash
uv pip install 'requests>=2.32' -t addon/vendor
```

Restart Anki after first install / symlink.

### 4. Trigger

- Sync normally, or
- Tools → Anki Sync Webhook → **Send progress now** / **Preview payload…**

## Layout

```
addon/              # Anki add-on package
server/tracker.py   # Flask + SQLite progress board
server/templates/   # Jinja pages
scripts/            # package / install helpers
```

## Lint / types / tests

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
```

`ty` covers `server/`, `scripts/`, and `tests/` (the add-on talks to Anki APIs that aren’t installed here).

## Notes / next steps

- Delivery is fire-and-forget; failures only toast (configurable).
- Media sync may still be running when `sync_did_finish` fires — this still reports deck progress from the local collection.
- Natural follow-ups within this scope: webhook auth, progress history/sparklines, hosted deploy.
