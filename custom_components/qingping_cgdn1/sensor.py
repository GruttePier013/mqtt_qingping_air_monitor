"""Sensors for the Qingping CGDN1."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    MATCH_ALL,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .client import QingpingClient
from .const import THROTTLE_EXTRA, THROTTLE_HOURLY, UNIT_PPM, UNIT_UG_M3
from .entity import QingpingEntity

BATTERY_STATES = {0: "discharging", 1: "charging", 2: "full"}


@dataclass(frozen=True, kw_only=True)
class QingpingSensorDescription(SensorEntityDescription):
    value_fn: Callable[[QingpingClient], Any]
    attrs_fn: Callable[[QingpingClient], dict[str, Any] | None] = lambda c: None
    unique_suffix: str | None = None
    measurement: bool = False          # unavailable while device is offline
    min_interval: float = 0
    unrecorded: frozenset[str] = field(default_factory=frozenset)
    report_every_update: bool = False  # see QingpingEntity._report_every_update


def _data(key: str) -> Callable[[QingpingClient], Any]:
    return lambda c: c.data.get(key)


SENSORS: tuple[QingpingSensorDescription, ...] = (
    # --- measurements -----------------------------------------------------
    QingpingSensorDescription(
        key="temperature", device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        value_fn=_data("temperature"), measurement=True,
    ),
    QingpingSensorDescription(
        key="temperature_unfiltered", device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
        value_fn=_data("temperature_raw"), measurement=True,
    ),
    QingpingSensorDescription(
        key="humidity", device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, value_fn=_data("humidity"), measurement=True,
    ),
    QingpingSensorDescription(
        key="co2", device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UNIT_PPM,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_data("co2"), measurement=True,
    ),
    QingpingSensorDescription(
        key="pm25", device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UNIT_UG_M3,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_data("pm25"), measurement=True,
    ),
    QingpingSensorDescription(
        key="pm10", device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=UNIT_UG_M3,
        state_class=SensorStateClass.MEASUREMENT, value_fn=_data("pm10"), measurement=True,
    ),
    QingpingSensorDescription(
        key="battery", device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=_data("battery"),
        measurement=True, min_interval=THROTTLE_HOURLY,
    ),
    # --- diagnostics ------------------------------------------------------
    QingpingSensorDescription(
        key="status", device_class=SensorDeviceClass.ENUM, options=["online", "offline"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: "online" if c.online else "offline",
        report_every_update=True,  # last message time = state.last_reported
    ),
    QingpingSensorDescription(
        key="battery_state", device_class=SensorDeviceClass.ENUM,
        options=list(BATTERY_STATES.values()), entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: BATTERY_STATES.get(c.data.get("battery_status")),
    ),
    QingpingSensorDescription(
        key="firmware", entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_data("sw_version"),
    ),
    QingpingSensorDescription(
        key="mac_address", unique_suffix="mac", entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.mac,
    ),
    QingpingSensorDescription(
        key="report_type", entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.last_report_type, min_interval=THROTTLE_HOURLY,
    ),
    QingpingSensorDescription(
        # Changes on every message, so every message is a logbook entry (the
        # logbook.exclude config is not applied on device pages). Disabled by
        # default, like core's Z-Wave JS "Last seen"; use Status.last_reported.
        key="last_seen", device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda c: c.last_seen,
        entity_registry_enabled_default=False,
        attrs_fn=lambda c: {
            "last_report_type": c.last_report_type,
            "device_timestamp": c.device_timestamp,
        },
        unrecorded=frozenset({"last_report_type", "device_timestamp"}),
    ),
    QingpingSensorDescription(
        key="wifi_signal", unique_suffix="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.wifi.get("rssi"),
        attrs_fn=lambda c: {k: v for k, v in c.wifi.items() if k != "rssi"},
        unrecorded=frozenset({"wifi_field_3", "hw_version",
                              "module_version", "sw_version", "iot_platform"}),
    ),
    QingpingSensorDescription(
        key="sensor_status", unique_suffix="sensor_health",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: None if not c.sensor_flags else (
            "OK" if all(s in (0, "0") for s in c.sensor_flags.values())
            else "Fault: " + ", ".join(sorted(k for k, s in c.sensor_flags.items() if s not in (0, "0")))
        ),
        attrs_fn=lambda c: dict(c.sensor_flags),
        unrecorded=frozenset({"temperature", "humidity", "co2", "pm25", "pm10"}),
    ),
    QingpingSensorDescription(
        key="co2_calibration_state", unique_suffix="co2_calib_state",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=_data("co2_calib_state"),
    ),
    QingpingSensorDescription(
        key="extra_data", entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: len(c.extra), attrs_fn=lambda c: dict(c.extra),
        min_interval=THROTTLE_EXTRA, unrecorded=frozenset({MATCH_ALL}),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    client: QingpingClient = entry.runtime_data
    entities = []
    for description in SENSORS:
        cls = QingpingSensor
        if description.unrecorded:
            # unrecorded attributes are combined per class by HA
            cls = type(f"QingpingSensor_{description.key}", (QingpingSensor,),
                       {"_unrecorded_attributes": description.unrecorded})
        entities.append(cls(client, description))
    async_add_entities(entities)


class QingpingSensor(QingpingEntity, SensorEntity):
    entity_description: QingpingSensorDescription

    def __init__(self, client: QingpingClient, description: QingpingSensorDescription) -> None:
        super().__init__(client, description.key, description.unique_suffix)
        self.entity_description = description
        self._min_interval = description.min_interval
        self._report_every_update = description.report_every_update
        if description.key == "co2":
            # requested entity id: <device>_carbon_dioxide (only used on first registration)
            self.entity_id = f"sensor.{slugify(client.name)}_carbon_dioxide"

    @property
    def available(self) -> bool:
        if self.entity_description.measurement:
            return self.client.online and self.entity_description.value_fn(self.client) is not None
        return True

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.client)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self.client)
