"""Repair issues + fix flows for Qingping CGDN1."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN


def issue_id(kind: str, mac: str) -> str:
    return f"{kind}_{mac}"


@callback
def raise_temp_step(hass: HomeAssistant, entry_id: str, mac: str, name: str, delta: float, correction: float) -> None:
    """(Re)create the fixable 'temperature step' issue with the latest values."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id("temp_step", mac),
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="temp_step",
        translation_placeholders={
            "name": name,
            "delta": f"{delta:+.2f}",
            "correction": f"{correction:+.2f}",
            "time": dt_util.now().strftime("%d-%m %H:%M"),
        },
        data={"entry_id": entry_id, "mac": mac},
    )


@callback
def raise_offline(hass: HomeAssistant, mac: str, name: str, minutes: int) -> None:
    ir.async_create_issue(
        hass, DOMAIN, issue_id("offline", mac),
        is_fixable=False, severity=ir.IssueSeverity.WARNING,
        translation_key="offline",
        translation_placeholders={"name": name, "minutes": str(minutes), "mac": mac},
    )


@callback
def raise_sensor_fault(hass: HomeAssistant, mac: str, name: str, sensors: str) -> None:
    ir.async_create_issue(
        hass, DOMAIN, issue_id("sensor_fault", mac),
        is_fixable=False, severity=ir.IssueSeverity.WARNING,
        translation_key="sensor_fault",
        translation_placeholders={"name": name, "sensors": sensors},
    )


@callback
def clear(hass: HomeAssistant, kind: str, mac: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, issue_id(kind, mac))


@callback
def clear_all(hass: HomeAssistant, mac: str) -> None:
    for kind in ("temp_step", "offline", "sensor_fault"):
        clear(hass, kind, mac)


class TempStepRepairFlow(RepairsFlow):
    """Acknowledge a temperature step, optionally reset the correction."""

    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data or {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input.get("reset"):
                entry = self.hass.config_entries.async_get_entry(self._data.get("entry_id", ""))
                client = getattr(entry, "runtime_data", None) if entry else None
                if client is not None:
                    client.set_temp_step(0.0)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Optional("reset", default=False): bool}),
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    return TempStepRepairFlow(data)
