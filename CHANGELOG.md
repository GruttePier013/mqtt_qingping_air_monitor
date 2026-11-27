# Changelog

## 2.4.0
### Integration
- **Status** is now a connectivity sensor with three states: `realtime` (type-12 realtime reports arrive), `online` (messages arrive, but no realtime reports — history/info only) and `offline` (nothing for 5 min). Realtime counts as lost after max(60 s, 4 × update interval) without a type-12 report.
- Status attributes: `last_report` (time of the last message, ISO), `report_type` (`realtime` / `history` / `device_info` / `settings` / `handshake`), `report_type_code` (`12`, `17`, …), `expected_every_s` (update interval in realtime/offline, device report interval when only online) and `device_timestamp`.
- The separate **Last seen** and **Report type** sensors are removed (config entry 1.2 → 1.3 removes them from the entity registry). Status keeps its entity ID and history.
- No logbook noise: the state only changes on a real transition; `last_report` alone is rewritten at most once a minute (one recorder row per minute), while `last_reported` still follows every message. `last_report` and `device_timestamp` are not recorded.
- **Breaking:** `online` used to mean "any message"; it now means "messages, but not realtime". Automations that test `state == 'online'` should test `state != 'offline'`.

## 2.3.1
### Windows GUI
- Bluetooth state next to *Scan* (on / off / disabled / no adapter / no Bluetooth LE), checked before every action.
- Clear messages for: no adapter or no Bluetooth LE (use another computer or a USB adapter), Bluetooth off, airplane mode / adapter disabled, monitor left pairing mode, no connection; a scan that sees nothing at all is told apart from one that sees other devices but no Qingping.
- *Read from device* renamed *Ask device* (NL *Opvragen*), with a tooltip; reports whether the device's Wi-Fi MAC matches the calculated one. Runs automatically when the list has no Wi-Fi MAC (macOS).
- Wi-Fi and MQTT broker are one required block (old steps 2 and 3); missing fields are listed by name. An empty Wi-Fi password needs confirmation (open network).
- Step 1 shows the integration logo, short instructions (USB power, Wi-Fi pairing mode) and an **NL / EN** language switch at the top right (remembered).
- The MQTT password is shown and remembered (it travels to the device in plain text anyway); the Wi-Fi password stays hidden and is never saved.
- No more "Done, the monitor now connects": the tool reports *Transfer complete* and lists what to check (Wi-Fi icon gone, `New client connected … as qingping-<MAC>` in the Mosquitto log, messages on the topic, device in Home Assistant). Same in the CLI.
- Log area with tabs *Log* and *Bluetooth (raw)* (advertisements, GATT services, every packet written and notification, secrets masked unless shown), plus *Copy* and *Clear*.
### Integration
- Repair issues (offline, sensor fault, temperature step) show the device name as it is in Home Assistant, including a name you gave it yourself, instead of the name from setup (e.g. the MAC suffix).
- Test that guards the translation files against frontend ICU errors (`UNCLOSED_TAG` from `<…>`, unbalanced braces) and checks that all languages have the same keys and placeholders.

## 2.3.0
### Added
- **Windows 11 GUI** for Bluetooth provisioning (`tools/qingping-provision/qingping_provision_gui.py`): scan, pick the monitor, Wi-Fi + broker, check, write with progress. Dutch/English following Windows, high-DPI, passwords never saved.
- `start_gui.bat` (first run sets up a venv), `build_exe.bat`, and a *Windows GUI* workflow that smoke-tests the window and the exe on `windows-latest` and attaches `QingpingProvision.exe` to tagged releases.
### CI
- actions/checkout v5, setup-python v6 (no Node 20 deprecation warning).

## 2.2.4
- hassfest: `network` added to `after_dependencies`; no HTML-like `<MAC>` in translations.
- LICENSE is plain MIT (detectable by GitHub/HACS); third-party notices moved to NOTICE.md.
- CI: tests run with the repository root on the Python path.

## 2.2.3
- Integration icon back to the Air Monitor Lite product image (650 ppm display).
- Repository owner and URLs set (GruttePier013/mqtt_qingping_air_monitor).

## 2.2.2
- Use `UnitOfRatio.PARTS_PER_MILLION` / `UnitOfDensity.MICROGRAMS_PER_CUBIC_METER` on newer Home Assistant (no deprecation warnings), with a fallback to the old `CONCENTRATION_*` constants on older cores.
- Device registry lookup is limited to the integration's own config entry.

## 2.2.1
- *Update interval* (step 5 s) and *Timezone* (step 1 h) are now sliders instead of input boxes.

## 2.2.0
### Changed
- **No more "Last seen" logbook spam.** The Status sensor is re-reported on every message with an
  unchanged state, so Home Assistant only bumps `state.last_reported` (no state_changed event, no
  logbook entry, no recorder row). The "Last seen" sensor is now disabled by default; a one-time
  migration (config entry 1.1 → 1.2) disables it on existing installs. It can be re-enabled.
- Docs: `logbook: exclude` is not applied on device pages; a Markdown card example shows the last message time.

## 2.1.0
### Added
- **Bluetooth provisioning from Home Assistant:** a CGDN1 in pairing mode is discovered over BLE
  (local adapter or ESPHome proxy with active connections). A config flow writes Wi-Fi, broker and
  topics to the device, waits for its first MQTT message and adds it. No Qingping account or cloud.
  The Wi-Fi MAC is derived from the Bluetooth MAC (minus 2).
- Secrets are entered in the flow only: never stored in the config entry, never logged. Deliberately
  not an action, because action data is recorded as `call_service` events.
- `tools/qingping-provision`: a cross-platform CLI (Windows, macOS, Linux; bleak) using the same
  protocol module, with `scan`, `provision`, `--dry-run`, hidden password prompts and `--read-wifi-mac` for macOS.
- `ble_provision.py`: an independent MIT implementation of the BLE setup protocol, with no HA imports.
### Docs
- README and Dutch guide: Bluetooth routes, Windows instructions, TLS/HTTPS FAQ.

## 2.0.2
### Privacy
- SSID and BSSID from the device's type-13 `wifi_info` are no longer stored anywhere (not in
  attributes, memory or diagnostics); only RSSI is kept.
- Diagnostics additionally redact `wifi_info`, `ssid` and `bssid`.
### Repository
- First public release layout: docs (protocol, privacy, Dutch guide), examples, CI.
- Bundled the offline BLE provisioning tool (bitrate16/qingping, AGPL-3.0, unmodified) under `tools/`.
- New original icon (no vendor product imagery).

## 2.0.1
- Integration renamed to "QingPing CGDN1".

## 2.0.0
- Rewrite: listener-based client without a polling coordinator.
- MQTT discovery (`qingping/+/up`) and a manual flow with MAC validation.
- Verified settings writes (type 28 read → merged type 17 → type 28 verification).
- Realtime arming with a watchdog; history interval reduced to one hour; stale history ignored.
- Temperature filter (step correction, outlier removal, low-pass) with a repair issue and reset.
- Repairs: offline (also for never-seen devices), sensor fault, temperature step.
- Automatic timezone and DST.
- Diagnostics, recorder hygiene (throttling, unrecorded attributes), Dutch translation.
- Entity ID migrations from 1.x.
