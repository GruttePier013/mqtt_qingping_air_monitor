# Changelog

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
