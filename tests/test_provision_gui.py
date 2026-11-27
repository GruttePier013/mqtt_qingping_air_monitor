"""GUI helpers of tools/qingping-provision (no Tk needed; the window itself is smoke-tested on Windows CI)."""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_DIR = Path(__file__).parents[1] / "tools" / "qingping-provision"
sys.path.insert(0, str(_DIR))
_spec = importlib.util.spec_from_file_location("qingping_provision_gui", _DIR / "qingping_provision_gui.py")
gui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gui)

FORM = {"address": "7C:C2:94:00:BE:F1", "ssid": "Example Net", "wifi_password": "w",
        "host": " 192.0.2.10 ", "port": "1883", "user": "qingping", "mqtt_password": "m", "prefix": ""}


def test_build_config_from_form():
    cfg = gui.build_config(FORM)
    assert cfg.topic_write == "qingping/7CC29400BEEF/up"
    assert cfg.mqtt_host == "192.0.2.10" and cfg.mqtt_port == 1883


def test_build_config_wifi_mac_override_and_errors():
    cfg = gui.build_config({**FORM, "address": "1F2E-UUID", "wifi_mac": "7CC2940000AA"})
    assert cfg.client_id == "qingping-7CC2940000AA"
    with pytest.raises(gui.bp.ProvisioningError):
        gui.build_config({**FORM, "address": "1F2E-UUID"})         # macOS UUID, no Wi-Fi MAC
    with pytest.raises(gui.bp.ProvisioningError):
        gui.build_config({**FORM, "port": "abc"})
    with pytest.raises(gui.bp.ProvisioningError):
        gui.build_config({**FORM, "mqtt_password": "two words"})


def test_settings_keep_mqtt_password_never_wifi_password(tmp_path):
    path = tmp_path / "settings.json"
    gui.save_settings({**FORM, "port": 1884, "lang": "en"}, path)
    stored = json.loads(path.read_text())
    assert set(stored) <= set(gui.SETTING_KEYS)
    assert "wifi_password" not in stored
    assert stored["mqtt_password"] == "m" and stored["lang"] == "en"
    assert gui.load_settings(path)["port"] == "1884"
    assert gui.load_settings(tmp_path / "missing.json") == {}


def test_scan_rows_filters_and_sorts():
    def dev(addr, name, rssi):
        return SimpleNamespace(address=addr, name=name), SimpleNamespace(local_name=name, rssi=rssi)

    found = {"a": dev("7C:C2:94:00:BE:F1", "Qingping Air Monitor Lite", -70),
             "b": dev("11:22:33:44:55:66", "Other", -40),
             "c": dev("7C:C2:94:00:00:03", "Qingping Air Monitor Lite", -50)}
    rows = gui.scan_rows(found)
    assert [r[1] for r in rows] == ["7C:C2:94:00:00:03", "7C:C2:94:00:BE:F1"]
    assert rows[1][3] == "7CC29400BEEF"


def test_language_and_texts_complete(monkeypatch):
    assert gui.detect_language("nl") == "nl" and gui.detect_language("en") == "en"
    monkeypatch.setenv("LANG", "nl_NL.UTF-8")
    assert gui.detect_language() == "nl"
    assert set(gui.TEXTS["nl"]) == set(gui.TEXTS["en"])


def test_ble_worker_runs_coroutines():
    worker = gui.BleWorker()

    async def answer():
        await asyncio.sleep(0)
        return 42

    try:
        assert worker.submit(answer()).result(timeout=2) == 42
    finally:
        worker.stop()


def test_wifi_and_broker_required():
    assert gui.missing_fields(FORM) == []
    assert gui.missing_fields({**FORM, "ssid": " ", "host": "", "mqtt_password": ""}) == ["ssid", "host", "mqtt_password"]
    assert gui.missing_fields({**FORM, "wifi_password": ""}) == []          # open network: confirmed in the GUI
    with pytest.raises(gui.bp.ProvisioningError, match="SSID"):
        gui.build_config({**FORM, "ssid": ""})
    assert gui.PROVISION_STEPS == 6


def test_done_text_asks_to_verify():
    for lang in ("nl", "en"):
        text = gui.TEXTS[lang]["done"].format(ssid="Net", topic="qingping/X/up", client_id="qingping-X", user="u")
        assert "qingping-X" in text and "not authorised" in text and "qingping/X/up" in text
        names = dict(item.split("=", 1) for item in gui.TEXTS[lang]["step_names"].split("|"))
        assert set(names) == {"wifi", "token", "mqtt", "topics"}


class BleakBluetoothNotAvailableError(Exception):
    """Stand-in with the same name and ``reason`` shape as bleak >= 2.0."""

    def __init__(self, msg, reason_name):
        super().__init__(msg)
        self.reason = SimpleNamespace(name=reason_name)


class BleakError(Exception):
    pass


@pytest.mark.parametrize(("err", "radio", "key"), [
    (BleakBluetoothNotAvailableError("No Bluetooth adapter found", "NO_BLUETOOTH"), None, "err_bt_none"),
    (BleakBluetoothNotAvailableError("central", "NO_BLE_CENTRAL_ROLE"), None, "err_bt_no_le"),
    (BleakBluetoothNotAvailableError("Bluetooth radio is not powered on.", "POWERED_OFF"), None, "err_bt_off"),
    (BleakBluetoothNotAvailableError("Bluetooth radio is not powered on.", "POWERED_OFF"), "disabled", "err_bt_disabled"),
    (BleakBluetoothNotAvailableError("denied", "DENIED_BY_USER"), None, "err_bt_denied"),
    (BleakError("No Bluetooth adapters found."), None, "err_bt_none"),                    # bleak < 2.0
    (OSError("[WinError -2147020577] The device is not ready for use"), None, "err_bt_off"),
    (gui.BluetoothUnavailable("none"), None, "err_bt_none"),
    (gui.BluetoothUnavailable("disabled"), None, "err_bt_disabled"),
    (gui.bp.ProvisioningError("7C:C2:94:00:BE:F1 not found: in pairing mode and within range?"), None,
     "err_device_gone"),
    (TimeoutError(), None, "err_connect"),
    (BleakError("Could not get GATT services: Unreachable"), None, "err_connect"),
    (gui.bp.ProvisioningError("Wi-Fi SSID is empty"), None, ""),
    (ValueError("something else"), None, ""),
])
def test_classify_error(err, radio, key):
    assert gui.classify_error(err, radio) == key
    if key:
        assert key in gui.TEXTS["nl"] and key in gui.TEXTS["en"]


def test_radio_state_off_windows_is_unknown():
    if sys.platform != "win32":
        assert asyncio.run(gui.radio_state()) == "unknown"
        assert asyncio.run(gui.ensure_bluetooth()) == "unknown"


def test_format_and_describe_packet_mask_secrets():
    cfg = gui.build_config(FORM)
    packet = gui.bp.build_packet(gui.bp.PKT_MQTT, cfg.mqtt_payload())
    line = gui.describe_packet("→", gui.bp.CHAR_CFG_WRITE, packet, gui.config_secrets(cfg))
    assert line.startswith("→ 0x0001 type 0x17 (MQTT)")
    assert "|..192.0.2.10 1883 qingping m|" in line            # MQTT password shown (plain on the wire anyway)
    wifi = gui.describe_packet("→", gui.bp.CHAR_WIFI_WRITE,
                               gui.bp.build_packet(gui.bp.PKT_WIFI, b'"Example Net","secretpw"'), [b"secretpw"])
    assert "secretpw" not in wifi and "●●●●●●●●" in wifi            # Wi-Fi password still masked
    assert gui.format_bytes(b"ab", []) == "61 62  |ab|"
    assert gui.short_uuid(gui.bp.CHAR_INFO_NOTIFY) == 0x18 and gui.short_uuid(gui.bp.SERVICE_UUID) is None


def test_raw_log_client_reassembles_and_logs_notifications():
    lines = []

    class Inner:
        services = "svc"

        def __init__(self):
            self.writes, self.cb = [], None

        async def write_gatt_char(self, char, data, response=False):
            self.writes.append(bytes(data))

        async def start_notify(self, char, cb):
            self.cb = cb

        async def stop_notify(self, char):
            pass

    inner = Inner()
    client = gui.RawLogClient(inner, lines.append, [b"secret"])
    char = SimpleNamespace(uuid=gui.bp.CHAR_WIFI_WRITE)
    packet = gui.bp.build_packet(gui.bp.PKT_WIFI, b'"Example Net","secret"')

    async def run():
        for chunk in gui.bp.chunked(packet):
            await client.write_gatt_char(char, chunk, response=False)
        got = []
        await client.start_notify(SimpleNamespace(uuid=gui.bp.CHAR_INFO_NOTIFY), lambda s, d: got.append(d))
        inner.cb(None, bytearray([7, gui.bp.PKT_WIFI_MAC]) + bytes.fromhex("7CC29400BEEF"))
        return got

    got = asyncio.run(run())
    assert client.services == "svc" and b"".join(inner.writes) == packet
    writes = [ln for ln in lines if ln.startswith("→")]
    assert len(writes) == 1 and "(Wi-Fi)" in writes[0] and "secret" not in writes[0] and "●●●●●●" in writes[0]
    assert any(ln.startswith("← 0x0018 type 0x0B (Wi-Fi MAC)") and "7C C2 94 00 BE EF" in ln for ln in lines)
    assert got and bytes(got[0])[2:] == bytes.fromhex("7CC29400BEEF")
