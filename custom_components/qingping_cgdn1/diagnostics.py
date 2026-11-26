"""Diagnostics for Qingping CGDN1 (Settings > Devices > ... > Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

TO_REDACT = {"hk_salt", "password", "wifi_info", "ssid", "bssid"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    client = entry.runtime_data
    return {
        "entry": {"title": entry.title, "data": dict(entry.data), "version": entry.version},
        "client": async_redact_data(client.diagnostics(), TO_REDACT),
    }
