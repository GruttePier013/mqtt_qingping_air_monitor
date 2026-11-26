"""'Last seen' without logbook noise: Status.last_reported + disabled Last seen sensor."""
from __future__ import annotations

import time

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.qingping_cgdn1.const import DOMAIN

from test_integration import MAC, UP, rt, setup  # noqa: F401  (fixture re-export)

STATUS = "sensor.beef_status"


async def test_status_reports_every_message_without_state_changed(hass, mqtt_mock, setup):  # noqa: F811
    now = int(time.time())
    async_fire_mqtt_message(hass, UP, rt(now))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "online"
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


async def test_last_seen_disabled_by_default(hass, mqtt_mock, setup):  # noqa: F811
    entry = er.async_get(hass).async_get(
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{MAC}_last_seen"))
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("sensor.beef_last_seen") is None


async def test_migration_disables_existing_last_seen(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, title="beeF", version=1, minor_version=1,
                            data={"mac": MAC, "name": "beeF"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create("sensor", DOMAIN, f"{MAC}_last_seen",
                                       suggested_object_id="beef_last_seen", config_entry=entry)
    assert old.disabled_by is None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(old.entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.minor_version == 2


async def test_migration_respects_user_choice_afterwards(hass, mqtt_mock):
    """Once migrated (1.2), a user who re-enables Last seen keeps it."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC, title="beeF", version=1, minor_version=2,
                            data={"mac": MAC, "name": "beeF"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    reenabled = registry.async_get_or_create("sensor", DOMAIN, f"{MAC}_last_seen",
                                             suggested_object_id="beef_last_seen", config_entry=entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(reenabled.entity_id).disabled_by is None


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
