#!/usr/bin/env python3
"""Build anki-sync-webhook.ankiaddon (zip of addon files, no parent folder)."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon"
ROOT_FILES = ("__init__.py", "webhook.py", "config.json", "config.md", "manifest.json")


def main() -> int:
    vendor = ADDON / "vendor"
    if not (vendor / "requests").is_dir():
        raise SystemExit(
            "missing addon/vendor/requests — run:\n"
            "  uv pip install 'requests>=2.32' -t addon/vendor"
        )

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "anki-sync-webhook.ankiaddon"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ROOT_FILES:
            path = ADDON / name
            if not path.is_file():
                raise SystemExit(f"missing {path}")
            zf.write(path, arcname=name)

        for path in vendor.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            zf.write(path, arcname=str(path.relative_to(ADDON)))

    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
