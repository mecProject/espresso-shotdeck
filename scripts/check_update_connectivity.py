#!/usr/bin/env python3
"""Return success when the updater has enough network connectivity to run.

The check is intentionally lightweight and dependency-free:

- read `/etc/shotdeck/updater.json`
- collect `manifest_url` and optional `next_manifest_url`
- issue a short HEAD request to each URL until one succeeds

This allows the systemd service to skip unattended runs when the device is
offline or the configured update host is unavailable.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


def _candidate_urls(config_path: Path) -> list[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    urls: list[str] = []
    for key in ("manifest_url", "next_manifest_url"):
        value = str(payload.get(key, "")).strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def _url_is_reachable(url: str, *, timeout: int = 8) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "shotdeck-updater/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    config_path = Path(argv[0]) if argv else Path("/etc/shotdeck/updater.json")
    if not config_path.exists():
        return 1
    for url in _candidate_urls(config_path):
        if _url_is_reachable(url):
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
