"""Number entities for the Qingping CGDN1."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .client import QingpingClient
from .const import MAX_UPDATE_INTERVAL, MIN_UPDATE_INTERVAL, UNIT_PPM, UNIT_UG_M3
from .entity import QingpingEntity, QingpingSettingEntity


@dataclass(frozen=True)
class SettingNumber:
    key: str
    minimum: float
    maximum: float
    step: float
    unit: str | None
    icon: str | None = None
    enabled_default: bool = True
    mode: NumberMode = NumberMode.BOX


OBJECT_IDS = {"co2_zoom": "co2_offset_percent", "temperature_zoom": "temperature_offset_percent"}

# Ranges as tested on CGDN1 devices by Kevin6872/qingping-air-monitor-lite
SETTING_NUMBERS = (
    SettingNumber("temperature_offset", -10, 10, 0.1, UnitOfTemperature.CELSIUS, "mdi:thermometer-plus"),
    SettingNumber("temperature_zoom", -10, 10, 0.1, PERCENTAGE, "mdi:thermometer-plus"),
    SettingNumber("humidity_offset", -20, 20, 0.1, PERCENTAGE, "mdi:water-plus"),
    SettingNumber("co2_offset", -500, 500, 1, UNIT_PPM, "mdi:molecule-co2"),
    SettingNumber("co2_zoom", -50, 50, 0.1, PERCENTAGE, "mdi:molecule-co2"),
    SettingNumber("pm25_offset", -500, 500, 1, UNIT_UG_M3, "mdi:blur"),
    SettingNumber("pm10_offset", -500, 500, 1, UNIT_UG_M3, "mdi:blur"),
    SettingNumber("power_off_time", 0, 60, 5, UnitOfTime.MINUTES, "mdi:power-sleep"),
    SettingNumber("display_off_time", 0, 600, 5, UnitOfTime.SECONDS, "mdi:monitor-off"),
    SettingNumber("auto_slideing_time", 0, 600, 5, UnitOfTime.SECONDS, "mdi:monitor-shimmer"),
    SettingNumber("timezone", -12, 14, 1, UnitOfTime.HOURS, "mdi:earth", mode=NumberMode.SLIDER),
    # Sampling intervals: unit undocumented for the CGDN1 (raw device value).
    # Only available when the device reports the key in its settings.
    SettingNumber("pm_sampling_interval", 0, 3600, 1, None, "mdi:fan-clock", False),
    SettingNumber("co2_sampling_interval", 0, 3600, 1, None, "mdi:timer-cog-outline", False),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    client: QingpingClient = entry.runtime_data
    entities: list = [QingpingSettingNumber(client, d) for d in SETTING_NUMBERS]
    entities += [QingpingUpdateInterval(client), QingpingTempStepCorrection(client)]
    async_add_entities(entities)


class QingpingSettingNumber(QingpingSettingEntity, NumberEntity):
    """A numeric on-device setting (type 17 write, confirmed via type 28)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, client: QingpingClient, description: SettingNumber) -> None:
        super().__init__(client, description.key)
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum
        self._attr_native_step = description.step
        self._attr_mode = description.mode
        self._attr_native_unit_of_measurement = description.unit
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = description.enabled_default
        if description.key in OBJECT_IDS:  # avoid "<x>_offset_2" on first registration
            self.entity_id = f"number.{slugify(client.name)}_{OBJECT_IDS[description.key]}"

    @property
    def native_value(self) -> float | None:
        value = self._value
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write(value)


class QingpingUpdateInterval(QingpingEntity, NumberEntity):
    """Realtime report interval (up_itvl)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = MIN_UPDATE_INTERVAL
    _attr_native_max_value = MAX_UPDATE_INTERVAL
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sync-outline"

    def __init__(self, client: QingpingClient) -> None:
        super().__init__(client, "update_interval")

    @property
    def native_value(self) -> int:
        return self.client.update_interval

    async def async_set_native_value(self, value: float) -> None:
        await self.client.async_set_update_interval(int(value))


class QingpingTempStepCorrection(QingpingEntity, RestoreNumber):
    """Correction learned from temperature step artefacts (HA-side only).

    Updated automatically by the temperature filter; set to 0 to reset.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -5
    _attr_native_max_value = 5
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:stairs"

    def __init__(self, client: QingpingClient) -> None:
        super().__init__(client, "temperature_step_correction", "temp_step_correction")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None and not self.client.temp_step:
            self.client.set_temp_step(last.native_value)

    @property
    def native_value(self) -> float:
        return self.client.temp_step

    async def async_set_native_value(self, value: float) -> None:
        self.client.set_temp_step(value)
