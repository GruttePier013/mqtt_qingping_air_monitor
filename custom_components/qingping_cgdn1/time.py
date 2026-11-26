"""Night-mode time entities for Qingping CGDN1."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import QingpingClient
from .entity import QingpingSettingEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    client: QingpingClient = entry.runtime_data
    async_add_entities([
        QingpingNightTime(client, "night_mode_start_time"),
        QingpingNightTime(client, "night_mode_end_time"),
    ])


class QingpingNightTime(QingpingSettingEntity, TimeEntity):
    """Minutes since midnight on the device. Start == end means night mode off."""

    _attr_icon = "mdi:weather-night"

    @property
    def native_value(self) -> time | None:
        value = self._value
        if value is None:
            return None
        minutes = int(value)
        return time(hour=(minutes // 60) % 24, minute=minutes % 60)

    async def async_set_value(self, value: time) -> None:
        await self._async_write(value.hour * 60 + value.minute)
