"""MQTT client for one Qingping CGDN1 (Air Monitor Lite MQTT protocol).

Message types (protocol + observed on firmware 4.8.5):
  up   10  "which BLE sub-devices?"  -> must be answered with 11, else no data
  up   12  realtime sensor data
  up   13  device info (wifi_info, versions)          [undocumented]
  up   17  historical data (need_ack -> answer 18)
  up   28  settings report / write acknowledgement
  down 11  answer to 10 (+ time sync)
  down 12  arm realtime reporting (up_itvl, duration)
  down 17  write settings
  down 18  ack historical data
  down 28  query settings
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import repairs
from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    HISTORY_MAX_AGE,
    KNOWN_PAYLOAD_KEYS,
    KNOWN_SENSOR_KEYS,
    KNOWN_SUB_KEYS,
    MQTT_TOPIC_PREFIX,
    OFFLINE_TIMEOUT,
    REALTIME_DURATION,
    REALTIME_REARM,
    TEMP_LOWPASS_TIME_CONSTANT,
    TEMP_OUTLIER_RADIUS,
    TEMP_OUTLIER_WINDOW,
    TEMP_STEP_MAX,
    TEMP_STEP_MAX_GAP,
    TEMP_STEP_THRESHOLD,
    WATCHDOG_INTERVAL,
)
from .device import QingpingDeviceSettings

_LOGGER = logging.getLogger(__name__)

# Never kept, not even in memory for diagnostics:
#  hk_salt   = HomeKit pairing secret
#  wifi_info = "ssid,rssi,n,bssid": network name + router MAC can be geolocated
REDACT_KEYS = {"hk_salt", "wifi_info"}


def _value(obj: Any) -> Any:
    return obj.get("value") if isinstance(obj, dict) else obj


def _entry_ts(entry: dict) -> int:
    try:
        return int(_value(entry.get("timestamp")) or 0)
    except (TypeError, ValueError):
        return 0


class QingpingClient:
    """Owns the MQTT conversation and the parsed state of one device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
        self.hass = hass
        self.entry = entry
        self.mac = mac
        self.up_topic = f"{MQTT_TOPIC_PREFIX}/{mac}/up"
        self.down_topic = f"{MQTT_TOPIC_PREFIX}/{mac}/down"
        self.settings = QingpingDeviceSettings(hass, entry, mac)

        # parsed state read by the entities
        self.data: dict[str, Any] = {}
        self.extra: dict[str, Any] = {}
        self.sensor_flags: dict[str, Any] = {}
        self.wifi: dict[str, Any] = {}
        self.last_seen: datetime | None = None
        self.last_report_type: str | None = None
        self.device_timestamp: int | None = None
        self.last_payloads: dict[str, dict] = {}

        # liveness
        self._started = time.time()
        self._last_rx = 0.0
        self._last_realtime = 0.0
        self._last_applied_ts = 0
        self._online = False
        self._offline_issue = False

        # temperature filter state
        self.temp_step: float = 0.0
        self._prev_raw: float | None = None
        self._prev_raw_t = 0.0
        self._window: deque[float] = deque(maxlen=TEMP_OUTLIER_WINDOW)
        self._lowpass: float | None = None

        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------ properties
    @property
    def name(self) -> str:
        return str(self.entry.data.get("name") or self.entry.title or self.mac)

    @property
    def update_interval(self) -> int:
        try:
            return int(self.entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        except (TypeError, ValueError):
            return DEFAULT_UPDATE_INTERVAL

    @property
    def online(self) -> bool:
        return self._online

    # ------------------------------------------------------------- listeners
    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        @callback
        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # ---------------------------------------------------------------- start
    async def async_start(self) -> None:
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, self.up_topic, self._on_message, 1)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._watchdog, timedelta(seconds=WATCHDOG_INTERVAL))
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._rearm, timedelta(seconds=REALTIME_REARM))
        )
        self.settings.async_start()
        await self.async_publish_realtime()
        await self.settings.async_request_settings()

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        self.settings.async_stop()

    # ------------------------------------------------------------- outbound
    async def _publish(self, payload: dict[str, Any]) -> None:
        try:
            await mqtt.async_publish(self.hass, self.down_topic, json.dumps(payload))
            _LOGGER.debug("Published to %s: %s", self.down_topic, payload)
        except HomeAssistantError as err:
            _LOGGER.warning("Publish to %s failed: %s", self.down_topic, err)

    async def async_publish_realtime(self) -> None:
        await self._publish(
            {"type": "12", "up_itvl": str(self.update_interval), "duration": str(REALTIME_DURATION)}
        )

    async def _rearm(self, _now=None) -> None:
        await self.async_publish_realtime()

    async def async_set_update_interval(self, seconds: int) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_UPDATE_INTERVAL: int(seconds)}
        )
        await self.async_publish_realtime()
        self._notify()

    # ------------------------------------------------------------- watchdog
    async def _watchdog(self, _now=None) -> None:
        now = time.time()
        online = bool(self._last_rx) and now - self._last_rx <= OFFLINE_TIMEOUT
        if online != self._online:
            self._online = online
            self._notify()
        if not online:
            # offline/never seen: raise issue once, keep nudging the device
            if not self._offline_issue and (
                self._last_rx or now - self._started > OFFLINE_TIMEOUT
            ):
                self._offline_issue = True
                repairs.raise_offline(self.hass, self.mac, self.name, OFFLINE_TIMEOUT // 60)
            await self.async_publish_realtime()
            await self.settings.async_request_settings()
            return
        if now - self._last_realtime > max(60, 4 * self.update_interval):
            _LOGGER.debug("%s online but no realtime reports: re-arming", self.mac)
            await self.async_publish_realtime()
        elif not self.settings.available:
            await self.settings.async_request_settings()

    @callback
    def _mark_alive(self) -> None:
        self._last_rx = time.time()
        if not self._online:
            self._online = True
            if self._offline_issue:
                self._offline_issue = False
                repairs.clear(self.hass, "offline", self.mac)
            # came back: make sure realtime + settings are (re)established
            self.hass.async_create_task(self.async_publish_realtime())

    @callback
    def _seen(self, msg_type: str, payload: dict) -> None:
        self.last_seen = dt_util.utcnow()
        self.last_report_type = msg_type
        ts = payload.get("timestamp")
        try:
            self.device_timestamp = int(ts) if ts is not None else self.device_timestamp
        except (TypeError, ValueError):
            pass

    # -------------------------------------------------------------- inbound
    @callback
    def _on_message(self, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.debug("Invalid JSON on %s: %s", msg.topic, msg.payload)
            return
        if not isinstance(payload, dict):
            return
        msg_type = str(payload.get("type", ""))
        if not msg_type:
            return
        self.last_payloads[msg_type] = {
            k: ("**REDACTED**" if k in REDACT_KEYS else v) for k, v in payload.items()
        }
        now = int(time.time())
        self._mark_alive()

        if msg_type == "10":
            self._seen(msg_type, payload)
            self.hass.async_create_task(self._publish(
                {"code": 0, "desc": "", "dev_list": ["FFFFFFFFFFFF"], "timestamp": now, "type": "11"}
            ))
            self._notify()
            return
        if msg_type == "13":
            self._seen(msg_type, payload)
            self._handle_info(payload)
            self._notify()
            return
        if msg_type == "28":
            self._seen(msg_type, payload)
            self.settings.handle_settings(payload.get("setting"))
            self._notify()
            return
        if msg_type not in ("12", "17"):
            _LOGGER.debug("Ignoring message type %s: %s", msg_type, payload)
            return
        if payload.get("mac") and str(payload["mac"]).upper() != self.mac:
            return

        if msg_type == "17" and payload.get("need_ack") and "id" in payload:
            self.hass.async_create_task(self._publish(
                {"ack_id": payload["id"], "code": 0, "desc": "", "timestamp": now, "type": "18"}
            ))

        entries = [d for d in payload.get("sensorData") or [] if isinstance(d, dict)]
        latest = max(entries, key=_entry_ts) if entries else None
        latest_ts = _entry_ts(latest) if latest else 0

        if msg_type == "17" and (
            latest is None
            or latest_ts <= self._last_applied_ts
            or (latest_ts and now - latest_ts > HISTORY_MAX_AGE)
        ):
            return  # stale backlog: acked, no state changes

        if msg_type == "12":
            self._last_realtime = time.time()
        self._seen(msg_type, payload)
        if payload.get("version"):
            self._set_versions(sw=str(payload["version"]))
        if latest is not None:
            if latest_ts:
                self._last_applied_ts = max(self._last_applied_ts, latest_ts)
            self._apply(latest, payload)
        self._notify()

    # ------------------------------------------------------------- parsing
    @callback
    def _apply(self, entry: dict, payload: dict) -> None:
        for key in ("battery", "co2", "humidity", "pm25", "pm10"):
            if key in entry and _value(entry[key]) is not None:
                self.data[key] = _value(entry[key])
        battery = entry.get("battery")
        if isinstance(battery, dict) and "status" in battery:
            self.data["battery_status"] = battery["status"]

        temp = entry.get("temperature")
        if temp is not None and _value(temp) is not None:
            try:
                celsius = float(_value(temp))
                if isinstance(temp, dict) and str(temp.get("unit", "C")).upper() == "F":
                    celsius = (celsius - 32) * 5 / 9
                self.data["temperature_raw"] = round(celsius, 2)
                self.data["temperature"] = round(self._filter_temperature(celsius), 2)
            except (TypeError, ValueError):
                pass
            if isinstance(temp, dict) and "co2_calib_state" in temp:
                self.data["co2_calib_state"] = temp["co2_calib_state"]

        flags = {
            k: v.get("status")
            for k, v in entry.items()
            if isinstance(v, dict) and "status" in v and k != "battery"
        }
        if flags:
            self.sensor_flags = flags
            faulty = sorted(k for k, s in flags.items() if s not in (0, "0"))
            if faulty:
                repairs.raise_sensor_fault(self.hass, self.mac, self.name, ", ".join(faulty))
            else:
                repairs.clear(self.hass, "sensor_fault", self.mac)

        extra = {f"payload.{k}": v for k, v in payload.items() if k not in KNOWN_PAYLOAD_KEYS}
        for k, v in entry.items():
            if k not in KNOWN_SENSOR_KEYS:
                extra[f"sensor.{k}"] = _value(v) if isinstance(v, dict) and set(v) == {"value"} else v
            elif isinstance(v, dict):
                for sub, subv in v.items():
                    if sub not in KNOWN_SUB_KEYS:
                        extra[f"sensor.{k}.{sub}"] = subv
        new = set(extra) - set(self.extra)
        if new:
            _LOGGER.info("Qingping %s sends undocumented fields: %s", self.mac,
                         {k: extra[k] for k in sorted(new)})
        self.extra = extra

    @callback
    def _handle_info(self, payload: dict) -> None:
        # wifi_info = "<ssid>,<rssi>,<n>,<bssid>" (the SSID may contain commas).
        # Only RSSI and the third field are kept; SSID and BSSID are dropped on
        # purpose: together they can geolocate the house via Wi-Fi databases.
        parts = str(payload.get("wifi_info", "")).split(",")
        wifi: dict[str, Any] = {}
        if len(parts) >= 4:
            wifi["wifi_field_3"] = parts[-2].strip()
            try:
                wifi["rssi"] = int(parts[-3])
            except ValueError:
                pass
        for key in ("hw_version", "module_version", "sw_version", "iot_platform"):
            if key in payload:
                wifi[key] = payload[key]
        self.wifi = wifi
        self._set_versions(sw=payload.get("sw_version"), hw=payload.get("hw_version"))

    @callback
    def _set_versions(self, sw: str | None = None, hw: str | None = None) -> None:
        changes: dict[str, str] = {}
        if sw and sw != self.data.get("sw_version"):
            self.data["sw_version"] = sw
            changes["sw_version"] = sw
        if hw and hw != self.data.get("hw_version"):
            self.data["hw_version"] = hw
            changes["hw_version"] = hw
        if changes:
            registry = dr.async_get(self.hass)
            device = next(
                (
                    d
                    for d in dr.async_entries_for_config_entry(registry, self.entry.entry_id)
                    if (DOMAIN, self.mac) in d.identifiers
                ),
                None,
            )
            if device is not None:
                registry.async_update_device(device.id, **changes)

    # ---------------------------------------------------- temperature filter
    @callback
    def _filter_temperature(self, value: float) -> float:
        """Step correction, then outlier (median window) + low-pass."""
        now = time.monotonic()
        if self._prev_raw is not None and now - self._prev_raw_t <= TEMP_STEP_MAX_GAP:
            delta = value - self._prev_raw
            if abs(delta) >= TEMP_STEP_THRESHOLD:
                new_step = round(self.temp_step - delta, 2)
                if abs(new_step) > TEMP_STEP_MAX:
                    _LOGGER.warning("%s temperature correction %.2f out of range, reset to 0",
                                    self.mac, new_step)
                    new_step = 0.0
                _LOGGER.info("%s temperature step %+.2f °C absorbed, correction %.2f -> %.2f",
                             self.mac, delta, self.temp_step, new_step)
                self.temp_step = new_step
                repairs.raise_temp_step(
                    self.hass, self.entry.entry_id, self.mac, self.name, delta, new_step
                )
        self._prev_raw, self._prev_raw_t = value, now
        value += self.temp_step

        self._window.append(value)
        if len(self._window) >= 3:
            median = statistics.median(self._window)
            if abs(value - median) > TEMP_OUTLIER_RADIUS:
                _LOGGER.debug("%s temperature spike %.2f ignored (median %.2f)",
                              self.mac, value, median)
                value = median
        if self._lowpass is None:
            self._lowpass = value
        else:
            self._lowpass += (value - self._lowpass) / TEMP_LOWPASS_TIME_CONSTANT
        return self._lowpass

    @callback
    def set_temp_step(self, value: float) -> None:
        self.temp_step = round(float(value), 2)
        self._lowpass = None  # restart smoothing at the corrected level
        self._window.clear()
        self._notify()

    # ------------------------------------------------------------ diagnostics
    def diagnostics(self) -> dict[str, Any]:
        return {
            "mac": self.mac,
            "online": self._online,
            "last_rx_age_s": round(time.time() - self._last_rx, 1) if self._last_rx else None,
            "last_realtime_age_s": round(time.time() - self._last_realtime, 1)
            if self._last_realtime else None,
            "update_interval": self.update_interval,
            "temp_step": self.temp_step,
            "data": self.data,
            "sensor_flags": self.sensor_flags,
            "extra": self.extra,
            "wifi": self.wifi,
            "settings_raw": self.settings.raw,
            "last_payloads": self.last_payloads,
        }
