"""Constants for the Qingping CGDN1 integration."""
from __future__ import annotations

import re

DOMAIN = "qingping_cgdn1"
MANUFACTURER = "Qingping"
MODEL = "CGDN1 Air Monitor Lite"

CONF_MAC = "mac"
CONF_NAME = "name"
CONF_UPDATE_INTERVAL = "update_interval"

MQTT_TOPIC_PREFIX = "qingping"
MQTT_DISCOVERY_TOPIC = f"{MQTT_TOPIC_PREFIX}/+/up"

# Realtime reporting (protocol 3.2): up_itvl > 2 s, duration 60-3600 s.
DEFAULT_UPDATE_INTERVAL = 15
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 120
REALTIME_DURATION = 3600
REALTIME_REARM = REALTIME_DURATION - 300

# Liveness / watchdog
WATCHDOG_INTERVAL = 60          # s
OFFLINE_TIMEOUT = 300           # s without any message -> offline + repair issue
HISTORY_MAX_AGE = 120           # s; older type-17 entries are acked but ignored

# Temperature filtering (applied to the main temperature entity)
TEMP_STEP_THRESHOLD = 1.0       # °C between consecutive samples = artefact
TEMP_STEP_MAX_GAP = 120         # s; larger gaps may hold a real change
TEMP_STEP_MAX = 5.0             # °C; larger accumulated correction -> reset
TEMP_OUTLIER_WINDOW = 6         # samples
TEMP_OUTLIER_RADIUS = 0.5       # °C from window median = spike
TEMP_LOWPASS_TIME_CONSTANT = 4  # samples

# Write throttling for slow-changing entities
THROTTLE_HOURLY = 3600
THROTTLE_EXTRA = 300

KNOWN_PAYLOAD_KEYS = {
    "type", "mac", "version", "timestamp", "sensorData", "id", "need_ack", "timezone",
}
KNOWN_SENSOR_KEYS = {
    "battery", "temperature", "humidity", "co2", "pm25", "pm10", "timestamp",
}
KNOWN_SUB_KEYS = {"value", "status", "unit", "co2_calib_state"}

_MAC_RE = re.compile(r"^[0-9A-F]{12}$")


def normalize_mac(mac: str) -> str:
    """Return MAC as upper-case hex without separators (as the device sends it)."""
    return "".join(ch for ch in str(mac) if ch.isalnum()).upper()


def is_valid_mac(mac: str) -> bool:
    return bool(_MAC_RE.match(normalize_mac(mac)))


# Units: HA 2026.x replaces the CONCENTRATION_* constants with UnitOfRatio /
# UnitOfDensity. Use the new names where available (no deprecation warning)
# and fall back for older cores. The string values are identical.
try:
    from homeassistant.const import UnitOfDensity, UnitOfRatio

    UNIT_PPM: str = UnitOfRatio.PARTS_PER_MILLION
    UNIT_UG_M3: str = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
except ImportError:  # pragma: no cover - older Home Assistant
    from homeassistant.const import (
        CONCENTRATION_MICROGRAMS_PER_CUBIC_METER as UNIT_UG_M3,
        CONCENTRATION_PARTS_PER_MILLION as UNIT_PPM,
    )
