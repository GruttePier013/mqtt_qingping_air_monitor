"""Tests for the Bluetooth provisioning protocol module (no hardware)."""
from __future__ import annotations

import asyncio

import pytest

from custom_components.qingping_cgdn1 import ble_provision as bp


class FakeChar:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid
        self.properties = ["write-without-response", "notify"]


class FakeService:
    def __init__(self) -> None:
        self.chars = {u: FakeChar(u) for u in (
            bp.CHAR_WIFI_WRITE, bp.CHAR_WIFI_NOTIFY, bp.CHAR_CFG_WRITE,
            bp.CHAR_CFG_NOTIFY, bp.CHAR_INFO_WRITE, bp.CHAR_INFO_NOTIFY)}

    def get_characteristic(self, uuid):
        return self.chars.get(uuid)


class FakeServices:
    def __init__(self, present: bool = True) -> None:
        self.service = FakeService() if present else None

    def get_service(self, uuid):
        return self.service if uuid == bp.SERVICE_UUID else None


class FakeClient:
    def __init__(self, present: bool = True, wifi_mac: bytes | None = None) -> None:
        self.services = FakeServices(present)
        self.writes: list[tuple[str, bytes, bool]] = []
        self._notify = {}
        self._wifi_mac = wifi_mac

    async def write_gatt_char(self, char, data, response=False):
        self.writes.append((char.uuid, bytes(data), response))
        if char.uuid == bp.CHAR_INFO_WRITE and self._wifi_mac and bp.CHAR_INFO_NOTIFY in self._notify:
            self._notify[bp.CHAR_INFO_NOTIFY](None, bytearray([7, bp.PKT_WIFI_MAC]) + self._wifi_mac)

    async def start_notify(self, char, cb):
        self._notify[char.uuid] = cb

    async def stop_notify(self, char):
        self._notify.pop(char.uuid, None)


def _config(**kw) -> bp.ProvisionConfig:
    base = dict(wifi_ssid="Example Net", wifi_password="pa,ss", mqtt_host="192.0.2.10",
                mqtt_port=1883, mqtt_username="qingping", mqtt_password="secret")
    base.update(kw)
    return bp.ProvisionConfig.for_wifi_mac("7CC29400BEEF", **base)


def _reassemble(writes, uuid):
    """Concatenate chunks per characteristic and split back into packets."""
    stream = b"".join(d for u, d, _ in writes if u == uuid)
    packets, i = [], 0
    while i < len(stream):
        n = stream[i]
        packets.append((stream[i + 1], stream[i + 2:i + 1 + n]))
        i += 1 + n
    return packets


# ---------------------------------------------------------------- encoding
def test_mac_helpers():
    assert bp.normalize_mac("7c:c2:94:00:be:ef") == "7CC29400BEEF"
    assert bp.wifi_mac_from_ble("7C:C2:94:00:BE:F1") == "7CC29400BEEF"
    assert bp.wifi_mac_from_ble("7C:C2:94:00:01:01") == "7CC2940000FF"
    with pytest.raises(bp.ProvisioningError):
        bp.normalize_mac("zz")


def test_build_packet_and_chunks():
    assert bp.build_packet(0x0B) == b"\x01\x0b"
    assert bp.build_packet(0x17, b"abc") == b"\x04\x17abc"
    with pytest.raises(bp.ProvisioningError):
        bp.build_packet(1, b"x" * 255)
    assert [len(c) for c in bp.chunked(b"x" * 45)] == [20, 20, 5]


def test_topic_layout_and_payloads():
    c = _config()
    assert c.client_id == "qingping-7CC29400BEEF"
    assert c.topic_read == "qingping/7CC29400BEEF/down"
    assert c.topic_write == "qingping/7CC29400BEEF/up"
    assert c.wifi_payload() == b'"Example Net","pa,ss"'
    assert c.mqtt_payload() == b"192.0.2.10 1883 qingping secret"
    assert c.topics_payload() == b"qingping-7CC29400BEEF qingping/7CC29400BEEF/down qingping/7CC29400BEEF/up"
    assert len(c.link_token) == 16
    assert "secret" not in str(c.redacted()) and "pa,ss" not in str(c.redacted())


@pytest.mark.parametrize("kw", [
    {"mqtt_password": "has space"},
    {"mqtt_username": ""},
    {"mqtt_host": "my host"},
    {"wifi_ssid": 'quo"te'},
    {"wifi_ssid": ""},
    {"mqtt_port": 0},
])
def test_invalid_input(kw):
    with pytest.raises(bp.ProvisioningError):
        _config(**kw).validate()


# ------------------------------------------------------------------ GATT
async def test_provision_writes_expected_sequence():
    client = FakeClient()
    steps: list[str] = []
    cfg = _config()
    await bp.provision(client, cfg, step_delay=0, chunk_delay=0, progress=steps.append)

    assert steps == ["wifi", "token", "token", "mqtt", "topics", "done"]
    assert all(len(d) <= 20 and r is False for _, d, r in client.writes)
    assert _reassemble(client.writes, bp.CHAR_WIFI_WRITE) == [(0x01, cfg.wifi_payload())]
    assert _reassemble(client.writes, bp.CHAR_CFG_WRITE) == [
        (0x01, cfg.link_token), (0x02, cfg.link_token),
        (0x17, cfg.mqtt_payload()), (0x18, cfg.topics_payload()),
    ]
    # Wi-Fi is written before the MQTT settings
    order = [u for u, _, _ in client.writes]
    assert order.index(bp.CHAR_WIFI_WRITE) < order.index(bp.CHAR_CFG_WRITE)


async def test_provision_outside_pairing_mode():
    with pytest.raises(bp.ProvisioningError, match="pairing mode"):
        await bp.provision(FakeClient(present=False), _config(), step_delay=0)


async def test_provision_uses_write_with_response_when_needed():
    client = FakeClient()
    for ch in client.services.service.chars.values():
        ch.properties = ["write"]
    await bp.provision(client, _config(), step_delay=0, chunk_delay=0)
    assert all(r is True for _, _, r in client.writes)


async def test_read_wifi_mac():
    client = FakeClient(wifi_mac=bytes.fromhex("7CC29400BEEF"))
    assert await bp.read_wifi_mac(client, timeout=1) == "7CC29400BEEF"


async def test_read_wifi_mac_timeout():
    assert await bp.read_wifi_mac(FakeClient(), timeout=0.05) is None
