"""Switch entities for Qingping CGDN1 device settings."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import QingpingClient
from .entity import QingpingSettingEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    client: QingpingClient = entry.runtime_data
    async_add_entities([QingpingCo2AscSwitch(client, "co2_asc")])


class QingpingCo2AscSwitch(QingpingSettingEntity, SwitchEntity):
    """CO2 automatic self-calibration (ASC). No manual calibration command exists."""

    _attr_icon = "mdi:molecule-co2"

    @property
    def is_on(self) -> bool | None:
        value = self._value
        return None if value is None else int(value) == 1

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(1)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(0)
