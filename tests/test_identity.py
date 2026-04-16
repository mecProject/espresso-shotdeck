from __future__ import annotations

from shotdeck_updater.identity import IdentityPolicy, collect_identity, normalize_mac


def test_normalize_mac() -> None:
    assert normalize_mac("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"


def test_collect_identity_is_order_stable(tmp_path) -> None:
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("Serial\t\t: 000000001234abcd\n", encoding="utf-8")
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("machine-id-value\n", encoding="utf-8")
    model = tmp_path / "model"
    model.write_text("Raspberry Pi Zero 2 W", encoding="utf-8")
    sys_class_net = tmp_path / "net"
    (sys_class_net / "wlan0").mkdir(parents=True)
    (sys_class_net / "wlan0" / "address").write_text("B8:27:EB:AA:BB:CC\n", encoding="utf-8")
    (sys_class_net / "eth0").mkdir(parents=True)
    (sys_class_net / "eth0" / "address").write_text("DC:A6:32:11:22:33\n", encoding="utf-8")

    identity_a = collect_identity(
        IdentityPolicy(expose_raw_identifiers=True),
        cpuinfo_path=cpuinfo,
        machine_id_path=machine_id,
        sys_class_net=sys_class_net,
        device_model_path=model,
    )
    identity_b = collect_identity(
        IdentityPolicy(expose_raw_identifiers=True),
        cpuinfo_path=cpuinfo,
        machine_id_path=machine_id,
        sys_class_net=sys_class_net,
        device_model_path=model,
    )

    assert identity_a.device_fingerprint == identity_b.device_fingerprint
    assert identity_a.device_short_id == identity_a.device_fingerprint[:12]
    assert identity_a.hardware_group == "raspberry-pi-zero-2-w"
    assert "cpu_serial" in identity_a.raw_components
