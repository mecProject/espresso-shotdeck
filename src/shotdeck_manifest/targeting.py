"""Applicability checks for release manifests against device state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .models import AllowlistEntry, ReleaseManifest


@dataclass(slots=True)
class DeviceContext:
    product: str
    fingerprint: str
    short_id: str
    hardware_group: str
    channel: str
    current_version: str
    updater_version: str
    allowlist_entry: AllowlistEntry | None = None


@dataclass(slots=True)
class ApplicabilityDecision:
    applicable: bool
    reason: str
    staged_rollout_bucket: int | None = None


def rollout_bucket(fingerprint: str, version: str) -> int:
    digest = hashlib.sha256(f"{fingerprint}:{version}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def evaluate_targeting(
    manifest: ReleaseManifest,
    context: DeviceContext,
) -> ApplicabilityDecision:
    if manifest.product != context.product.lower():
        return ApplicabilityDecision(False, "manifest product does not match device product")

    current_version = Version(context.current_version)
    target_version = Version(manifest.version)
    updater_version = Version(context.updater_version)

    if updater_version < Version(manifest.min_updater_version):
        return ApplicabilityDecision(False, "updater is too old for this manifest")

    effective_channel = context.allowlist_entry.channel if context.allowlist_entry and context.allowlist_entry.channel else context.channel
    effective_hardware_group = (
        context.allowlist_entry.hardware_group
        if context.allowlist_entry and context.allowlist_entry.hardware_group
        else context.hardware_group
    )
    effective_tags = set(context.allowlist_entry.tags if context.allowlist_entry else [])

    if effective_channel.lower() != manifest.channel:
        return ApplicabilityDecision(False, "release channel does not match device channel")

    rules = manifest.rollout
    if rules.channels and effective_channel.lower() not in rules.channels:
        return ApplicabilityDecision(False, "device channel is not included in rollout rules")
    if rules.hardware_groups and effective_hardware_group.lower() not in rules.hardware_groups:
        return ApplicabilityDecision(False, "hardware group is not included in rollout rules")
    if rules.device_fingerprints and context.fingerprint not in rules.device_fingerprints:
        return ApplicabilityDecision(False, "device fingerprint is not allowlisted for this manifest")
    if rules.allowlist_tags and not effective_tags.intersection(rules.allowlist_tags):
        return ApplicabilityDecision(False, "device allowlist tags do not match this rollout")
    if rules.allowlist and context.allowlist_entry is None:
        return ApplicabilityDecision(False, "device is not present in the signed allowlist")
    if rules.current_version and current_version not in SpecifierSet(rules.current_version):
        return ApplicabilityDecision(False, "current installed version is outside the rollout constraint")

    if target_version == current_version:
        return ApplicabilityDecision(False, "device already runs this version")
    if target_version < current_version and not rules.allow_downgrade:
        return ApplicabilityDecision(False, "manifest would downgrade the installed version")

    if rules.staged_rollout_percentage is not None:
        bucket = rollout_bucket(context.fingerprint, manifest.version)
        if bucket >= rules.staged_rollout_percentage:
            return ApplicabilityDecision(
                False,
                "device is outside the staged rollout percentage",
                staged_rollout_bucket=bucket,
            )
        return ApplicabilityDecision(True, "update applies", staged_rollout_bucket=bucket)

    return ApplicabilityDecision(True, "update applies")
