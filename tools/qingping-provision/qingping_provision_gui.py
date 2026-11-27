#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Windows 11 GUI for provisioning a Qingping Air Monitor Lite (CGDN1) over Bluetooth.

Double-click ``start_gui.bat`` (first run installs ``bleak`` in a local venv), or run
``QingpingProvision.exe`` from the GitHub release, or ``pythonw qingping_provision_gui.py``.

The window walks through three steps: find the monitor (in pairing mode), enter
the Wi-Fi network and the MQTT broker, write. The Wi-Fi password is never saved; the
other fields (including the MQTT password) are remembered in %APPDATA%\\QingpingProvision\\settings.json.

Bluetooth runs on its own asyncio loop in a worker thread (MTA on Windows), so
the Tk main loop never blocks and WinRT does not collide with Tk's thread.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import locale
import os
import queue
import sys
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))))
import qingping_provision as cli  # noqa: E402  (shares the protocol loader)

bp = cli.bp
APP_NAME = "QingpingProvision"
VERSION = "2.3.1"

# ------------------------------------------------------------------ texts
TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Qingping Air Monitor Lite: Bluetooth setup",
        "step1": "1  Monitor",
        "step1_help": "1. Power the device over USB.\n2. Put the Air Monitor in Wi-Fi pairing mode.",
        "scan": "Scan",
        "scanning": "Scanning…",
        "col_name": "Name", "col_address": "Bluetooth address", "col_rssi": "Signal", "col_wifi": "Wi-Fi MAC (topic)",
        "wifi_mac": "Wi-Fi MAC", "read_mac": "Ask device",
        "read_mac_tip": "Asks the monitor itself for its Wi-Fi MAC over Bluetooth, to verify the calculated value "
                        "(Bluetooth MAC minus 2). Only needed when the list shows no Wi-Fi MAC (macOS) or when the "
                        "monitor does not show up in Home Assistant after writing.",
        "step2": "2  Wi-Fi and MQTT broker (all fields required)",
        "step2_help": "The Wi-Fi network and the MQTT user details must be written together.",
        "wifi_box": "Wi-Fi network (2.4 GHz)", "mqtt_box": "MQTT broker",
        "missing": "Still to fill in: {fields}.",
        "open_wifi_title": "Wi-Fi without password?",
        "open_wifi_ask": "The Wi-Fi password is empty. Is this an open network without a password?",
        "ssid": "Network name (SSID)", "wifi_password": "Password", "show": "Show",
        "host": "Broker LAN IP", "port": "Port", "user": "User for the monitor", "mqtt_password": "Password",
        "prefix": "Topic prefix",
        "check": "Check", "provision": "Write to monitor",
        "log": "Log",
        "raw": "Bluetooth (raw)",
        "clear": "Clear", "copy": "Copy",
        "raw_secrets": "Show Wi-Fi password in raw data",
        "no_device": "Select a monitor in the list (Scan first).",
        "found": "Found {n} monitor(s).",
        "none_found": "No Qingping found, although {n} other Bluetooth device(s) were seen, so Bluetooth itself works.\n\n"
                      "• Is the large Wi-Fi icon (still) on the screen? Pairing mode ends after a while: hold the top bar "
                      "for 8 seconds again.\n"
                      "• Keep the monitor within about 2 metres of this computer.\n"
                      "• Close the Qingping+ app on your phone; it can keep the monitor busy.",
        "none_seen": "Bluetooth is on, but not a single Bluetooth device was seen in {s} seconds. "
                     "The adapter does not seem to scan.\n\n"
                     "• Turn Bluetooth off and on again (Settings → Bluetooth & devices) and scan again.\n"
                     "• For a USB dongle: plug it into another port, or restart the computer.\n"
                     "• Still nothing: use another computer or Bluetooth adapter (Bluetooth 4.0 / LE or newer).",
        "none_title": "No monitor found",
        "connecting": "Connecting to {address}…",
        "step": "  → sending: {step}",
        "step_names": "wifi=Wi-Fi network|token=link token|mqtt=MQTT broker|topics=topics",
        "sent_all": "  → all packets sent",
        "done": "Transfer complete: all settings were sent to the monitor over Bluetooth. The monitor confirms "
                "nothing, so check yourself that it really connects:\n\n"
                "1. The large Wi-Fi icon disappears; the monitor joins \"{ssid}\".\n"
                "2. Mosquitto log: \"New client connected … as {client_id} … u'{user}'\". If it says \"not authorised\", "
                "the user or password is wrong: pairing mode on and write again.\n"
                "3. Within about a minute messages arrive on {topic}.\n"
                "4. Home Assistant: a new monitor appears under Settings → Devices & services → Discovered; an "
                "existing monitor shows values again.",
        "error_title": "Error",
        "config": "Configuration (Wi-Fi password hidden):",
        "mac_read": "Device reports Wi-Fi MAC: {mac}",
        "mac_match": "  matches the value calculated from the Bluetooth address.",
        "mac_differs": "  differs from the calculated {calc}; the value reported by the device is used.",
        "mac_none": "The device did not answer. Enter the Wi-Fi MAC (Bluetooth MAC minus 2).",
        "bt_error": "Bluetooth error: {error}",
        "bt_error_hint": "Try again: put the monitor back into pairing mode (large Wi-Fi icon), keep it close by, "
                         "and turn Bluetooth off and on if needed.",
        "technical": "technical: {error}",
        "bt_label": "Bluetooth:",
        "bt_on": "on", "bt_off": "off", "bt_disabled": "disabled", "bt_none": "no adapter", "bt_no_le": "no Bluetooth LE",
        "err_bt_none": "This computer has no (working) Bluetooth adapter.\n\n"
                       "Use another computer with Bluetooth, or plug in a USB Bluetooth adapter "
                       "(Bluetooth 4.0 / LE or newer). If the computer does have Bluetooth, check that the adapter is "
                       "not disabled in Device Manager.",
        "err_bt_no_le": "The Bluetooth adapter of this computer does not support Bluetooth Low Energy, which the monitor "
                        "needs.\n\nUse another computer or a USB Bluetooth adapter (Bluetooth 4.0 / LE or newer).",
        "err_bt_off": "Bluetooth is turned off.\n\nTurn it on under Settings → Bluetooth & devices (or Win+A, "
                      "quick settings), wait a few seconds and click Scan again.",
        "err_bt_disabled": "Bluetooth is disabled: airplane mode is on, or the adapter is disabled in Device Manager.\n\n"
                           "Turn off airplane mode (Win+A), turn Bluetooth on and click Scan again.",
        "err_bt_denied": "Windows does not allow this program to use Bluetooth.\n\nCheck Settings → Privacy & security, "
                         "or start the program once as the logged-in user (not via another account).",
        "err_device_gone": "The monitor can no longer be found over Bluetooth.\n\nPairing mode probably ended: hold the "
                           "top bar 8 seconds until the large Wi-Fi icon appears, click Scan and try again.",
        "err_connect": "Could not connect to the monitor (no answer).\n\nKeep it within about 2 metres, close the "
                       "Qingping+ app on your phone, put the monitor back into pairing mode and try again.",
        "busy": "Busy…",
        "ready": "Ready",
    },
    "nl": {
        "title": "Qingping Air Monitor Lite: instellen via Bluetooth",
        "step1": "1  Monitor",
        "step1_help": "1. Gebruik USB-stroom op het apparaat.\n2. Zet de Air Monitor in wifi-koppelmodus.",
        "scan": "Zoeken",
        "scanning": "Zoeken…",
        "col_name": "Naam", "col_address": "Bluetooth-adres", "col_rssi": "Signaal", "col_wifi": "Wifi-MAC (topic)",
        "wifi_mac": "Wifi-MAC", "read_mac": "Opvragen",
        "read_mac_tip": "Vraagt het wifi-MAC via Bluetooth op bij de monitor zelf, ter controle van de berekende waarde "
                        "(Bluetooth-MAC min 2). Alleen nodig als de lijst geen wifi-MAC toont (macOS) of als de monitor "
                        "na het schrijven niet in Home Assistant verschijnt.",
        "step2": "2  Wifi en MQTT-broker (alles verplicht)",
        "step2_help": "Wifi-netwerk en MQTT-gebruikersgegevens moeten tegelijk geschreven worden.",
        "wifi_box": "Wifi-netwerk (2,4 GHz)", "mqtt_box": "MQTT-broker",
        "missing": "Vul nog in: {fields}.",
        "open_wifi_title": "Wifi zonder wachtwoord?",
        "open_wifi_ask": "Het wifi-wachtwoord is leeg. Klopt het dat dit een open netwerk zonder wachtwoord is?",
        "ssid": "Netwerknaam (SSID)", "wifi_password": "Wachtwoord", "show": "Tonen",
        "host": "Broker LAN-IP", "port": "Poort", "user": "Gebruiker voor de monitor", "mqtt_password": "Wachtwoord",
        "prefix": "Topic-prefix",
        "check": "Controleren", "provision": "Naar monitor schrijven",
        "log": "Logboek",
        "raw": "Bluetooth (ruw)",
        "clear": "Wissen", "copy": "Kopiëren",
        "raw_secrets": "Wifi-wachtwoord tonen in ruwe data",
        "no_device": "Kies een monitor in de lijst (eerst Zoeken).",
        "found": "{n} monitor(s) gevonden.",
        "none_found": "Geen Qingping gevonden, wel {n} andere Bluetooth-apparaten; Bluetooth zelf werkt dus.\n\n"
                      "• Staat het grote wifi-icoon (nog) in beeld? De koppelmodus stopt na een tijdje: houd de balk "
                      "bovenop opnieuw 8 seconden ingedrukt.\n"
                      "• Houd de monitor binnen ongeveer 2 meter van deze computer.\n"
                      "• Sluit de Qingping+-app op je telefoon; die kan de monitor bezet houden.",
        "none_seen": "Bluetooth staat aan, maar in {s} seconden is geen enkel Bluetooth-apparaat gezien. "
                     "De adapter lijkt niet te zoeken.\n\n"
                     "• Zet Bluetooth uit en weer aan (Instellingen → Bluetooth en apparaten) en zoek opnieuw.\n"
                     "• Bij een USB-dongle: andere USB-poort proberen, of de computer herstarten.\n"
                     "• Lukt het nog steeds niet: gebruik een andere computer of Bluetooth-adapter "
                     "(Bluetooth 4.0 / LE of nieuwer).",
        "none_title": "Geen monitor gevonden",
        "connecting": "Verbinden met {address}…",
        "step": "  → versturen: {step}",
        "step_names": "wifi=wifi-netwerk|token=koppeltoken|mqtt=MQTT-broker|topics=topics",
        "sent_all": "  → alle pakketten verstuurd",
        "done": "Overdracht klaar: alle instellingen zijn via Bluetooth naar de monitor gestuurd. De monitor bevestigt "
                "niets, dus controleer zelf of hij echt verbindt:\n\n"
                "1. Het grote wifi-icoon verdwijnt; de monitor verbindt met \"{ssid}\".\n"
                "2. Mosquitto-log: \"New client connected … as {client_id} … u'{user}'\". Staat er \"not authorised\", "
                "dan kloppen gebruiker of wachtwoord niet: koppelmodus aan en opnieuw schrijven.\n"
                "3. Binnen ongeveer een minuut komen er berichten op {topic}.\n"
                "4. Home Assistant: een nieuwe monitor verschijnt onder Instellingen → Apparaten & diensten → Ontdekt; "
                "een bestaande monitor geeft weer waarden.",
        "error_title": "Fout",
        "config": "Configuratie (wifi-wachtwoord verborgen):",
        "mac_read": "Apparaat meldt wifi-MAC: {mac}",
        "mac_match": "  komt overeen met de waarde berekend uit het Bluetooth-adres.",
        "mac_differs": "  wijkt af van de berekende {calc}; de waarde van het apparaat wordt gebruikt.",
        "mac_none": "Het apparaat antwoordde niet. Vul het wifi-MAC in (Bluetooth-MAC min 2).",
        "bt_error": "Bluetooth-fout: {error}",
        "bt_error_hint": "Probeer het opnieuw: zet de monitor weer in koppelmodus (groot wifi-icoon), houd hem dichtbij "
                         "en zet zo nodig Bluetooth uit en weer aan.",
        "technical": "technisch: {error}",
        "bt_label": "Bluetooth:",
        "bt_on": "aan", "bt_off": "uit", "bt_disabled": "uitgeschakeld", "bt_none": "geen adapter",
        "bt_no_le": "geen Bluetooth LE",
        "err_bt_none": "Deze computer heeft geen (werkende) Bluetooth-adapter.\n\n"
                       "Gebruik een andere computer met Bluetooth, of sluit een USB-Bluetooth-adapter aan "
                       "(Bluetooth 4.0 / LE of nieuwer). Heeft de computer wel Bluetooth, kijk dan of de adapter niet "
                       "is uitgeschakeld in Apparaatbeheer.",
        "err_bt_no_le": "De Bluetooth-adapter van deze computer ondersteunt geen Bluetooth Low Energy, en dat heeft de "
                        "monitor nodig.\n\nGebruik een andere computer of een USB-Bluetooth-adapter "
                        "(Bluetooth 4.0 / LE of nieuwer).",
        "err_bt_off": "Bluetooth staat uit.\n\nZet het aan via Instellingen → Bluetooth en apparaten (of Win+A, "
                      "snelle instellingen), wacht een paar seconden en klik opnieuw op Zoeken.",
        "err_bt_disabled": "Bluetooth is uitgeschakeld: de vliegtuigstand staat aan, of de adapter is uitgeschakeld in "
                           "Apparaatbeheer.\n\nZet de vliegtuigstand uit (Win+A), zet Bluetooth aan en klik opnieuw "
                           "op Zoeken.",
        "err_bt_denied": "Windows staat dit programma niet toe Bluetooth te gebruiken.\n\nControleer Instellingen → "
                         "Privacy en beveiliging, of start het programma als de ingelogde gebruiker (niet via een "
                         "ander account).",
        "err_device_gone": "De monitor is via Bluetooth niet meer te vinden.\n\nWaarschijnlijk is de koppelmodus "
                           "gestopt: houd de balk bovenop 8 seconden ingedrukt tot het grote wifi-icoon verschijnt, "
                           "klik op Zoeken en probeer het opnieuw.",
        "err_connect": "Verbinden met de monitor lukt niet (geen antwoord).\n\nHoud hem binnen ongeveer 2 meter, sluit "
                       "de Qingping+-app op je telefoon, zet de monitor opnieuw in koppelmodus en probeer het nog eens.",
        "busy": "Bezig…",
        "ready": "Gereed",
    },
}


def detect_language(override: str | None = None) -> str:
    if override in TEXTS:
        return override  # type: ignore[return-value]
    candidates = [os.environ.get("LANG", "")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            candidates.append(locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), ""))
        except Exception:  # noqa: BLE001
            pass
    return "nl" if any(c.lower().startswith(("nl", "dutch")) for c in candidates) else "en"


# --------------------------------------------------------------- settings
# The MQTT password is remembered on purpose (it travels in plain text to the device anyway);
# the Wi-Fi password never is.
SETTING_KEYS = ("ssid", "host", "port", "user", "mqtt_password", "prefix", "lang")


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / APP_NAME / "settings.json"


def load_settings(path: Path | None = None) -> dict[str, str]:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items() if k in SETTING_KEYS}


def save_settings(values: dict[str, Any], path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: str(values[k]) for k in SETTING_KEYS if k in values}
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")


# ------------------------------------------------------------ pure logic
def build_config(values: dict[str, str]) -> Any:
    """ProvisionConfig from form values (raises bp.ProvisioningError / ValueError)."""
    wifi_mac = (values.get("wifi_mac") or "").strip()
    if not wifi_mac:
        address = (values.get("address") or "").strip()
        if not cli._is_mac(address):
            raise bp.ProvisioningError("Wi-Fi MAC unknown")
        wifi_mac = bp.wifi_mac_from_ble(address)
    try:
        port = int(str(values.get("port", "1883")).strip())
    except ValueError as err:
        raise bp.ProvisioningError("MQTT port must be a number") from err
    config = bp.ProvisionConfig.for_wifi_mac(
        wifi_mac,
        wifi_ssid=values.get("ssid", ""),
        wifi_password=values.get("wifi_password", ""),
        mqtt_host=(values.get("host") or "").strip(),
        mqtt_port=port,
        mqtt_username=(values.get("user") or "").strip(),
        mqtt_password=values.get("mqtt_password", ""),
        prefix=(values.get("prefix") or bp.DEFAULT_PREFIX).strip(),
    )
    config.validate()
    return config


REQUIRED_FIELDS = ("ssid", "host", "port", "user", "mqtt_password")  # the Wi-Fi password may be empty (open network)
PROVISION_STEPS = 6  # progress callbacks of bp.provision: wifi, token, token, mqtt, topics, done


def missing_fields(values: dict[str, str]) -> list[str]:
    """Required form fields that are still empty (keys of REQUIRED_FIELDS, in order)."""
    return [key for key in REQUIRED_FIELDS if not str(values.get(key, "")).strip()]


def scan_rows(found: dict[str, tuple[Any, Any]]) -> list[tuple[str, str, int, str]]:
    """(name, address, rssi, wifi_mac) for Qingping devices, strongest first."""
    rows = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        if name.startswith("Qingping"):
            wifi = bp.wifi_mac_from_ble(device.address) if cli._is_mac(device.address) else ""
            rows.append((name, device.address, int(adv.rssi), wifi))
    return sorted(rows, key=lambda r: -r[2])


SCAN_SECONDS = 8.0
RADIO_PROBLEMS = ("off", "disabled", "none", "no_le")  # radio states that make scanning pointless


class BluetoothUnavailable(Exception):
    """Raised before a Bluetooth action when the radio check already says it cannot work."""

    def __init__(self, state: str) -> None:
        super().__init__(f"Bluetooth radio state: {state}")
        self.state = state


def classify_error(err: BaseException, radio: str | None = None) -> str:
    """Text key (``err_*``) for a known Bluetooth problem, or "" for anything else.

    Works on names and messages only, so it copes with bleak versions before and
    after ``BleakBluetoothNotAvailableError`` (bleak 2.0) and needs no bleak import.
    """
    if isinstance(err, BluetoothUnavailable):
        return {"off": "err_bt_off", "disabled": "err_bt_disabled", "none": "err_bt_none",
                "no_le": "err_bt_no_le"}.get(err.state, "")
    reason = getattr(getattr(err, "reason", None), "name", "") if type(err).__name__.startswith("Bleak") else ""
    text = f"{type(err).__name__}: {err}".lower()
    if reason == "NO_BLUETOOTH" or "no bluetooth adapter" in text:
        return "err_bt_none"
    if reason == "NO_BLE_CENTRAL_ROLE" or "central' role" in text:
        return "err_bt_no_le"
    if (reason == "POWERED_OFF" or "not powered on" in text or "device is not ready" in text
            or "-2147020577" in text or "0x800710df" in text):
        return "err_bt_disabled" if radio == "disabled" else "err_bt_off"
    if reason.startswith("DENIED"):
        return "err_bt_denied"
    if isinstance(err, bp.ProvisioningError):
        return "err_device_gone" if "not found" in text else ""
    if isinstance(err, (TimeoutError, asyncio.TimeoutError)) or any(
            word in text for word in ("timeout", "timed out", "unreachable", "not connected", "disconnected")):
        return "err_connect"
    return ""


async def radio_state() -> str:
    """'on', 'off', 'disabled', 'none', 'no_le' or 'unknown' (non-Windows, or WinRT not available)."""
    if sys.platform != "win32":
        return "unknown"
    try:
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        from winrt.windows.devices.radios import RadioState
    except ImportError:
        return "unknown"
    try:
        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            return "none"
        if not (adapter.is_low_energy_supported and adapter.is_central_role_supported):
            return "no_le"
        radio = await adapter.get_radio_async()
        if radio is None:
            return "unknown"
        return {RadioState.ON: "on", RadioState.OFF: "off", RadioState.DISABLED: "disabled"}.get(radio.state, "unknown")
    except Exception:  # noqa: BLE001 - the check is advisory; bleak reports the real error
        return "unknown"


async def ensure_bluetooth() -> str:
    state = await radio_state()
    if state in RADIO_PROBLEMS:
        raise BluetoothUnavailable(state)
    return state


# ------------------------------------------------------- raw Bluetooth log
RawSink = Callable[[str], None]

PACKET_NAMES = {
    (0x000D, bp.PKT_WIFI): "Wi-Fi", (0x0001, bp.PKT_TOKEN_A): "token A", (0x0001, bp.PKT_TOKEN_B): "token B",
    (0x0001, bp.PKT_MQTT): "MQTT", (0x0001, bp.PKT_TOPICS): "topics",
    (0x0017, bp.PKT_WIFI_MAC): "Wi-Fi MAC?", (0x0018, bp.PKT_WIFI_MAC): "Wi-Fi MAC",
}


def short_uuid(uuid: str) -> int | None:
    """16-bit UUID of a Bluetooth-base UUID, else None."""
    uuid = str(uuid).lower()
    if uuid.endswith("-0000-1000-8000-00805f9b34fb") and len(uuid) == 36:
        return int(uuid[4:8], 16)
    return None


def _uuid_label(uuid: str) -> str:
    short = short_uuid(uuid)
    return f"0x{short:04X}" if short is not None else str(uuid)


def _secret_mask(data: bytes, secrets: list[bytes]) -> list[bool]:
    mask = [False] * len(data)
    for secret in secrets:
        if not secret:
            continue
        start = data.find(secret)
        while start != -1:
            for i in range(start, start + len(secret)):
                mask[i] = True
            start = data.find(secret, start + 1)
    return mask


def format_bytes(data: bytes, secrets: list[bytes] | None = None) -> str:
    """'hex | ascii', with the bytes of any secret shown as ●● / ●."""
    mask = _secret_mask(data, secrets or [])
    hexpart = " ".join("●●" if m else f"{b:02X}" for b, m in zip(data, mask))
    text = "".join("●" if m else (chr(b) if 32 <= b < 127 else ".") for b, m in zip(data, mask))
    return f"{hexpart}  |{text}|"


def describe_packet(direction: str, uuid: str, packet: bytes, secrets: list[bytes] | None = None) -> str:
    """One line for a complete ``<len><type><data>`` packet."""
    short = short_uuid(uuid)
    ptype = packet[1] if len(packet) > 1 else None
    name = PACKET_NAMES.get((short, ptype), "") if short is not None else ""
    head = f"{direction} {_uuid_label(uuid)} type 0x{ptype:02X}" if ptype is not None else f"{direction} {_uuid_label(uuid)}"
    if name:
        head += f" ({name})"
    return f"{head}, {len(packet)} B: {format_bytes(packet, secrets)}"


def describe_advertisement(device: Any, adv: Any) -> str:
    name = adv.local_name or device.name or "?"
    parts = [f"{device.address}  {adv.rssi:>4} dBm  {name}"]
    if getattr(adv, "service_uuids", None):
        parts.append("services=" + ",".join(_uuid_label(u) for u in adv.service_uuids))
    for company, data in (getattr(adv, "manufacturer_data", None) or {}).items():
        parts.append(f"mfr 0x{company:04X}={bytes(data).hex(' ').upper()}")
    for uuid, data in (getattr(adv, "service_data", None) or {}).items():
        parts.append(f"svc {_uuid_label(uuid)}={bytes(data).hex(' ').upper()}")
    return "  ".join(parts)


class RawLogClient:
    """Wraps a BleakClient: logs every GATT write (reassembled into packets) and notification."""

    def __init__(self, client: Any, sink: RawSink, secrets: list[bytes] | None = None) -> None:
        self._client, self._sink, self._secrets = client, sink, secrets or []
        self._pending: dict[str, bytearray] = {}

    def __getattr__(self, name: str) -> Any:  # services, disconnect, address, …
        return getattr(self._client, name)

    async def write_gatt_char(self, char: Any, data: Any, response: bool = False) -> Any:
        uuid = getattr(char, "uuid", str(char))
        buf = self._pending.setdefault(uuid, bytearray())
        buf.extend(bytes(data))
        while buf and len(buf) >= buf[0] + 1:
            packet = bytes(buf[: buf[0] + 1])
            del buf[: buf[0] + 1]
            mode = "with response" if response else "without response"
            self._sink(describe_packet("→", uuid, packet, self._secrets) + f"  [{mode}]")
        return await self._client.write_gatt_char(char, data, response=response)

    async def start_notify(self, char: Any, callback: Callable[..., Any], **kwargs: Any) -> Any:
        uuid = getattr(char, "uuid", str(char))
        self._sink(f"  subscribe {_uuid_label(uuid)}")

        def _logged(sender: Any, data: bytearray) -> Any:
            self._sink(describe_packet("←", uuid, bytes(data), self._secrets))
            return callback(sender, data)

        return await self._client.start_notify(char, _logged, **kwargs)

    async def stop_notify(self, char: Any) -> Any:
        self._sink(f"  unsubscribe {_uuid_label(getattr(char, 'uuid', str(char)))}")
        return await self._client.stop_notify(char)


def describe_services(client: Any) -> list[str]:
    lines = []
    try:
        services = list(client.services)
    except Exception:  # noqa: BLE001
        return lines
    for service in services:
        lines.append(f"  service {service.uuid}")
        for char in service.characteristics:
            lines.append(f"    {_uuid_label(char.uuid):<8} {','.join(char.properties)}")
    return lines


def config_secrets(config: Any) -> list[bytes]:
    return [s for s in (config.wifi_password.encode(), config.link_token) if s]


# ------------------------------------------------------------- BLE worker
class BleWorker:
    """Runs coroutines on a private asyncio loop in a daemon thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


def _no_raw(_line: str) -> None:
    pass


async def ble_scan(timeout: float = SCAN_SECONDS, raw: RawSink = _no_raw) -> tuple[list[tuple[str, str, int, str]], int]:
    """(Qingping rows, number of Bluetooth devices seen in total)."""
    from bleak import BleakScanner

    raw(f"radio: {await ensure_bluetooth()}")
    raw(f"scan {timeout:.0f} s…")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for device, adv in sorted(found.values(), key=lambda item: -item[1].rssi):
        raw("  " + describe_advertisement(device, adv))
    raw(f"scan done: {len(found)} device(s)")
    return scan_rows(found), len(found)


async def _raw_connect(address: str, raw: RawSink, secrets: list[bytes] | None = None) -> Any:
    raw(f"connect {address}…")
    client = await cli._connect(address, 20.0)
    raw(f"connected, MTU {getattr(client, 'mtu_size', '?')}")
    for line in describe_services(client):
        raw(line)
    return RawLogClient(client, raw, secrets)


async def _raw_disconnect(client: Any, raw: RawSink) -> None:
    try:
        await client.disconnect()
    finally:
        raw("disconnected")


async def ble_read_wifi_mac(address: str, raw: RawSink = _no_raw) -> str | None:
    raw(f"radio: {await ensure_bluetooth()}")
    client = await _raw_connect(address, raw)
    try:
        return await bp.read_wifi_mac(client)
    finally:
        await _raw_disconnect(client, raw)


async def ble_provision(address: str, config: Any, progress: Callable[[str], None],
                        raw: RawSink = _no_raw, show_secrets: bool = False) -> None:
    raw(f"radio: {await ensure_bluetooth()}")
    client = await _raw_connect(address, raw, [] if show_secrets else config_secrets(config))
    try:
        await bp.provision(client, config, progress=progress)
    finally:
        await _raw_disconnect(client, raw)


# -------------------------------------------------------------------- GUI
def _enable_dpi_awareness() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor, sharp on Windows 11
        except Exception:  # noqa: BLE001
            pass


class Tooltip:
    """Small hover tip for a widget."""

    def __init__(self, widget, text: str) -> None:
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        import tkinter as tk

        if self.tip:
            return
        x = self.widget.winfo_rootx() - 240
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{max(x, 0)}+{y}")
        tk.Label(self.tip, text=self.text, wraplength=320, justify="left", background="#ffffe1",
                 relief="solid", borderwidth=1, padx=6, pady=4).pack()

    def _hide(self, _event=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, lang: str) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk, self.ttk, self.messagebox = tk, ttk, messagebox
        self.lang = lang
        self.t = TEXTS[lang]
        self.worker = BleWorker()
        self.events: queue.Queue[tuple[Callable[..., None], tuple]] = queue.Queue()

        self.root = tk.Tk()
        self.root.title(self.t["title"])
        self.root.minsize(760, 640)
        self._set_icon()
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Step.TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        saved = load_settings()
        self.vars = {
            "wifi_mac": tk.StringVar(), "ssid": tk.StringVar(value=saved.get("ssid", "")),
            "wifi_password": tk.StringVar(), "host": tk.StringVar(value=saved.get("host", "")),
            "port": tk.StringVar(value=saved.get("port", "1883")),
            "user": tk.StringVar(value=saved.get("user", "qingping")),
            "mqtt_password": tk.StringVar(value=saved.get("mqtt_password", "")), "prefix": tk.StringVar(value=saved.get("prefix", bp.DEFAULT_PREFIX)),
        }
        self.status = tk.StringVar(value=self.t["ready"])
        self.lang_var = tk.StringVar(value=lang)
        self.raw_secrets = tk.BooleanVar(value=False)
        self._logo = self._load_logo()
        self.radio = "unknown"
        self._is_busy = False
        self._radio_pending = False
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._pump)
        self.root.after(300, self._poll_radio)

    # -- layout --------------------------------------------------------
    def _build(self) -> None:
        tk, ttk, t = self.tk, self.ttk, self.t
        outer = self.outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        # step 1
        s1 = ttk.LabelFrame(outer, text=t["step1"], padding=10, style="Step.TLabelframe")
        s1.grid(row=0, column=0, sticky="nsew")
        s1.columnconfigure(0, weight=1)
        head = ttk.Frame(s1)
        head.grid(row=0, column=0, columnspan=4, sticky="ew")
        head.columnconfigure(1, weight=1)
        if self._logo is not None:
            ttk.Label(head, image=self._logo).grid(row=0, column=0, sticky="nw", padx=(0, 12))
        ttk.Label(head, text=t["step1_help"], justify="left").grid(row=0, column=1, sticky="w")
        langs = ttk.Frame(head)
        langs.grid(row=0, column=2, sticky="ne")
        for code, label in (("nl", "NL"), ("en", "EN")):
            ttk.Radiobutton(langs, text=label, value=code, variable=self.lang_var, style="Toolbutton", width=4,
                            command=lambda: self.set_language(self.lang_var.get())).pack(side="left", padx=(2, 0))
        cols = ("name", "address", "rssi", "wifi")
        self.tree = ttk.Treeview(s1, columns=cols, show="headings", height=4, selectmode="browse")
        for col, key, width in zip(cols, ("col_name", "col_address", "col_rssi", "col_wifi"), (220, 260, 70, 150)):
            self.tree.heading(col, text=t[key])
            self.tree.column(col, width=width, stretch=col in ("name", "address"))
        self.tree.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=(8, 6))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        left = ttk.Frame(s1)
        left.grid(row=2, column=0, sticky="w")
        self.scan_btn = ttk.Button(left, text=t["scan"], command=self.scan)
        self.scan_btn.pack(side="left")
        self.bt_label = ttk.Label(left, text="")
        self.bt_label.pack(side="left", padx=(12, 0))
        ttk.Label(s1, text=t["wifi_mac"]).grid(row=2, column=1, sticky="e", padx=(12, 4))
        ttk.Entry(s1, textvariable=self.vars["wifi_mac"], width=16).grid(row=2, column=2, sticky="w")
        self.read_btn = ttk.Button(s1, text=t["read_mac"], command=self.read_mac)
        self.read_btn.grid(row=2, column=3, sticky="w", padx=(6, 0))
        Tooltip(self.read_btn, t["read_mac_tip"])

        # step 2: Wi-Fi + broker, one required block
        s2 = ttk.LabelFrame(outer, text=t["step2"], padding=10, style="Step.TLabelframe")
        s2.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        s2.columnconfigure((0, 1), weight=1)
        ttk.Label(s2, text=t["step2_help"], wraplength=700, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        wifi = ttk.LabelFrame(s2, text=t["wifi_box"], padding=8)
        wifi.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        mqtt = ttk.LabelFrame(s2, text=t["mqtt_box"], padding=8)
        mqtt.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        self._row(wifi, 0, t["ssid"] + " *", self.vars["ssid"], width=18)
        self.wifi_entry = self._row(wifi, 1, t["wifi_password"], self.vars["wifi_password"], secret=True, width=18)
        self._row(mqtt, 0, t["host"] + " *", self.vars["host"], width=15)
        self._row(mqtt, 1, t["port"] + " *", self.vars["port"], width=8)
        self._row(mqtt, 2, t["user"] + " *", self.vars["user"], width=15)
        self.mqtt_entry = self._row(mqtt, 3, t["mqtt_password"] + " *", self.vars["mqtt_password"], width=15)
        self._row(mqtt, 4, t["prefix"], self.vars["prefix"], width=12)

        # actions
        bar = ttk.Frame(outer)
        bar.grid(row=3, column=0, sticky="ew", pady=(12, 6))
        bar.columnconfigure(1, weight=1)
        self.check_btn = ttk.Button(bar, text=t["check"], command=self.check)
        self.check_btn.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=PROVISION_STEPS)
        self.progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.go_btn = ttk.Button(bar, text=t["provision"], command=self.provision, style="Accent.TButton")
        self.go_btn.grid(row=0, column=2, sticky="e")

        # log
        logf = ttk.Frame(outer)
        logf.grid(row=4, column=0, sticky="nsew")
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        self.notebook = ttk.Notebook(logf)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.log_text = self._text_tab(t["log"], wrap="word")
        self.raw_text = self._text_tab(t["raw"], wrap="none")
        tools = ttk.Frame(logf)
        tools.grid(row=1, column=0, sticky="e", pady=(4, 0))
        ttk.Checkbutton(tools, text=t["raw_secrets"], variable=self.raw_secrets).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text=t["copy"], command=self.copy_tab, width=10).pack(side="left", padx=(0, 4))
        ttk.Button(tools, text=t["clear"], command=self.clear_tab, width=10).pack(side="left")
        ttk.Label(outer, textvariable=self.status, anchor="w").grid(row=5, column=0, sticky="ew", pady=(4, 0))

    def _row(self, parent, row: int, label: str, var, secret: bool = False, width: int = 40):
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var, width=width, show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="w", pady=3)
        if secret:
            shown = self.tk.BooleanVar(value=False)
            ttk.Checkbutton(parent, text=self.t["show"], variable=shown,
                            command=lambda: entry.configure(show="" if shown.get() else "•")
                            ).grid(row=row, column=2, sticky="w", padx=8)
        return entry

    def _set_icon(self) -> None:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        ico = base / "app.ico"
        if sys.platform == "win32" and ico.is_file():
            try:
                self.root.iconbitmap(default=str(ico))
            except Exception:  # noqa: BLE001
                pass

    def _load_logo(self):
        """Integration logo (64 px) for the top left of step 1, or None."""
        here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        candidates = [(here / "logo.png", 1)]
        if len(here.parents) > 1:
            candidates.append((here.parents[1] / "custom_components" / "qingping_cgdn1" / "brand" / "icon.png", 4))
        for path, shrink in candidates:
            if path.is_file():
                try:
                    image = self.tk.PhotoImage(master=self.root, file=str(path))
                    return image.subsample(shrink) if shrink > 1 else image
                except Exception:  # noqa: BLE001
                    pass
        return None

    def set_language(self, lang: str) -> None:
        """Switch NL/EN: rebuild the window, keeping input, scan results and logs."""
        if lang == self.lang or lang not in TEXTS:
            return
        if self._is_busy:
            self.lang_var.set(self.lang)
            return
        rows = [self.tree.item(i, "values") for i in self.tree.get_children()]
        selected = self.tree.index(self.tree.selection()[0]) if self.tree.selection() else None
        logs = (self.log_text.get("1.0", "end-1c"), self.raw_text.get("1.0", "end-1c"))
        tab = self.notebook.index("current")
        progress = self.progress.cget("value")
        self.lang, self.t = lang, TEXTS[lang]
        self.root.title(self.t["title"])
        self.status.set(self.t["ready"])
        self.outer.destroy()
        self._build()
        for values in rows:
            self.tree.insert("", "end", values=values)
        if selected is not None:
            self.tree.selection_set(self.tree.get_children()[selected])
        for widget, text in zip((self.log_text, self.raw_text), logs):
            if text:
                self._append(widget, text)
        self.notebook.select(tab)
        self.progress.configure(value=progress)
        self._show_radio(self.radio)
        try:
            save_settings({**load_settings(), "lang": lang})
        except OSError:
            pass

    # -- helpers -------------------------------------------------------
    def _text_tab(self, title: str, wrap: str):
        tk, ttk = self.tk, self.ttk
        frame = ttk.Frame(self.notebook, padding=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, height=8, wrap=wrap, state="disabled", font=("Consolas", 9), relief="flat")
        text.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        ys.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=ys.set)
        if wrap == "none":
            xs = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
            xs.grid(row=1, column=0, sticky="ew")
            text.configure(xscrollcommand=xs.set)
        self.notebook.add(frame, text=title)
        return text

    @staticmethod
    def _append(widget, text: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", text + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def log(self, text: str) -> None:
        self._append(self.log_text, text)

    def raw_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        self._append(self.raw_text, f"{stamp}  {text}")

    def _raw_sink(self, text: str) -> None:
        """Thread-safe raw logger for the BLE worker."""
        self._post(self.raw_log, text)

    def _current_text(self):
        return self.raw_text if self.notebook.index("current") == 1 else self.log_text

    def clear_tab(self) -> None:
        widget = self._current_text()
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    def copy_tab(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._current_text().get("1.0", "end-1c"))

    def _post(self, fn: Callable[..., None], *args: Any) -> None:
        """Thread-safe: run fn(*args) on the Tk thread."""
        self.events.put((fn, args))

    def _pump(self) -> None:
        try:
            while True:
                fn, args = self.events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _busy(self, busy: bool) -> None:
        self._is_busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self.scan_btn, self.read_btn, self.check_btn, self.go_btn):
            btn.configure(state=state)
        self.status.set(self.t["busy"] if busy else self.t["ready"])
        self.root.configure(cursor="watch" if busy else "")

    def _run(self, coro, on_ok: Callable[[Any], None]) -> None:
        self._busy(True)

        def _done(fut: Future) -> None:
            try:
                result = fut.result()
            except Exception as err:  # noqa: BLE001
                self._post(self._fail, err)
            else:
                self._post(on_ok, result)
            self._post(self._busy, False)

        self.worker.submit(coro).add_done_callback(_done)

    def _fail(self, err: Exception) -> None:
        self.raw_log(f"error: {type(err).__name__}: {err}")
        key = classify_error(err, self.radio)
        if isinstance(err, BluetoothUnavailable):
            self._show_radio(err.state)
        if key:
            text = self.t[key]
            if not isinstance(err, BluetoothUnavailable):
                self.log(self.t["technical"].format(error=f"{type(err).__name__}: {err}"))
        elif isinstance(err, bp.ProvisioningError):
            text = str(err)
        else:
            text = self.t["bt_error"].format(error=f"{type(err).__name__}: {err}") + "\n\n" + self.t["bt_error_hint"]
        self.log(text)
        self.messagebox.showerror(self.t["error_title"], text, parent=self.root)

    # -- Bluetooth radio indicator -------------------------------------
    def _poll_radio(self) -> None:
        if not self._is_busy and not self._radio_pending:
            self._radio_pending = True

            def _done(fut: Future) -> None:
                try:
                    state = fut.result()
                except Exception:  # noqa: BLE001
                    state = "unknown"
                self._post(self._show_radio, state)

            self.worker.submit(radio_state()).add_done_callback(_done)
        self.root.after(3000, self._poll_radio)

    def _show_radio(self, state: str) -> None:
        self._radio_pending = False
        self.radio = state
        if state == "unknown":
            self.bt_label.configure(text="")
            return
        colour = "#107c10" if state == "on" else "#c42b1c"
        self.bt_label.configure(text=f"{self.t['bt_label']} {self.t['bt_' + state]}", foreground=colour)

    def _values(self) -> dict[str, str]:
        values = {k: v.get() for k, v in self.vars.items()}
        values["address"] = self._selected_address() or ""
        return values

    def _selected_address(self) -> str | None:
        sel = self.tree.selection()
        return self.tree.set(sel[0], "address") if sel else None

    # -- actions -------------------------------------------------------
    def _on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel:
            wifi = self.tree.set(sel[0], "wifi")
            if wifi:
                self.vars["wifi_mac"].set(wifi)

    def scan(self) -> None:
        self.log(self.t["scanning"])
        self.tree.delete(*self.tree.get_children())
        self._run(ble_scan(raw=self._raw_sink), self._scanned)

    def _scanned(self, result) -> None:
        rows, seen = result
        self._show_radio("on" if self.radio in ("unknown", "on") else self.radio)
        for name, address, rssi, wifi in rows:
            self.tree.insert("", "end", values=(name, address, f"{rssi} dBm", wifi))
        if not rows:
            text = (self.t["none_found"].format(n=seen) if seen
                    else self.t["none_seen"].format(s=f"{SCAN_SECONDS:.0f}"))
            self.log(text)
            self.messagebox.showwarning(self.t["none_title"], text, parent=self.root)
            return
        self.log(self.t["found"].format(n=len(rows)))
        first = self.tree.get_children()[0]
        self.tree.selection_set(first)
        self._on_select()
        if not self.tree.set(first, "wifi"):  # macOS: address is a UUID, so ask the device
            self.root.after(100, self.read_mac)

    def read_mac(self) -> None:
        address = self._selected_address()
        if not address:
            self.messagebox.showinfo(self.t["title"], self.t["no_device"], parent=self.root)
            return
        self.log(self.t["connecting"].format(address=address))
        self._run(ble_read_wifi_mac(address, raw=self._raw_sink), self._mac_read)

    def _mac_read(self, mac: str | None) -> None:
        if mac:
            address = self._selected_address() or ""
            calc = bp.wifi_mac_from_ble(address) if cli._is_mac(address) else ""
            self.vars["wifi_mac"].set(mac)
            self.log(self.t["mac_read"].format(mac=mac))
            if calc:
                self.log(self.t["mac_match"] if calc == mac else self.t["mac_differs"].format(calc=calc))
        else:
            self.log(self.t["mac_none"])

    def check(self) -> Any:
        values = self._values()
        missing = missing_fields(values)
        if missing:
            labels = {"ssid": self.t["ssid"], "host": self.t["host"], "port": self.t["port"],
                      "user": self.t["user"], "mqtt_password": f"{self.t['mqtt_box']}: {self.t['mqtt_password']}"}
            text = self.t["missing"].format(fields=", ".join(labels[k] for k in missing))
            self.log(text)
            self.messagebox.showwarning(self.t["error_title"], text, parent=self.root)
            return None
        try:
            config = build_config(values)
        except (bp.ProvisioningError, ValueError) as err:
            self._fail(err)
            return None
        self.log(self.t["config"])
        for key, value in config.redacted().items():
            self.log(f"  {key:<14} {value}")
            if key == "mqtt_username":
                self.log(f"  {'mqtt_password':<14} {config.mqtt_password}")
        return config

    def provision(self) -> None:
        address = self._selected_address()
        if not address:
            self.messagebox.showinfo(self.t["title"], self.t["no_device"], parent=self.root)
            return
        config = self.check()
        if config is None:
            return
        if not config.wifi_password and not self.messagebox.askyesno(
                self.t["open_wifi_title"], self.t["open_wifi_ask"], icon="warning", parent=self.root):
            return
        save_settings({**{k: v.get() for k, v in self.vars.items() if k in SETTING_KEYS}, "lang": self.lang})
        self.progress.configure(value=0)
        self.log(self.t["connecting"].format(address=address))
        names = dict(item.split("=", 1) for item in self.t["step_names"].split("|"))

        def progress(step: str) -> None:
            text = self.t["sent_all"] if step == "done" else self.t["step"].format(step=names.get(step, step))
            self._post(self.log, text)
            self._post(self.progress.step, 1)

        def ok(_result) -> None:
            self.progress.configure(value=PROVISION_STEPS)
            msg = self.t["done"].format(ssid=config.wifi_ssid, topic=config.topic_write,
                                        client_id=config.client_id, user=config.mqtt_username)
            self.log(msg)
            self.vars["wifi_password"].set("")
            self.messagebox.showinfo(self.t["done_title"], msg, parent=self.root)

        self._run(ble_provision(address, config, progress, raw=self._raw_sink,
                                show_secrets=self.raw_secrets.get()), ok)

    def close(self) -> None:
        self.worker.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qingping CGDN1 Bluetooth setup (GUI)")
    parser.add_argument("--lang", choices=sorted(TEXTS), help="force language")
    parser.add_argument("--selftest", action="store_true",
                        help="build the window, validate a sample config, close (CI smoke test)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    _enable_dpi_awareness()
    app = App(detect_language(args.lang or load_settings().get("lang")))
    if args.selftest:
        import bleak  # noqa: F401  - fails the test if bleak is not bundled

        sample = {"address": "7C:C2:94:00:BE:F1", "ssid": "Example", "wifi_password": "w",
                  "host": "192.0.2.10", "port": "1883", "user": "qingping", "mqtt_password": "m"}
        assert build_config(sample).topic_write == "qingping/7CC29400BEEF/up"
        app.root.after(800, app.close)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
