#!/usr/bin/env python3
"""Bridge between the updater CLI and Shotdeck's file-based update prompt UI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("/etc/shotdeck/updater.json")
UPDATER_BIN = Path("/opt/shotdeck/updater-venv/bin/shotdeck-updater")
STATUS_PATH = Path("/opt/shotdeck/update-status.json")
RESPONSE_PATH = Path("/opt/shotdeck/update-response.json")


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def clear_prompt_files() -> None:
    _remove_if_exists(STATUS_PATH)
    _remove_if_exists(RESPONSE_PATH)


def _run_updater(config_path: Path, command: str) -> dict[str, object]:
    completed = subprocess.run(
        (str(UPDATER_BIN), "--config", str(config_path), command),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise SystemExit(stderr or f"shotdeck-updater {command} failed with exit {completed.returncode}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"shotdeck-updater {command} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"shotdeck-updater {command} returned an unexpected JSON value")
    return payload


def _status_payload_from_check(check_payload: dict[str, object]) -> dict[str, object] | None:
    if not bool(check_payload.get("applicable")):
        return None
    version = str(check_payload.get("manifest_version") or "").strip()
    channel = str(check_payload.get("channel") or "stable").strip().lower()
    if not version:
        return None
    key = f"{channel}:{version}"
    return {
        "update_available": True,
        "target_version": version,
        "channel": channel,
        "summary": f"Update {version} available. Install now?",
        "key": key,
    }


def command_check(config_path: Path) -> int:
    check_payload = _run_updater(config_path, "check")
    status_payload = _status_payload_from_check(check_payload)
    if status_payload is None:
        clear_prompt_files()
        return 0
    prior_status = _load_json(STATUS_PATH)
    _write_json(STATUS_PATH, status_payload)
    status_key = str(status_payload["key"])
    if prior_status is not None and str(prior_status.get("key") or "") != status_key:
        _remove_if_exists(RESPONSE_PATH)
    return 0


def command_process_response(config_path: Path) -> int:
    status_payload = _load_json(STATUS_PATH)
    response_payload = _load_json(RESPONSE_PATH)
    if not status_payload or not response_payload:
        return 0

    status_key = str(status_payload.get("key") or "").strip()
    response_key = str(response_payload.get("key") or "").strip()
    if not status_key or response_key != status_key:
        _remove_if_exists(RESPONSE_PATH)
        return 0

    action = str(response_payload.get("action") or "").strip().lower()
    if action == "skip":
        clear_prompt_files()
        return 0
    if action != "install":
        _remove_if_exists(RESPONSE_PATH)
        return 0

    _remove_if_exists(RESPONSE_PATH)
    _run_updater(config_path, "apply")
    _remove_if_exists(STATUS_PATH)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("command", choices=("check", "process-response", "clear"))
    args = parser.parse_args(argv)

    if args.command == "clear":
        clear_prompt_files()
        return 0
    if args.command == "check":
        return command_check(args.config)
    return command_process_response(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
