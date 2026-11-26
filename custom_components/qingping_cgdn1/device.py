"""On-device settings for the Qingping CGDN1 over local MQTT.

Protocol (Air Monitor Lite MQTT, sections 3.3-3.5):
  * ``{"type": "28"}`` on ``/down``  -> device answers type 28 with ``setting``.
  * ``{"type": "17", "setting": {...}}`` -> device applies and answers type 28.

Lessons taken from Kevin6872/qingping-air-monitor-lite (cloud variant):
  * always read a fresh type-28 snapshot before writing and send the merged,
    complete settings object (never a stale cache);
  * skip the write when the device already has the requested values;
  * treat a write as successful only after the device reports the values back;
  * device units: temperature_offset x100, humidity_offset x10, timezone x10.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import MQTT_TOPIC_PREFIX

_LOGGER = logging.getLogger(__name__)

QUERY_TIMEOUT = 10  # s, local broker -> device is fast
WRITE_ACK_TIMEOUT = 15
QUERY_INTERVAL = timedelta(hours=1)  # settings rarely change
# We only use realtime (type 12) data. Historical (type 17) collection/upload
# is reduced to once per hour: less traffic, no acks storm, no backlogs.
HISTORY_INTERVAL = 3600

# device key -> (HA value from device, device value from HA)
CONVERSIONS: dict[str, tuple[Callable[[Any], Any], Callable[[Any], Any]]] = {
    "temperature_offset": (lambda v: round(float(v) / 100, 2), lambda v: int(round(float(v) * 100))),
    "humidity_offset": (lambda v: round(float(v) / 10, 1), lambda v: int(round(float(v) * 10))),
    "co2_offset": (int, lambda v: int(v)),
    # *_zoom = percentage correction, device units x10 (protocol 3.4).
    # temperature_zoom scale is undocumented; assumed x10 like the others.
    "temperature_zoom": (lambda v: round(float(v) / 10, 1), lambda v: int(round(float(v) * 10))),
    "co2_zoom": (lambda v: round(float(v) / 10, 1), lambda v: int(round(float(v) * 10))),
    "pm25_offset": (int, lambda v: int(v)),
    "pm10_offset": (int, lambda v: int(v)),
    "power_off_time": (int, lambda v: int(v)),
    "display_off_time": (int, lambda v: int(v)),
    "auto_slideing_time": (int, lambda v: int(v)),
    "timezone": (lambda v: round(float(v) / 10, 1), lambda v: int(round(float(v) * 10))),
    "pm_sampling_interval": (int, lambda v: int(v)),
    "co2_sampling_interval": (int, lambda v: int(v)),
    "night_mode_start_time": (int, lambda v: int(v)),
    "night_mode_end_time": (int, lambda v: int(v)),
    "screensaver_type": (int, lambda v: int(v)),
    "temperature_unit": (str, str),
    "is_12_hour_mode": (int, lambda v: int(v)),
    "co2_asc": (int, lambda v: int(v)),
}


def ha_timezone_device_value() -> int:
    """HA's current UTC offset in device units (hours x 10), DST aware."""
    offset = dt_util.now().utcoffset() or timedelta()
    return int(offset.total_seconds() / 360)


class QingpingDeviceSettings:
    """Read/write the device settings of one CGDN1."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
        self.hass = hass
        self.entry = entry
        self.mac = mac
        self.down_topic = f"{MQTT_TOPIC_PREFIX}/{mac}/down"
        self.raw: dict[str, Any] = {}       # last complete type-28 setting object
        self.values: dict[str, Any] = {}    # converted to HA units
        self._listeners: list[Callable[[], None]] = []
        self._waiters: list[tuple[Callable[[dict[str, Any]], bool], asyncio.Future]] = []
        self._write_lock = asyncio.Lock()
        self.auto_timezone = True
        self._auto_attempted: dict[str, Any] = {}

    # ------------------------------------------------------------------ setup
    def async_start(self) -> None:
        """Periodic refresh so changes made on the device itself show up."""

        async def _periodic(_now) -> None:
            await self.async_request_settings()

        self.entry.async_on_unload(
            async_track_time_interval(self.hass, _periodic, QUERY_INTERVAL)
        )
        self.entry.async_on_unload(self.async_stop)

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    @property
    def available(self) -> bool:
        return bool(self.raw)

    # -------------------------------------------------------------- transport
    async def _publish(self, payload: dict[str, Any]) -> None:
        await mqtt.async_publish(self.hass, self.down_topic, json.dumps(payload))
        _LOGGER.debug("Published to %s: %s", self.down_topic, payload)

    async def async_request_settings(self) -> None:
        """Fire-and-forget type 28 query (answer handled in handle_settings)."""
        try:
            await self._publish({"type": "28"})
        except HomeAssistantError as err:
            _LOGGER.debug("Settings query for %s failed: %s", self.mac, err)

    async def _send_and_wait(
        self,
        payload: dict[str, Any],
        matcher: Callable[[dict[str, Any]], bool],
        timeout: float,
    ) -> dict[str, Any]:
        future: asyncio.Future = self.hass.loop.create_future()
        waiter = (matcher, future)
        self._waiters.append(waiter)
        try:
            await self._publish(payload)
            return await asyncio.wait_for(future, timeout)
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def async_query_settings(self) -> dict[str, Any]:
        """Return a fresh complete settings object from the device."""
        try:
            return await self._send_and_wait(
                {"type": "28"}, lambda s: True, QUERY_TIMEOUT
            )
        except asyncio.TimeoutError as err:
            raise HomeAssistantError(
                f"Qingping {self.mac} did not answer the settings query"
            ) from err

    # ---------------------------------------------------------------- inbound
    @callback
    def handle_settings(self, setting: Any) -> None:
        """Process a type-28 report from the device."""
        if not isinstance(setting, dict):
            return
        # Offset-only replies (3.4) are partial: merge into the snapshot.
        self.raw = {**self.raw, **setting}
        converted: dict[str, Any] = {}
        for key, (from_device, _) in CONVERSIONS.items():
            if key in self.raw:
                try:
                    converted[key] = from_device(self.raw[key])
                except (TypeError, ValueError):
                    continue
        changed = converted != self.values
        self.values = converted

        for matcher, future in list(self._waiters):
            if not future.done() and matcher(setting):
                future.set_result(dict(self.raw))
        if changed:  # setting entities only write state when a value changed
            for update in list(self._listeners):
                update()

        self._async_auto_tune()

    @callback
    def _async_auto_tune(self) -> None:
        """Keep timezone (DST) in sync and minimise historical reporting."""
        if self._write_lock.locked():
            return
        wanted: dict[str, Any] = {}
        if self.auto_timezone and "timezone" in self.raw:
            wanted["timezone"] = ha_timezone_device_value()
        if "report_interval" in self.raw:
            wanted["report_interval"] = HISTORY_INTERVAL
        if "collect_interval" in self.raw:
            wanted["collect_interval"] = HISTORY_INTERVAL
        changes = {
            k: v
            for k, v in wanted.items()
            # one attempt per target value: no retry loop if the device refuses
            if self.raw.get(k) != v and self._auto_attempted.get(k) != v
        }
        if not changes:
            return
        self._auto_attempted.update(changes)
        _LOGGER.info("Qingping %s auto-settings: %s", self.mac, changes)
        self.hass.async_create_task(self._async_auto_write(changes))

    async def _async_auto_write(self, changes: dict[str, Any]) -> None:
        try:
            await self._async_set_raw(changes)
        except HomeAssistantError as err:
            _LOGGER.warning("Qingping %s auto-settings %s failed: %s", self.mac, changes, err)

    @callback
    def async_stop(self) -> None:
        """Fail pending waiters on unload."""
        for _, future in self._waiters:
            if not future.done():
                future.cancel()
        self._waiters.clear()

    # --------------------------------------------------------------- outbound
    async def async_set(self, key: str, ha_value: Any) -> None:
        """Write one setting given in HA units."""
        to_device = CONVERSIONS[key][1]
        await self._async_set_raw({key: to_device(ha_value)})

    async def _async_set_raw(self, requested: Mapping[str, Any]) -> None:
        async with self._write_lock:
            current = await self.async_query_settings()
            if all(current.get(k) == v for k, v in requested.items()):
                return  # already set; no redundant full write
            merged = {**current, **requested}
            merged.pop("need_ack", None)  # report-only field

            def _includes(setting: dict[str, Any]) -> bool:
                return all(setting.get(k) == v for k, v in requested.items())

            try:
                ack = await self._send_and_wait(
                    {"type": "17", "setting": merged}, _includes, WRITE_ACK_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Ack may be lost; verify by reading instead of re-sending.
                ack = await self.async_query_settings()

            mismatch = {k: (v, ack.get(k)) for k, v in requested.items() if ack.get(k) != v}
            if mismatch:
                raise HomeAssistantError(
                    f"Qingping {self.mac} did not apply settings: {mismatch}"
                )
