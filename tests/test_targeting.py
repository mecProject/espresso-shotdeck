from __future__ import annotations

from shotdeck_manifest import AllowlistEntry, ArtifactRef, ReleaseManifest, RollbackInfo, RolloutRules
from shotdeck_manifest.targeting import DeviceContext, evaluate_targeting, rollout_bucket


def make_manifest() -> ReleaseManifest:
    return ReleaseManifest(
        schema_version="1.0",
        product="shotdeck",
        channel="pilot",
        version="1.5.0",
        released_at="2026-04-15T12:00:00Z",
        min_updater_version="0.1.0",
        full_artifact=ArtifactRef(
            url="https://updates.example.com/artifacts/shotdeck-1.5.0-full.tar.gz",
            sha256="c" * 64,
            size=4096,
            filename="shotdeck-1.5.0-full.tar.gz",
            install_tree_sha256="d" * 64,
        ),
        rollout=RolloutRules(
            channels=["pilot"],
            hardware_groups=["raspberry-pi-zero-2-w"],
            current_version=">=1.4,<1.5",
            allowlist_tags=["pilot"],
        ),
        rollback=RollbackInfo(),
        notes=[],
    )


def test_targeting_accepts_matching_device() -> None:
    manifest = make_manifest()
    context = DeviceContext(
        product="shotdeck",
        fingerprint="1" * 64,
        short_id="111111111111",
        hardware_group="raspberry-pi-zero-2-w",
        channel="pilot",
        current_version="1.4.2",
        updater_version="0.1.0",
        allowlist_entry=AllowlistEntry(
            fingerprint="1" * 64,
            channel="pilot",
            hardware_group="raspberry-pi-zero-2-w",
            tags=["pilot"],
        ),
    )
    decision = evaluate_targeting(manifest, context)
    assert decision.applicable is True


def test_targeting_rejects_wrong_hardware_group() -> None:
    manifest = make_manifest()
    context = DeviceContext(
        product="shotdeck",
        fingerprint="1" * 64,
        short_id="111111111111",
        hardware_group="raspberry-pi-4",
        channel="pilot",
        current_version="1.4.2",
        updater_version="0.1.0",
        allowlist_entry=AllowlistEntry(fingerprint="1" * 64, tags=["pilot"]),
    )
    decision = evaluate_targeting(manifest, context)
    assert decision.applicable is False
    assert "hardware group" in decision.reason


def test_staged_rollout_is_deterministic() -> None:
    bucket = rollout_bucket("2" * 64, "1.6.0")
    manifest = ReleaseManifest(
        schema_version="1.0",
        product="shotdeck",
        channel="stable",
        version="1.6.0",
        released_at="2026-04-15T12:00:00Z",
        min_updater_version="0.1.0",
        full_artifact=ArtifactRef(
            url="https://updates.example.com/artifacts/shotdeck-1.6.0-full.tar.gz",
            sha256="e" * 64,
            size=1024,
            filename="shotdeck-1.6.0-full.tar.gz",
            install_tree_sha256="f" * 64,
        ),
        rollout=RolloutRules(staged_rollout_percentage=bucket + 1),
        rollback=RollbackInfo(),
    )
    context = DeviceContext(
        product="shotdeck",
        fingerprint="2" * 64,
        short_id="222222222222",
        hardware_group="raspberry-pi-zero-2-w",
        channel="stable",
        current_version="1.5.0",
        updater_version="0.1.0",
    )
    decision = evaluate_targeting(manifest, context)
    assert decision.applicable is True
    assert decision.staged_rollout_bucket == bucket
