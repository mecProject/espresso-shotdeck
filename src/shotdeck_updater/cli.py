"""Command line interface for the runtime updater."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import UpdaterClient
from .config import DEFAULT_CONFIG_PATH, UpdaterConfig
from .identity import collect_identity
from .locking import exclusive_lock
from .logging_utils import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shotdeck-updater")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)

    show_identity = subparsers.add_parser("show-identity", help="Print the current device identity")
    show_identity.add_argument("--include-raw", action="store_true")
    show_identity.add_argument("--enrollment", action="store_true")

    subparsers.add_parser("check", help="Fetch and evaluate the latest manifest")
    subparsers.add_parser("download", help="Download the selected update artifact")
    subparsers.add_parser("apply", help="Download and apply the selected update")
    subparsers.add_parser("rollback", help="Roll back to the previous installed release")
    subparsers.add_parser("unattended", help="Run the configured unattended policy")

    return parser


def _load_config(path: Path, *, command: str) -> UpdaterConfig:
    allow_missing = command == "show-identity"
    config = UpdaterConfig.from_file(path, allow_missing=allow_missing)
    if command == "show-identity":
        return config
    config.validate()
    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _load_config(args.config, command=args.command)
    logger = configure_logging(config.log_file, verbose=args.verbose)

    if args.command == "show-identity":
        identity = collect_identity(config.identity_policy)
        if args.enrollment:
            payload = identity.enrollment_record(product=config.product, channel=config.channel)
        else:
            payload = identity.to_dict(include_raw=args.include_raw)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    client = UpdaterClient(config, logger=logger)
    with exclusive_lock(config.lock_path):
        if args.command == "check":
            print(json.dumps(client.check().to_dict(), indent=2, sort_keys=True))
            return 0
        if args.command == "download":
            check_result = client.check()
            artifact = client.download(check_result)
            print(json.dumps({"artifact_path": str(artifact), **check_result.to_dict()}, indent=2, sort_keys=True))
            return 0
        if args.command == "apply":
            check_result = client.check()
            outcome = client.apply(check_result)
            print(
                json.dumps(
                    {
                        "installed_version": outcome.version,
                        "release_path": str(outcome.release_path),
                        "artifact_kind": outcome.artifact_kind,
                        **check_result.to_dict(),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "rollback":
            outcome = client.rollback()
            print(
                json.dumps(
                    {
                        "installed_version": outcome.version,
                        "release_path": str(outcome.release_path),
                        "artifact_kind": outcome.artifact_kind,
                        "rolled_back": outcome.rolled_back,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "unattended":
            print(json.dumps(client.unattended(), indent=2, sort_keys=True))
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
