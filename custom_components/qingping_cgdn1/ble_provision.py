# SPDX-License-Identifier: MIT
"""Bluetooth provisioning for the Qingping Air Monitor Lite (CGDN1).

Writes Wi-Fi credentials, MQTT broker and MQTT topics into a monitor that is in
pairing mode (top bar held ~8 s until the large Wi-Fi icon), so it publishes to
your own broker without the Qingping cloud.

This module has **no Home Assistant imports**. It only needs ``bleak`` and is
shared by the integration's Bluetooth config flow and by the standalone
cross-platform CLI in ``tools/qingping-provision``.

Protocol facts (setup service of the stock 4.x firmware):

* service ``22210000-554a-4546-5542-46534450464d``;
* packets ``<len><type><data>`` where ``len = 1 + len(data)``, written in
  chunks of at most 20 bytes, write-without-response;
* characteristics (16-bit UUIDs in the Bluetooth base UUID):

  ======  ======  =====  ================================================
  write   notify  type   payload
  ======  ======  =====  ================================================
  0x000D  0x000E  0x01   Wi-Fi: ``"ssid","password"``
  0x0001  0x0002  0x01   link token (16 bytes), repeated with type 0x02
  0x0001  0x0002  0x17   MQTT: ``host port username password``
  0x0001  0x0002  0x18   topics: ``client_id read_topic write_topic``
  0x0017  0x0018  0x0B   query Wi-Fi MAC (answer ``<len><0x0B><6 bytes>``)
  ======  ======  =====  ================================================

The Wi-Fi MAC (used in the MQTT topics) is the Bluetooth MAC minus 2.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from bleak import BleakClient
    from bleak.backends.characteristic import BleakGATTCharacteristic

_LOGGER = logging.getLogger(__name__)

SERVICE_UUID = "22210000-554a-4546-5542-46534450464d"
LOCAL_NAME = "Qingping Air Monitor Lite"


def _uuid16(short: int) -> str:
    return f"{short:08x}-0000-1000-8000-00805f9b34fb"


CHAR_WIFI_WRITE = _uuid16(0x000D)
CHAR_WIFI_NOTIFY = _uuid16(0x000E)
CHAR_CFG_WRITE = _uuid16(0x0001)
CHAR_CFG_NOTIFY = _uuid16(0x0002)
CHAR_INFO_WRITE = _uuid16(0x0017)
CHAR_INFO_NOTIFY = _uuid16(0x0018)

PKT_WIFI = 0x01
PKT_TOKEN_A = 0x01
PKT_TOKEN_B = 0x02
PKT_MQTT = 0x17
PKT_TOPICS = 0x18
PKT_WIFI_MAC = 0x0B

CHUNK_SIZE = 20
MAX_DATA = 254          # len byte = 1 + len(data) <= 255
BLE_TO_WIFI_OFFSET = 2  # Bluetooth MAC = Wi-Fi MAC + 2
DEFAULT_PREFIX = "qingping"


class ProvisioningError(Exception):
    """Provisioning failed or the input cannot be encoded."""


# --------------------------------------------------------------- helpers
def normalize_mac(mac: str) -> str:
    """Return 12 upper-case hex characters, or raise ProvisioningError."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(digits) != 12:
        raise ProvisioningError(f"not a MAC address: {mac!r}")
    return digits.upper()


def wifi_mac_from_ble(ble_mac: str, offset: int = BLE_TO_WIFI_OFFSET) -> str:
    """Wi-Fi MAC (topic MAC) from the Bluetooth MAC: Bluetooth minus ``offset``."""
    value = (int(normalize_mac(ble_mac), 16) - offset) % (1 << 48)
    return f"{value:012X}"


def build_packet(pkt_type: int, data: bytes | None = None) -> bytes:
    """Encode one ``<len><type><data>`` packet."""
    if not 0 <= pkt_type <= 0xFF:
        raise ProvisioningError(f"packet type out of range: {pkt_type}")
    data = data or b""
    if len(data) > MAX_DATA:
        raise ProvisioningError(f"payload too long ({len(data)} > {MAX_DATA} bytes)")
    return bytes((len(data) + 1, pkt_type)) + data


def chunked(packet: bytes, size: int = CHUNK_SIZE) -> list[bytes]:
    return [packet[i:i + size] for i in range(0, len(packet), size)]


def _no_space(label: str, value: str) -> str:
    if not value or any(c.isspace() for c in value):
        raise ProvisioningError(f"{label} must be non-empty and contain no spaces")
    return value


@dataclass(frozen=True)
class ProvisionConfig:
    """Everything that is written to the monitor."""

    wifi_ssid: str
    wifi_password: str
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    client_id: str
    topic_read: str     # the topic the DEVICE subscribes to (…/down)
    topic_write: str    # the topic the DEVICE publishes to (…/up)
    link_token: bytes = field(default_factory=lambda: secrets.token_bytes(16))

    @classmethod
    def for_wifi_mac(
        cls,
        wifi_mac: str,
        *,
        wifi_ssid: str,
        wifi_password: str,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str,
        mqtt_password: str,
        prefix: str = DEFAULT_PREFIX,
    ) -> ProvisionConfig:
        """Config with the topic layout used by the integration."""
        mac = normalize_mac(wifi_mac)
        return cls(
            wifi_ssid=wifi_ssid,
            wifi_password=wifi_password,
            mqtt_host=mqtt_host,
            mqtt_port=int(mqtt_port),
            mqtt_username=mqtt_username,
            mqtt_password=mqtt_password,
            client_id=f"{prefix}-{mac}",
            topic_read=f"{prefix}/{mac}/down",
            topic_write=f"{prefix}/{mac}/up",
        )

    # -- payloads (validated) -------------------------------------------
    def wifi_payload(self) -> bytes:
        for label, value in (("Wi-Fi SSID", self.wifi_ssid), ("Wi-Fi password", self.wifi_password)):
            if '"' in value:
                raise ProvisioningError(f"{label} must not contain a double quote")
        if not self.wifi_ssid:
            raise ProvisioningError("Wi-Fi SSID is empty")
        return f'"{self.wifi_ssid}","{self.wifi_password}"'.encode()

    def mqtt_payload(self) -> bytes:
        if not 1 <= self.mqtt_port <= 65535:
            raise ProvisioningError("MQTT port must be 1-65535")
        parts = (
            _no_space("MQTT host", self.mqtt_host),
            str(self.mqtt_port),
            _no_space("MQTT username", self.mqtt_username),
            _no_space("MQTT password", self.mqtt_password),
        )
        return " ".join(parts).encode()

    def topics_payload(self) -> bytes:
        parts = (
            _no_space("MQTT client ID", self.client_id),
            _no_space("read topic", self.topic_read),
            _no_space("write topic", self.topic_write),
        )
        return " ".join(parts).encode()

    def validate(self) -> None:
        """Raise ProvisioningError if anything cannot be encoded."""
        if len(self.link_token) != 16:
            raise ProvisioningError("link token must be 16 bytes")
        for payload in (self.wifi_payload(), self.mqtt_payload(), self.topics_payload()):
            build_packet(0, payload)

    def redacted(self) -> dict[str, Any]:
        """For logging: no passwords, no token."""
        return {
            "wifi_ssid": self.wifi_ssid, "mqtt_host": self.mqtt_host, "mqtt_port": self.mqtt_port,
            "mqtt_username": self.mqtt_username, "client_id": self.client_id,
            "topic_read": self.topic_read, "topic_write": self.topic_write,
        }


# ------------------------------------------------------------- GATT I/O
def _characteristic(client: BleakClient, uuid: str) -> BleakGATTCharacteristic:
    service = client.services.get_service(SERVICE_UUID)
    if service is None:
        raise ProvisioningError(
            "setup service not found: is the monitor in pairing mode "
            "(hold the top bar ~8 s until the large Wi-Fi icon)?"
        )
    char = service.get_characteristic(uuid)
    if char is None:
        raise ProvisioningError(f"characteristic {uuid} not found (unsupported firmware?)")
    return char


async def _write(client: BleakClient, uuid: str, packet: bytes, chunk_delay: float) -> None:
    char = _characteristic(client, uuid)
    response = "write-without-response" not in char.properties
    for chunk in chunked(packet):
        await client.write_gatt_char(char, chunk, response=response)
        if chunk_delay:
            await asyncio.sleep(chunk_delay)


async def provision(
    client: BleakClient,
    config: ProvisionConfig,
    *,
    step_delay: float = 1.0,
    chunk_delay: float = 0.05,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Write Wi-Fi, link token, MQTT broker and topics to a connected monitor.

    The device does not confirm the writes. Verify by waiting for its first
    message on ``config.topic_write``.
    """
    config.validate()
    report = progress or (lambda step: _LOGGER.debug("provisioning: %s", step))
    _characteristic(client, CHAR_CFG_WRITE)  # fail early outside pairing mode

    steps: tuple[tuple[str, str, bytes], ...] = (
        ("wifi", CHAR_WIFI_WRITE, build_packet(PKT_WIFI, config.wifi_payload())),
        ("token", CHAR_CFG_WRITE, build_packet(PKT_TOKEN_A, config.link_token)),
        ("token", CHAR_CFG_WRITE, build_packet(PKT_TOKEN_B, config.link_token)),
        ("mqtt", CHAR_CFG_WRITE, build_packet(PKT_MQTT, config.mqtt_payload())),
        ("topics", CHAR_CFG_WRITE, build_packet(PKT_TOPICS, config.topics_payload())),
    )
    for name, uuid, packet in steps:
        report(name)
        await _write(client, uuid, packet, chunk_delay)
        await asyncio.sleep(step_delay)
    report("done")


async def read_wifi_mac(client: BleakClient, timeout: float = 5.0) -> str | None:
    """Ask the monitor for its Wi-Fi MAC (useful where the OS hides the BLE MAC, e.g. macOS).

    Returns 12 upper-case hex characters, or None if there is no answer.
    """
    loop = asyncio.get_running_loop()
    answer: asyncio.Future[bytes] = loop.create_future()

    def _on_notify(_sender: Any, data: bytearray) -> None:
        if len(data) >= 8 and data[1] == PKT_WIFI_MAC and not answer.done():
            answer.set_result(bytes(data[2:8]))

    notify = _characteristic(client, CHAR_INFO_NOTIFY)
    await client.start_notify(notify, _on_notify)
    try:
        await _write(client, CHAR_INFO_WRITE, build_packet(PKT_WIFI_MAC), 0)
        raw = await asyncio.wait_for(answer, timeout)
    except TimeoutError:
        return None
    finally:
        try:
            await client.stop_notify(notify)
        except Exception:  # noqa: BLE001 - best effort
            pass
    return raw.hex().upper()
