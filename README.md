# Shotdeck Public Updater

This subtree is designed to live in a public repository. It contains only the updater runtime, manifest/signature logic, admin tooling, systemd units, example metadata, and tests. It does not contain Shotdeck application source code, build secrets, or private signing keys.

## Architecture

- Devices run `shotdeck-updater` from a systemd timer and only hold a public Ed25519 verification key.
- The device builds a stable fingerprint from CPU serial, MAC addresses, and optional machine ID, hashes the canonical identity with SHA-256, and logs only a short hash by default.
- Update decisions happen before artifact download by checking signed manifest rules, the optional allowlist file, rollout channel, hardware group, fingerprint, staged rollout percentage, and installed-version constraints.
- Artifacts are authenticated by signed manifest metadata and verified again with SHA-256 after download.
- Full updates use versioned directories under `/opt/shotdeck/releases/<version>/` and atomic symlink activation through `/opt/shotdeck/current`.
- Patch updates use a conservative tar-overlay strategy with exact base version and tree checksum checks; the updater falls back to the full artifact whenever the patch is not eligible.
- Failed activations roll back to the previous release and restart the prior service target.

## Repository Layout

- `src/shotdeck_manifest/`: typed manifest and allowlist models, targeting rules, Ed25519 signing and verification.
- `src/shotdeck_updater/`: runtime updater, identity abstraction, downloader, installer, patching layer, CLI.
- `src/shotdeck_admin/`: operator tooling for key generation, manifest signing, allowlist editing, and patch generation.
- `systemd/`: app service, updater service, and updater timer units.
- `scripts/install_updater.sh`: headless installer for Raspberry Pi OS.
- `examples/`: updater config, allowlist, manifest, keys, and CI workflow examples.
- `tests/`: pytest coverage for signatures, targeting, downloads, rollback, patch eligibility, and identity normalization.

## Threat Model

- Protected: private Python source, signing keys, integrity of update metadata, integrity of downloaded artifacts, safe rollback on bad installs, accidental rollout to the wrong devices.
- Assumed hostile: static HTTPS host compromise, corrupted network transfers, stale manifests, power loss mid-download, non-target devices trying to apply restricted manifests.
- Out of scope with a fully public artifact host: preventing a determined third party from downloading a public binary blob by URL alone. This design prevents non-target devices from accepting or activating restricted updates, but confidential payload distribution still requires a private artifact host or per-device encryption.

## Runtime Flow

1. `shotdeck-updater check` downloads the channel manifest, verifies its Ed25519 signature, optionally downloads the allowlist file, and evaluates targeting locally.
2. If applicable, `shotdeck-updater download` streams the selected patch or full tarball to `/opt/shotdeck/update-cache/`, verifies size and SHA-256, and keeps partial files separate.
3. `shotdeck-updater apply` prepares a staged release directory, validates the extracted tree hash, swaps `/opt/shotdeck/current` atomically, restarts `shotdeck.service`, and rolls back on health-check failure.
4. `shotdeck-updater rollback` re-points the symlink to `/opt/shotdeck/previous`.

## Operating Notes

- Manifests should be generated in private CI after `build_nuitka.sh` finishes and signed offline or in a tightly scoped signing step.
- The public repo should only receive the safe outputs: signed manifests, allowlists of hashed device IDs, tarball artifacts, patch metadata, and updater code.
- Keep the verification key under `/etc/shotdeck/update-signing-key.pem` and never deploy the private key to a device.
- Prefer full artifacts as the default release path. Patch artifacts are useful for bandwidth reduction, but they are optional.

## Limitations

- The default health check trusts `systemctl is-active shotdeck`. If you need an application-level probe, configure `hooks.health_check`.
- The updater rejects symlinks inside release artifacts for path-safety and auditability.
- Restricted manifests prevent non-target devices from accepting or activating an update, but a fully public artifact URL still exposes the compiled binary blob itself to anyone who knows the URL.
