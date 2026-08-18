#!/usr/bin/env bash
# Sync addon/ into the local Anki addons21 folder (copy — works with Windows Anki + WSL).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/addon"
NAME="${ADDON_FOLDER_NAME:-anki_webhook}"

candidates=(
  "${ANKI_ADDONS:-}"
  "$HOME/.local/share/Anki2/addons21"
  "$HOME/Library/Application Support/Anki2/addons21"
  "/mnt/c/Users/${WIN_USER:-$USER}/AppData/Roaming/Anki2/addons21"
  "/mnt/c/Users/josep/AppData/Roaming/Anki2/addons21"
)

DEST_PARENT=""
for c in "${candidates[@]}"; do
  [[ -z "$c" ]] && continue
  if [[ -d "$c" ]]; then
    DEST_PARENT="$c"
    break
  fi
done

if [[ -z "$DEST_PARENT" ]]; then
  echo "Could not find addons21. Set ANKI_ADDONS to that folder, e.g.:" >&2
  echo "  export ANKI_ADDONS=/mnt/c/Users/<you>/AppData/Roaming/Anki2/addons21" >&2
  exit 1
fi

DEST="$DEST_PARENT/$NAME"
mkdir -p "$DEST"
# Prefer rsync if present; else cp -a
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$SRC/" "$DEST/"
else
  rm -rf "$DEST"
  mkdir -p "$DEST"
  cp -a "$SRC"/. "$DEST"/
  find "$DEST" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
fi

echo "Installed (copied) to: $DEST"
echo "Restart Anki (or disable/enable the add-on) to reload."
