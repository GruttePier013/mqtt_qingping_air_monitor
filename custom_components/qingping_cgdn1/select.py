"""Select entities for Qingping CGDN1 device settings."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import QingpingClient
from .entity import QingpingSettingEntity

# option key (translated) -> device value
SELECTS: dict[str, tuple[dict[str, object], str]] = {
    "screensaver_type": (
        {"rotating": 0, "current": 1, "time_rotating": 2, "time_current": 3},
        "mdi:monitor-dashboard",
    ),
    "temperature_unit": ({"celsius": "C", "fahrenheit": "F"}, "mdi:temperature-celsius"),
    "is_12_hour_mode": ({"24h": 0, "12h": 1}, "mdi:clock-outline"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    client: QingpingClient = entry.runtime_data
    async_add_entities(
        QingpingSettingSelect(client, key, options, icon)
        for key, (options, icon) in SELECTS.items()
    )


class QingpingSettingSelect(QingpingSettingEntity, SelectEntity):
    def __init__(self, client: QingpingClient, key: str, options: dict, icon: str) -> None:
        super().__init__(client, key)
        self._to_device = options
        self._from_device = {v: k for k, v in options.items()}
        self._attr_options = list(options)
        self._attr_icon = icon

    @property
    def current_option(self) -> str | None:
        return self._from_device.get(self._value)

    async def async_select_option(self, option: str) -> None:
        await self._async_write(self._to_device[option])
