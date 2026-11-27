"""The Qingping CGDN1 (Air Monitor Lite) integration - local MQTT."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import repairs
from .client import QingpingClient
from .const import DOMAIN, normalize_mac

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TIME,
]

type QingpingConfigEntry = ConfigEntry[QingpingClient]

# unique-id suffix -> wanted object-id suffix (cleans up "_2" duplicates etc.)
ENTITY_ID_MIGRATIONS: dict[str, tuple[str, str]] = {
    "co2": ("sensor", "carbon_dioxide"),
    "dev_co2_zoom": ("number", "co2_offset_percent"),
    "dev_temperature_zoom": ("number", "temperature_offset_percent"),
    "dev_humidity_offset": ("number", "humidity_offset"),
    "temperature_unfiltered": ("sensor", "temperature_unfiltered"),
}


# sensors folded into Status (unique-id suffixes)
REMOVED_SENSORS = ("last_seen", "report_type")


@callback
def _async_migrate_entity_ids(hass: HomeAssistant, mac: str) -> None:
    """Rename confusing entity ids (history is kept by HA)."""
    registry = er.async_get(hass)
    base_id = registry.async_get_entity_id("sensor", DOMAIN, f"{mac}_temperature")
    if not base_id or not base_id.endswith("_temperature"):
        return
    base = base_id.split(".", 1)[1][: -len("_temperature")]
    for suffix, (domain, wanted) in ENTITY_ID_MIGRATIONS.items():
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{mac}_{suffix}")
        if not entity_id:
            continue
        new_id = f"{domain}.{base}_{wanted}"
        if entity_id == new_id:
            continue
        object_id = entity_id.split(".", 1)[1]
        # only touch ids that are clearly wrong: "_2" duplicates, double prefixes, old co2
        if not (
            object_id.endswith("_2")
            or object_id.endswith("_co2")
            or (suffix == "temperature_unfiltered" and not object_id.startswith(f"{base}_temperature"))
        ):
            continue
        if registry.async_get(new_id) is not None or hass.states.get(new_id) is not None:
            _LOGGER.warning("Cannot rename %s: %s already exists", entity_id, new_id)
            continue
        registry.async_update_entity(entity_id, new_entity_id=new_id)
        _LOGGER.info("Renamed %s to %s", entity_id, new_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config entry migrations.

    1.1 -> 1.2: disable the "Last seen" sensor (one logbook entry per message;
    the logbook exclude config does not apply on the device page). Users can
    re-enable it; "Status" now carries the time of the last message in
    ``last_reported``.

    1.2 -> 1.3: remove "Last seen" and "Report type"; their data are now
    attributes of "Status" (realtime / online / offline).
    """
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        mac = normalize_mac(entry.data.get("mac", ""))
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{mac}_last_seen"):
            reg_entry = registry.async_get(entity_id)
            if reg_entry is not None and reg_entry.disabled_by is None:
                registry.async_update_entity(
                    entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
                _LOGGER.info("Disabled %s (logbook noise); use the Status sensor's "
                             "last_reported instead", entity_id)
        hass.config_entries.async_update_entry(entry, minor_version=2)
    if entry.minor_version < 3:
        # 1.2 -> 1.3: "Last seen" and "Report type" are now attributes of
        # Status (realtime / online / offline): remove the separate entities.
        mac = normalize_mac(entry.data.get("mac", ""))
        registry = er.async_get(hass)
        for suffix in REMOVED_SENSORS:
            if entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{mac}_{suffix}"):
                registry.async_remove(entity_id)
                _LOGGER.info("Removed %s: now an attribute of the Status sensor", entity_id)
        hass.config_entries.async_update_entry(entry, minor_version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: QingpingConfigEntry) -> bool:
    """Set up one Qingping CGDN1."""
    mac = normalize_mac(entry.data["mac"])
    _async_migrate_entity_ids(hass, mac)
    client = QingpingClient(hass, entry, mac)
    entry.runtime_data = client
    await client.async_start()
    entry.async_on_unload(client.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: QingpingConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove repair issues of a deleted device."""
    repairs.clear_all(hass, normalize_mac(entry.data.get("mac", "")))
