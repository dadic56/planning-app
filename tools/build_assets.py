"""Placeholder tool to build frontend assets (empty for prototype)."""
import os

def build():
    print('No frontend configured. This is a placeholder.')

if __name__ == '__main__':
    build()
#!/usr/bin/env python3
"""Génère des copies hashées des assets statiques et un manifest JSON."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
DIST_DIR = STATIC_DIR / "dist"
MANIFEST_PATH = DIST_DIR / "asset-manifest.json"

SOURCES = ["app.js", "base.js", "snapshots.js"]


def compute_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def build():
    DIST_DIR.mkdir(exist_ok=True)
    manifest = {}
    for name in SOURCES:
        src = STATIC_DIR / name
        if not src.exists():
            raise FileNotFoundError(f"Asset introuvable: {src}")
        file_hash = compute_hash(src)
        stem, ext = name.rsplit(".", 1)
        target_name = f"{stem}.{file_hash}.{ext}"
        target = DIST_DIR / target_name
        shutil.copy2(src, target)
        manifest[name] = f"dist/{target_name}"
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Manifest généré:", MANIFEST_PATH)


if __name__ == "__main__":
    build()
