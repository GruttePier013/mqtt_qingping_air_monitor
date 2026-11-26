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


def test_settings_never_store_passwords(tmp_path):
    path = tmp_path / "settings.json"
    gui.save_settings({**FORM, "port": 1884}, path)
    stored = json.loads(path.read_text())
    assert set(stored) <= set(gui.SETTING_KEYS)
    assert "wifi_password" not in stored and "mqtt_password" not in stored
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
