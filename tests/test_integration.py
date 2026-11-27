import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_mqtt_message, async_fire_time_changed,
)

from custom_components.qingping_cgdn1.const import DOMAIN

MAC = "7CC29400BEEF"
UP = f"qingping/{MAC}/up"
DOWN = f"qingping/{MAC}/down"


def rt(ts, temp=20.41, co2=1200, unit="C", status=0):
    return json.dumps({"type": "12", "mac": MAC, "version": "4.8.5", "timezone": 10, "timestamp": ts,
        "sensorData": [{"timestamp": {"value": ts}, "battery": {"value": 100, "status": 2},
            "temperature": {"value": temp, "status": 0, "unit": unit, "co2_calib_state": 0},
            "humidity": {"value": 53.58, "status": 0, "unit": "%"},
            "co2": {"value": co2, "status": status}, "pm25": {"value": 4, "status": 0},
            "pm10": {"value": 4, "status": 0}}]})

SETTINGS = {"auto_slideing_time": 120, "co2_asc": 1, "co2_offset": 0, "co2_zoom": 0,
    "collect_interval": 60, "display_off_time": 120, "humidity_offset": 0, "is_12_hour_mode": 0,
    "need_ack": 1, "night_mode_end_time": 0, "night_mode_start_time": 0, "pm10_offset": 0,
    "pm25_offset": 0, "pm_sampling_interval": 1, "power_off_time": 30, "report_interval": 60,
    "screensaver_type": 1, "temperature_offset": 0, "temperature_unit": "C",
    "temperature_zoom": 0, "timezone": 10}


@pytest.fixture
async def setup(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, title="beeF",
                            data={"mac": MAC, "name": "beeF", "update_interval": 15})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def published(mqtt_mock, typ=None):
    out = []
    for call in mqtt_mock.async_publish.call_args_list:
        topic, payload = call.args[0], json.loads(call.args[1])
        if topic == DOWN and (typ is None or payload.get("type") == typ):
            out.append(payload)
    return out


async def test_setup_publishes_realtime_and_query(hass, mqtt_mock, setup):
    rts = published(mqtt_mock, "12")
    assert rts and rts[0]["up_itvl"] == "15" and rts[0]["duration"] == "3600"
    assert published(mqtt_mock, "28")


async def test_realtime_values_and_names(hass, mqtt_mock, setup):
    now = int(dt_util.utcnow().timestamp())
    async_fire_mqtt_message(hass, UP, rt(now))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beef_carbon_dioxide").state == "1200"
    t = hass.states.get("sensor.beef_temperature")
    assert t.state == "20.41"
    assert t.attributes["friendly_name"] == "beeF Temperature"
    assert hass.states.get("sensor.beef_humidity").state == "53.58"
    assert hass.states.get("sensor.beef_battery_state").state == "full"
    assert hass.states.get("sensor.beef_status").state == "online"
    assert hass.states.get("sensor.beef_sensor_status").state == "OK"
    assert hass.states.get("sensor.beef_extra_data").state == "0"
    assert hass.states.get("sensor.beef_firmware").state == "4.8.5"


async def test_type10_answered(hass, mqtt_mock, setup):
    async_fire_mqtt_message(hass, UP, json.dumps({"id": 1, "type": "10"}))
    await hass.async_block_till_done()
    ans = published(mqtt_mock, "11")
    assert ans and ans[-1]["dev_list"] == ["FFFFFFFFFFFF"]


async def test_type13_wifi(hass, mqtt_mock, setup):
    async_fire_mqtt_message(hass, UP, json.dumps({"id": 250, "type": "13",
        "wifi_info": "Example,Net,-58,1,02:00:00:00:00:01", "sw_version": "4.8.5",
        "module_version": "4.8.5", "wifi_mac": MAC, "hk_salt": "SECRET", "iot_platform": 0,
        "timestamp": 1, "timezone": 10, "hw_version": "0001"}))
    await hass.async_block_till_done()
    s = hass.states.get("sensor.beef_wifi_signal")
    assert s.state == "-58"
    assert s.attributes["wifi_field_3"] == "1"
    for key in ("ssid", "bssid", "hk_salt", "wifi_info"):
        assert key not in s.attributes
    assert "02:00:00:00:00:01" not in json.dumps(dict(s.attributes))


async def test_temperature_step_and_spike(hass, mqtt_mock, setup):
    now = int(dt_util.utcnow().timestamp())
    seq = [20.0, 20.02, 20.04, 18.06, 18.08, 18.10, 21.0, 18.14]
    for i, v in enumerate(seq):
        async_fire_mqtt_message(hass, UP, rt(now + i, temp=v))
        await hass.async_block_till_done()
    t = float(hass.states.get("sensor.beef_temperature").state)
    assert 19.9 < t < 20.3, t
    corr = float(hass.states.get("number.beef_temperature_step_correction").state)
    assert corr > 1.5
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"temp_step_{MAC}") is not None


async def test_fahrenheit_converted(hass, mqtt_mock, setup):
    now = int(dt_util.utcnow().timestamp())
    async_fire_mqtt_message(hass, UP, rt(now, temp=68.0, unit="F"))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beef_temperature").state == "20.0"


async def test_stale_history_acked_not_applied(hass, mqtt_mock, setup):
    now = int(dt_util.utcnow().timestamp())
    async_fire_mqtt_message(hass, UP, rt(now, co2=800))
    await hass.async_block_till_done()
    old = json.loads(rt(now - 3600, co2=1500)); old.update({"type": "17", "id": 77, "need_ack": 1})
    async_fire_mqtt_message(hass, UP, json.dumps(old))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beef_carbon_dioxide").state == "800"
    assert any(p.get("ack_id") == 77 for p in published(mqtt_mock, "18"))


async def test_settings_entities_and_write(hass, mqtt_mock, setup):
    import asyncio
    async def settle():
        for _ in range(20):
            await asyncio.sleep(0.01)
    async_fire_mqtt_message(hass, UP, json.dumps({"type": "28", "id": 1, "setting": SETTINGS}))
    await settle()
    assert hass.states.get("number.beef_screen_off_after").state == "120.0"
    assert hass.states.get("switch.beef_co2_automatic_calibration").state == "on"
    assert hass.states.get("select.beef_screen_mode").state == "current"
    # device answers the read-before-write query of the auto-tune
    async_fire_mqtt_message(hass, UP, json.dumps({"type": "28", "id": 2, "setting": SETTINGS}))
    await settle()
    writes = published(mqtt_mock, "17")
    assert writes and writes[-1]["setting"]["report_interval"] == 3600
    acked = {**SETTINGS, **writes[-1]["setting"]}
    async_fire_mqtt_message(hass, UP, json.dumps({"type": "28", "id": 3, "setting": acked}))
    await settle()
    await hass.async_block_till_done()


async def test_offline_issue(hass, mqtt_mock, setup):
    now = int(dt_util.utcnow().timestamp())
    async_fire_mqtt_message(hass, UP, rt(now))
    await hass.async_block_till_done()
    client = setup.runtime_data
    client._last_rx -= 10_000  # pretend the last message is old
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beef_status").state == "offline"
    assert hass.states.get("sensor.beef_carbon_dioxide").state == "unavailable"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"offline_{MAC}") is not None
    async_fire_mqtt_message(hass, UP, rt(now + 10_000))
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"offline_{MAC}") is None


async def test_issue_uses_ha_device_name(hass, mqtt_mock, setup):
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, MAC)})
    registry.async_update_device(device.id, name_by_user="Zolder")
    client = setup.runtime_data
    assert client.display_name == "Zolder" and client.name == "beeF"
    now = int(dt_util.utcnow().timestamp())
    async_fire_mqtt_message(hass, UP, rt(now))
    await hass.async_block_till_done()
    client._last_rx -= 10_000
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"offline_{MAC}")
    assert issue is not None and issue.translation_placeholders["name"] == "Zolder"


async def test_sensor_fault_issue(hass, mqtt_mock, setup):
    now = int(dt_util.utcnow().timestamp())
    async_fire_mqtt_message(hass, UP, rt(now, status=3))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beef_sensor_status").state == "Fault: co2"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"sensor_fault_{MAC}") is not None


async def test_update_interval(hass, mqtt_mock, setup):
    await hass.services.async_call("number", "set_value",
        {"entity_id": "number.beef_update_interval", "value": 30}, blocking=True)
    assert published(mqtt_mock, "12")[-1]["up_itvl"] == "30"
    assert setup.data["update_interval"] == 30
    assert hass.states.get("number.beef_update_interval").state == "30"


async def test_mqtt_discovery_flow(hass, mqtt_mock):
    info = MqttServiceInfo(topic="qingping/7CC29400CAFE/up", payload="{}", qos=0,
                           retain=False, subscribed_topic="qingping/+/up", timestamp=0)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_MQTT}, data=info)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "AIR1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"mac": "7CC29400CAFE", "name": "AIR1"}


async def test_manual_flow_duplicate_aborts(hass, mqtt_mock, setup):
    with patch("custom_components.qingping_cgdn1.config_flow.SCAN_SECONDS", 0):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "manual"
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "x", "mac": "zz"})
    assert bad["errors"] == {"mac": "invalid_mac"}
    dup = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "x", "mac": "7c:c2:94:00:be:ef"})
    assert dup["type"] is FlowResultType.ABORT and dup["reason"] == "already_configured"


async def test_entity_id_migration(hass, mqtt_mock):
    reg = er.async_get(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, title="beeF", data={"mac": MAC, "name": "beeF"})
    entry.add_to_hass(hass)
    reg.async_get_or_create("sensor", DOMAIN, f"{MAC}_temperature", suggested_object_id="beef_temperature", config_entry=entry)
    reg.async_get_or_create("number", DOMAIN, f"{MAC}_dev_co2_zoom", suggested_object_id="beef_co2_offset_2", config_entry=entry)
    reg.async_get_or_create("sensor", DOMAIN, f"{MAC}_temperature_unfiltered", suggested_object_id="air2_beef_temperature_unfiltered", config_entry=entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert reg.async_get_entity_id("number", DOMAIN, f"{MAC}_dev_co2_zoom") == "number.beef_co2_offset_percent"
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_temperature_unfiltered") == "sensor.beef_temperature_unfiltered"


async def test_diagnostics_redacts(hass, mqtt_mock, setup):
    from custom_components.qingping_cgdn1.diagnostics import async_get_config_entry_diagnostics
    async_fire_mqtt_message(hass, UP, json.dumps({"type": "13", "hk_salt": "SECRET",
                                                     "wifi_info": "MyHomeNet,-50,1,02:00:00:00:00:02"}))
    await hass.async_block_till_done()
    d = json.dumps(await async_get_config_entry_diagnostics(hass, setup))
    for secret in ("SECRET", "MyHomeNet", "02:00:00:00:00:02"):
        assert secret not in d


async def test_unload(hass, mqtt_mock, setup):
    assert await hass.config_entries.async_unload(setup.entry_id)
