"""Base entities for Qingping CGDN1."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory

from .client import QingpingClient
from .const import DOMAIN, MANUFACTURER, MODEL


class QingpingEntity(Entity):
    """Push entity fed by the client; only writes state when something changed."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _min_interval: float = 0  # s between writes of a changed value (0 = always)
    # Re-write an unchanged state on every device message. HA then only bumps
    # state.last_reported: no state_changed event, no logbook entry, no new
    # recorder row. Used by "Status" to expose "last seen" for free.
    _report_every_update: bool = False

    def __init__(self, client: QingpingClient, key: str, unique_suffix: str | None = None) -> None:
        self.client = client
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{client.mac}_{unique_suffix or key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client.mac)},
            name=client.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._written: tuple | None = None
        self._last_write = 0.0

    def _snapshot(self) -> tuple:
        """What decides whether a state write is needed."""
        return (self.available, getattr(self, "native_value", None),
                getattr(self, "is_on", None), getattr(self, "current_option", None),
                repr(self.extra_state_attributes))

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.client.async_add_listener(self._handle_update))
        self.async_on_remove(self.client.settings.async_add_listener(self._handle_update))
        self._written = self._snapshot()
        self._last_write = time.monotonic()

    def _handle_update(self) -> None:
        snap = self._snapshot()
        if snap == self._written:
            if self._report_every_update and self.hass is not None:
                self.async_write_ha_state()
            return
        now = time.monotonic()
        availability_changed = self._written is None or snap[0] != self._written[0]
        if (
            not availability_changed
            and self._min_interval
            and now - self._last_write < self._min_interval
        ):
            return
        self._written = snap
        self._last_write = now
        self.async_write_ha_state()


class QingpingSettingEntity(QingpingEntity):
    """Entity backed by an on-device setting (written with type 17)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: QingpingClient, key: str) -> None:
        super().__init__(client, key, unique_suffix=f"dev_{key}")

    @property
    def available(self) -> bool:
        return self._key in self.client.settings.values

    @property
    def _value(self) -> Any:
        return self.client.settings.values.get(self._key)

    async def _async_write(self, value: Any) -> None:
        if not self.client.settings.available:
            raise HomeAssistantError("Qingping settings not received yet")
        await self.client.settings.async_set(self._key, value)
        self._handle_update()
