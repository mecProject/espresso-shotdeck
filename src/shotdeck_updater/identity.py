"""Device fingerprint collection and normalization."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path


MAC_RE = re.compile(r"[^0-9a-f]")


@dataclass(slots=True)
class IdentityPolicy:
    include_cpu_serial: bool = True
    include_mac_addresses: bool = True
    include_machine_id: bool = True
    interface_allowlist: tuple[str, ...] = ()
    interface_denylist: tuple[str, ...] = ("lo",)
    expose_raw_identifiers: bool = False
    hardware_group_override: str | None = None


@dataclass(slots=True)
class DeviceIdentity:
    canonical_identity: str
    device_fingerprint: str
    device_short_id: str
    hardware_group: str
    raw_components: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self, include_raw: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "device_fingerprint": self.device_fingerprint,
            "device_short_id": self.device_short_id,
            "hardware_group": self.hardware_group,
            "canonical_identity_sha256": hashlib.sha256(
                self.canonical_identity.encode("utf-8")
            ).hexdigest(),
        }
        if include_raw:
            payload["canonical_identity"] = self.canonical_identity
            payload["raw_components"] = self.raw_components
        return payload

    def enrollment_record(self, product: str, channel: str) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "product": product,
            "device_fingerprint": self.device_fingerprint,
            "device_short_id": self.device_short_id,
            "hardware_group": self.hardware_group,
            "channel": channel,
        }


def normalize_mac(value: str) -> str:
    normalized = MAC_RE.sub("", value.strip().lower())
    if len(normalized) != 12:
        raise ValueError(f"invalid MAC address: {value!r}")
    return normalized


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip("\x00\r\n\t ")
    except FileNotFoundError:
        return None


def read_cpu_serial(cpuinfo_path: Path = Path("/proc/cpuinfo")) -> str | None:
    content = _read_file(cpuinfo_path)
    if not content:
        return None
    for line in content.splitlines():
        if line.lower().startswith("serial"):
            _, _, value = line.partition(":")
            serial = value.strip().lower()
            if serial:
                return serial
    return None


def list_mac_addresses(
    sys_class_net: Path = Path("/sys/class/net"),
    allowlist: tuple[str, ...] = (),
    denylist: tuple[str, ...] = ("lo",),
) -> list[str]:
    addresses: list[str] = []
    if not sys_class_net.exists():
        return addresses
    for interface in sorted(item.name for item in sys_class_net.iterdir() if item.is_dir()):
        if allowlist and interface not in allowlist:
            continue
        if interface in denylist:
            continue
        address = _read_file(sys_class_net / interface / "address")
        if not address:
            continue
        try:
            normalized = normalize_mac(address)
        except ValueError:
            continue
        if normalized == "000000000000":
            continue
        addresses.append(f"{interface}:{normalized}")
    return sorted(set(addresses))


def detect_hardware_group(
    *,
    model_path: Path = Path("/proc/device-tree/model"),
    fallback_machine: str | None = None,
) -> str:
    model = _read_file(model_path) or fallback_machine or platform.machine()
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return slug or "unknown"


def collect_identity(
    policy: IdentityPolicy | None = None,
    *,
    cpuinfo_path: Path = Path("/proc/cpuinfo"),
    machine_id_path: Path = Path("/etc/machine-id"),
    sys_class_net: Path = Path("/sys/class/net"),
    device_model_path: Path = Path("/proc/device-tree/model"),
) -> DeviceIdentity:
    policy = policy or IdentityPolicy()
    components: dict[str, list[str]] = {}

    if policy.include_cpu_serial:
        serial = read_cpu_serial(cpuinfo_path)
        if serial:
            components["cpu_serial"] = [serial]
    if policy.include_machine_id:
        machine_id = _read_file(machine_id_path)
        if machine_id:
            components["machine_id"] = [machine_id.lower()]
    if policy.include_mac_addresses:
        macs = list_mac_addresses(
            sys_class_net=sys_class_net,
            allowlist=policy.interface_allowlist,
            denylist=policy.interface_denylist,
        )
        if macs:
            components["mac_addresses"] = macs

    parts: list[str] = []
    for name in sorted(components):
        for value in sorted(components[name]):
            parts.append(f"{name}={value}")
    canonical_identity = "|".join(parts)
    fingerprint = hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()
    short_id = fingerprint[:12]
    hardware_group = policy.hardware_group_override or detect_hardware_group(
        model_path=device_model_path,
        fallback_machine=platform.machine(),
    )
    raw_components = components if policy.expose_raw_identifiers else {}
    return DeviceIdentity(
        canonical_identity=canonical_identity,
        device_fingerprint=fingerprint,
        device_short_id=short_id,
        hardware_group=hardware_group,
        raw_components=raw_components,
    )


def identity_to_json(identity: DeviceIdentity, include_raw: bool = False) -> str:
    return json.dumps(identity.to_dict(include_raw=include_raw), indent=2, sort_keys=True)
