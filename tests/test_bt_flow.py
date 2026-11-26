"""Config flow: Bluetooth discovery + provisioning (BLE and MQTT mocked)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_BLUETOOTH
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.qingping_cgdn1.ble_provision import ProvisioningError
from custom_components.qingping_cgdn1.const import DOMAIN

FLOW = "custom_components.qingping_cgdn1.config_flow.QingpingConfigFlow"
BLE = SimpleNamespace(address="7C:C2:94:00:BE:F1", name="Qingping Air Monitor Lite")
WIFI_MAC = "7CC29400BEEF"
INPUT = {
    "name": "Woonkamer", "wifi_ssid": "Example", "wifi_password": "wifipass",
    "mqtt_host": "192.0.2.10", "mqtt_port": 1883,
    "mqtt_username": "qingping", "mqtt_password": "mqttpass",
}


async def _start(hass):
    with patch(f"{FLOW}._async_bt_defaults", AsyncMock(return_value={"mqtt_host": "192.0.2.10"})):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=BLE)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bt_setup"
    assert result["description_placeholders"]["mac"] == WIFI_MAC
    return result


async def _run_progress(hass, result):
    """Advance through show_progress steps until a non-progress result.

    HA advances by itself when a progress task finishes; mocked tasks finish
    at once, so the first result may already be final.
    """
    flow_id = result["flow_id"]
    for _ in range(6):
        if result["type"] not in (FlowResultType.SHOW_PROGRESS, FlowResultType.SHOW_PROGRESS_DONE):
            return result
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


async def test_bt_provision_success(hass, mqtt_mock):
    result = await _start(hass)
    write = AsyncMock()
    with patch(f"{FLOW}._async_ble_write", write), \
         patch(f"{FLOW}._async_wait_for_mqtt", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        result = await _run_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Woonkamer"
    assert result["data"] == {"mac": WIFI_MAC, "name": "Woonkamer"}   # no secrets stored
    write.assert_awaited_once()


async def test_bt_provision_ble_error_returns_to_form(hass, mqtt_mock):
    result = await _start(hass)
    write = AsyncMock(side_effect=ProvisioningError("not in range"))
    with patch(f"{FLOW}._async_ble_write", write):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        result = await _run_progress(hass, result)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bt_setup"
    assert result["errors"] == {"base": "ble_failed"}
    assert result["description_placeholders"]["error"] == "not in range"
    write.assert_awaited_once()   # the form input is not re-submitted in a loop


async def test_bt_provision_timeout_then_add_anyway(hass, mqtt_mock):
    result = await _start(hass)
    with patch(f"{FLOW}._async_ble_write", AsyncMock()), \
         patch(f"{FLOW}._async_wait_for_mqtt", AsyncMock(return_value=False)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        result = await _run_progress(hass, result)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bt_timeout"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_bt_invalid_input(hass, mqtt_mock):
    result = await _start(hass)
    bad = {**INPUT, "mqtt_password": "with space"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_provisioning"}


async def test_bt_already_configured(hass, mqtt_mock):
    MockConfigEntry(domain=DOMAIN, unique_id=WIFI_MAC, data={"mac": WIFI_MAC, "name": "x"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=BLE)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
