"""Status sensor: realtime / online / offline, last report as attributes, no logbook noise."""
from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_mqtt_message, async_fire_time_changed,
)

from custom_components.qingping_cgdn1.const import DOMAIN

from test_integration import MAC, UP, rt, setup  # noqa: F401  (fixture re-export)

STATUS = "sensor.beef_status"


async def test_status_reports_every_message_without_state_changed(hass, mqtt_mock, setup):  # noqa: F811
    now = int(time.time())
    async_fire_mqtt_message(hass, UP, rt(now))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "realtime"
    first_reported = hass.states.get(STATUS).last_reported

    changed: list = []
    hass.bus.async_listen(
        EVENT_STATE_CHANGED,
        lambda e: changed.append(e) if e.data["entity_id"] == STATUS else None,
    )
    for i in range(1, 4):
        async_fire_mqtt_message(hass, UP, rt(now + 15 * i, temp=20.41 + i / 100))
        await hass.async_block_till_done()

    state = hass.states.get(STATUS)
    assert changed == []                         # no events → no logbook entries, no recorder rows
    assert state.last_reported > first_reported  # but the time of the last message is tracked
    assert state.last_changed < state.last_reported


async def test_status_realtime_online_offline(hass, mqtt_mock, setup):  # noqa: F811
    client = setup.runtime_data
    now = int(time.time())
    async_fire_mqtt_message(hass, UP, rt(now))
    await hass.async_block_till_done()
    state = hass.states.get(STATUS)
    assert state.state == "realtime"
    assert state.attributes["report_type"] == "realtime"
    assert state.attributes["report_type_code"] == "12"
    assert state.attributes["expected_every_s"] == 15
    assert state.attributes["last_report"].endswith("+00:00")
    assert state.attributes["device_timestamp"] == now

    # realtime stops, other messages keep coming -> online
    client._last_realtime -= 10_000
    async_fire_mqtt_message(hass, UP, json.dumps({"type": "13", "sw_version": "4.8.5"}))
    await hass.async_block_till_done()
    state = hass.states.get(STATUS)
    assert state.state == "online"
    assert state.attributes["report_type"] == "device_info"

    # nothing at all -> offline (watchdog)
    client._last_rx -= 10_000
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "offline"

    # back
    async_fire_mqtt_message(hass, UP, rt(now + 10_000))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "realtime"


async def test_realtime_lost_detected_by_watchdog(hass, mqtt_mock, setup):  # noqa: F811
    client = setup.runtime_data
    async_fire_mqtt_message(hass, UP, rt(int(time.time())))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "realtime"
    client._last_realtime -= 10_000  # still "online" (last_rx recent)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "online"


async def test_last_seen_and_report_type_entities_gone(hass, mqtt_mock, setup):  # noqa: F811
    registry = er.async_get(hass)
    for suffix in ("last_seen", "report_type"):
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{MAC}_{suffix}") is None
    assert hass.states.get("sensor.beef_last_seen") is None
    assert hass.states.get("sensor.beef_report_type") is None


@pytest.mark.parametrize("minor", [1, 2])
async def test_migration_removes_old_entities(hass, mqtt_mock, minor):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, title="beeF", version=1, minor_version=minor,
                            data={"mac": MAC, "name": "beeF"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = [registry.async_get_or_create("sensor", DOMAIN, f"{MAC}_{suffix}",
                                        suggested_object_id=f"beef_{suffix}", config_entry=entry)
           for suffix in ("last_seen", "report_type")]
    status = registry.async_get_or_create("sensor", DOMAIN, f"{MAC}_status",
                                          suggested_object_id="beef_status", config_entry=entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert all(registry.async_get(e.entity_id) is None for e in old)
    assert registry.async_get(status.entity_id) is not None  # history kept
    assert entry.minor_version == 3


async def test_slider_numbers(hass, mqtt_mock, setup):  # noqa: F811
    interval = hass.states.get("number.beef_update_interval")
    assert interval.attributes["mode"] == "slider"
    assert interval.attributes["step"] == 5
    assert (interval.attributes["min"], interval.attributes["max"]) == (5, 120)
    registry = er.async_get(hass)
    tz = registry.async_get(registry.async_get_entity_id("number", DOMAIN, f"{MAC}_dev_timezone"))
    assert tz.capabilities["mode"] == "slider"
    assert tz.capabilities["step"] == 1
    assert (tz.capabilities["min"], tz.capabilities["max"]) == (-12, 14)
