"""Config flow for Qingping CGDN1.

* MQTT auto-discovery (``qingping/+/up``), MQTT scan and manual entry;
* Bluetooth: a monitor in pairing mode is discovered and provisioned to the
  local broker (Wi-Fi + MQTT written over BLE), then added once it publishes.
  Secrets are entered in the flow only: they are never stored in the config
  entry, logged, or fired in events (unlike action/service data).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .ble_provision import (
    LOCAL_NAME,
    ProvisionConfig,
    ProvisioningError,
    provision,
    wifi_mac_from_ble,
)

from .const import (
    CONF_MAC,
    CONF_NAME,
    DOMAIN,
    MQTT_DISCOVERY_TOPIC,
    MQTT_TOPIC_PREFIX,
    is_valid_mac,
    normalize_mac,
)

_LOGGER = logging.getLogger(__name__)
SCAN_SECONDS = 10
BT_WAIT_SECONDS = 120   # device joins Wi-Fi + broker after provisioning

CONF_WIFI_SSID = "wifi_ssid"
CONF_WIFI_PASSWORD = "wifi_password"
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
LOCAL_BROKER_NAMES = {"core-mosquitto", "localhost", "127.0.0.1", "::1", "homeassistant", "homeassistant.local"}


def _default_name(mac: str) -> str:
    return f"Qingping {mac[-4:]}"


class QingpingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Qingping CGDN1."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._mac: str | None = None
        self._found: dict[str, str] = {}
        # Bluetooth provisioning
        self._ble_address: str | None = None
        self._bt_name: str | None = None
        self._bt_config: ProvisionConfig | None = None
        self._bt_defaults: dict[str, Any] = {}
        self._bt_error: str | None = None
        self._bt_task: asyncio.Task | None = None
        self._wait_task: asyncio.Task | None = None
        # HA re-sends the last form input to the step after SHOW_PROGRESS_DONE;
        # steps reached that way must not treat it as a submission.
        self._drop_input = False

    # ---------------------------------------------------- MQTT discovery
    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """A Qingping published on qingping/<MAC>/up (manifest 'mqtt' key)."""
        parts = discovery_info.topic.split("/")
        mac = normalize_mac(parts[1]) if len(parts) == 3 else ""
        if not is_valid_mac(mac):
            return self.async_abort(reason="invalid_discovery_info")
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        self._mac = mac
        self.context["title_placeholders"] = {"name": _default_name(mac)}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._mac is not None
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_MAC: self._mac, CONF_NAME: user_input[CONF_NAME]},
            )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=_default_name(self._mac)): str}),
            description_placeholders={"mac": self._mac},
        )

    # ------------------------------------------------------- user: scan
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_create(user_input)

        await self._async_scan()
        if not self._found:
            return await self.async_step_manual()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_MAC): vol.In(self._found),
                vol.Required(CONF_NAME): str,
            }),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not is_valid_mac(user_input[CONF_MAC]):
                errors[CONF_MAC] = "invalid_mac"
            else:
                return await self._async_create(user_input)
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MAC): str,
            }),
            errors=errors,
        )

    async def _async_create(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        mac = normalize_mac(user_input[CONF_MAC])
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()  # AbortFlow propagates: proper message
        return self.async_create_entry(
            title=user_input[CONF_NAME], data={CONF_MAC: mac, CONF_NAME: user_input[CONF_NAME]}
        )

    async def _async_scan(self) -> None:
        """Listen briefly for qingping/<MAC>/up messages."""
        configured = {e.unique_id for e in self._async_current_entries(include_ignore=False)}

        @callback
        def _on_message(msg) -> None:
            parts = msg.topic.split("/")
            mac = normalize_mac(parts[1]) if len(parts) == 3 else ""
            if is_valid_mac(mac) and mac not in configured:
                self._found.setdefault(mac, f"Qingping CGDN1 ({mac})")

        try:
            unsub = await mqtt.async_subscribe(self.hass, MQTT_DISCOVERY_TOPIC, _on_message)
        except Exception as err:  # noqa: BLE001 - MQTT not ready: fall back to manual
            _LOGGER.debug("MQTT scan not possible: %s", err)
            return
        try:
            await asyncio.sleep(SCAN_SECONDS)
        finally:
            unsub()

    # ------------------------------------------------ Bluetooth provisioning
    async def async_step_bluetooth(self, discovery_info: Any) -> ConfigFlowResult:
        """A CGDN1 advertises over BLE (manifest 'bluetooth' matcher)."""
        try:
            mac = wifi_mac_from_ble(discovery_info.address)
        except ProvisioningError:
            return self.async_abort(reason="invalid_discovery_info")
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        self._mac = mac
        self._ble_address = discovery_info.address
        self.context["title_placeholders"] = {"name": _default_name(mac)}
        return await self.async_step_bt_setup()

    async def async_step_bt_setup(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for Wi-Fi and broker details (secrets stay in this flow only)."""
        assert self._mac is not None
        if self._drop_input:
            self._drop_input, user_input = False, None
        errors: dict[str, str] = {}
        if self._bt_error:
            errors["base"] = "ble_failed"
        if user_input is not None:
            self._bt_defaults = {k: v for k, v in user_input.items()
                                 if k not in (CONF_WIFI_PASSWORD, CONF_MQTT_PASSWORD)}
            try:
                config = ProvisionConfig.for_wifi_mac(
                    self._mac,
                    wifi_ssid=user_input[CONF_WIFI_SSID],
                    wifi_password=user_input.get(CONF_WIFI_PASSWORD, ""),
                    mqtt_host=user_input[CONF_MQTT_HOST].strip(),
                    mqtt_port=int(user_input[CONF_MQTT_PORT]),
                    mqtt_username=user_input[CONF_MQTT_USERNAME].strip(),
                    mqtt_password=user_input[CONF_MQTT_PASSWORD],
                    prefix=MQTT_TOPIC_PREFIX,
                )
                config.validate()
            except (ProvisioningError, ValueError) as err:
                errors["base"] = "invalid_provisioning"
                self._bt_error = str(err)
            else:
                self._bt_name = user_input[CONF_NAME]
                self._bt_config = config
                self._bt_error = None
                return await self.async_step_bt_write()

        defaults = self._bt_defaults or await self._async_bt_defaults()
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, _default_name(self._mac))): str,
            vol.Required(CONF_WIFI_SSID, default=defaults.get(CONF_WIFI_SSID, "")): str,
            vol.Optional(CONF_WIFI_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Required(CONF_MQTT_HOST, default=defaults.get(CONF_MQTT_HOST, "")): str,
            vol.Required(CONF_MQTT_PORT, default=defaults.get(CONF_MQTT_PORT, 1883)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(CONF_MQTT_USERNAME, default=defaults.get(CONF_MQTT_USERNAME, "qingping")): str,
            vol.Required(CONF_MQTT_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        })
        return self.async_show_form(
            step_id="bt_setup",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "mac": self._mac,
                "ble_address": self._ble_address or "",
                "error": self._bt_error or "",
            },
        )

    async def async_step_bt_write(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Connect over BLE and write the configuration."""
        if self._bt_task is None:
            self._bt_task = self.hass.async_create_task(self._async_ble_write())
        if not self._bt_task.done():
            return self.async_show_progress(
                step_id="bt_write", progress_action="writing", progress_task=self._bt_task)
        task, self._bt_task = self._bt_task, None
        try:
            task.result()
        except Exception as err:  # noqa: BLE001 - shown to the user, flow restarts at the form
            _LOGGER.warning("Qingping %s: Bluetooth provisioning failed: %s", self._mac, err)
            self._bt_error = str(err) or type(err).__name__
            self._drop_input = True
            return self.async_show_progress_done(next_step_id="bt_setup")
        return self.async_show_progress_done(next_step_id="bt_wait")

    async def async_step_bt_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Wait for the first MQTT message from the freshly provisioned device."""
        if self._wait_task is None:
            self._wait_task = self.hass.async_create_task(self._async_wait_for_mqtt())
        if not self._wait_task.done():
            return self.async_show_progress(
                step_id="bt_wait", progress_action="waiting", progress_task=self._wait_task,
                description_placeholders={"topic": f"{MQTT_TOPIC_PREFIX}/{self._mac}/up"})
        task, self._wait_task = self._wait_task, None
        heard = False
        try:
            heard = bool(task.result())
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Qingping %s: waiting for MQTT failed: %s", self._mac, err)
        self._drop_input = True
        return self.async_show_progress_done(next_step_id="bt_finish" if heard else "bt_timeout")

    async def async_step_bt_timeout(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """No message yet: explain, offer to add the device anyway."""
        if self._drop_input:
            self._drop_input, user_input = False, None
        if user_input is not None:
            return await self.async_step_bt_finish()
        return self.async_show_form(
            step_id="bt_timeout",
            data_schema=vol.Schema({}),
            description_placeholders={"topic": f"{MQTT_TOPIC_PREFIX}/{self._mac}/up",
                                      "seconds": str(BT_WAIT_SECONDS)},
        )

    async def async_step_bt_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._mac is not None
        self._drop_input = False
        name = self._bt_name or _default_name(self._mac)
        self._bt_config = None  # drop secrets
        return self.async_create_entry(title=name, data={CONF_MAC: self._mac, CONF_NAME: name})

    async def _async_ble_write(self) -> None:
        """Connect to the monitor (local adapter or ESPHome proxy) and provision it."""
        from bleak_retry_connector import (  # noqa: PLC0415 - only needed for BLE setups
            BleakClientWithServiceCache,
            establish_connection,
        )

        from homeassistant.components import bluetooth  # noqa: PLC0415

        assert self._ble_address is not None and self._bt_config is not None
        device = bluetooth.async_ble_device_from_address(self.hass, self._ble_address, connectable=True)
        if device is None:
            raise ProvisioningError(
                "monitor not reachable over Bluetooth: it needs a connectable adapter or an "
                "ESPHome Bluetooth proxy with active connections, and must be in pairing mode")
        _LOGGER.debug("Qingping %s: provisioning %s", self._mac, self._bt_config.redacted())
        client = await establish_connection(
            BleakClientWithServiceCache, device, LOCAL_NAME, use_services_cache=False)
        try:
            await provision(client, self._bt_config)
        finally:
            await client.disconnect()

    async def _async_wait_for_mqtt(self) -> bool:
        """True as soon as anything arrives on qingping/<MAC>/up."""
        heard: asyncio.Future[bool] = self.hass.loop.create_future()

        @callback
        def _on_message(_msg) -> None:
            if not heard.done():
                heard.set_result(True)

        unsub = await mqtt.async_subscribe(
            self.hass, f"{MQTT_TOPIC_PREFIX}/{self._mac}/up", _on_message)
        try:
            return await asyncio.wait_for(heard, BT_WAIT_SECONDS)
        except TimeoutError:
            return False
        finally:
            unsub()

    async def _async_bt_defaults(self) -> dict[str, Any]:
        """Prefill broker host/port from HA's MQTT entry (LAN IP for the add-on)."""
        host, port = "", 1883
        entries = self.hass.config_entries.async_entries("mqtt")
        if entries:
            host = str(entries[0].data.get("broker", ""))
            port = int(entries[0].data.get("port", 1883) or 1883)
        if not host or host.lower() in LOCAL_BROKER_NAMES:
            try:
                from homeassistant.components import network  # noqa: PLC0415

                host = await network.async_get_source_ip(self.hass)
            except Exception:  # noqa: BLE001 - leave empty, user fills it in
                host = ""
        return {CONF_MQTT_HOST: host, CONF_MQTT_PORT: port}
