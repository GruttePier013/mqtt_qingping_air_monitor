# CGDN1 protocol notes

This page collects what is known about the MQTT JSON protocol of the Qingping Air Monitor Lite (CGDN1).
Sources: Qingping's public MQTT JSON documentation (developer.qingping.co), traffic observed on
firmware 4.8.5, and community research (credited at the end). "Observed" means that it was seen on
real devices but is not in Qingping's documentation.

## Topics

| Direction | Topic | Notes |
|---|---|---|
| device → broker | `qingping/<MAC>/up` | `<MAC>` = Wi-Fi MAC, 12 upper-case hex characters |
| broker → device | `qingping/<MAC>/down` | |

The topic names come from the Private Access configuration (portal) or from the BLE provisioning
(see [tools/qingping-ble-setup](../tools/qingping-ble-setup/README.md)). This integration expects the
`qingping/<MAC>/…` layout. With portal provisioning, the device was observed connecting with client ID
`qingping-<MAC>`.

## Message types

| Type | Dir | Meaning | Integration behaviour |
|---|---|---|---|
| `10` | up | "Which BLE sub-devices do you have?" Sent after connecting. | Answers `11` at once. **Without an answer the device sends no data.** |
| `11` | down | Answer to 10, also syncs the clock. | `{"type":"11","code":0,"desc":"","dev_list":["FFFFFFFFFFFF"],"timestamp":<now>}` |
| `12` | down | Arm realtime reporting. | `{"type":"12","up_itvl":"15","duration":"3600"}`, re-armed every 55 min and by a watchdog |
| `12` | up | Realtime `sensorData` (one entry). | Main data source |
| `13` | up | Device info, about every minute (observed, undocumented). | Firmware and hardware version → device registry; RSSI. `hk_salt`, SSID and BSSID are discarded. |
| `17` | up | Stored history (`sensorData` list), `need_ack: 1`. | Acked with `18`. Entries older than 120 s don't change the live state. |
| `17` | down | Write settings: `{"type":"17","setting":{…}}`. | Always the **complete merged** object, from a fresh `28` read |
| `18` | down | Ack history: `{"type":"18","ack_id":<id>,"code":0,"desc":"","timestamp":<now>}` | |
| `28` | down | Query settings: `{"type":"28"}` | Hourly, before every write, and after writes for verification |
| `28` | up | Current settings (`setting` object). | Source of truth for all configuration entities |
| `23` | down | **Firmware update from URL** (observed in firmware analysis). | **Never sent.** See the security note below. |
| `24` | up | OTA progress or status (observed in firmware analysis). | Ignored |

### `sensorData` (types 12 and 17)

```json
{
  "type": "12", "id": 123, "mac": "7CC29400BEEF", "need_ack": 0, "timestamp": 1764173842,
  "sensorData": [{
    "timestamp":   {"value": 1764173840},
    "temperature": {"value": 22.56, "status": 0},
    "humidity":    {"value": 45.07, "status": 0},
    "co2":         {"value": 635,   "status": 0},
    "pm25":        {"value": 1,     "status": 0},
    "pm10":        {"value": 3,     "status": 0},
    "battery":     {"value": 100}
  }]
}
```

- `status` ≠ 0 means a sensor fault or warm-up. The integration shows it in *Sensor status* and raises a repair issue.
- Unknown keys are kept as attributes of *Extra data* and logged once at INFO level.

### Type 13 (device info)

```json
{"type": "13", "wifi_mac": "7CC29400BEEF", "sw_version": "4.8.5", "module_version": "4.8.5",
 "hw_version": "0001", "iot_platform": 0, "timezone": 10, "timestamp": 1764173842,
 "wifi_info": "<ssid>,<rssi>,<n>,<bssid>", "hk_salt": "<redacted>"}
```

`wifi_info` is comma separated, and the SSID itself may contain commas, so it is parsed from the
right. `hk_salt` belongs to HomeKit pairing. Both are privacy-sensitive; see [PRIVACY.md](PRIVACY.md).

## Settings (type 28 / 17)

Full `setting` object as reported by a CGDN1:

| Key | Example | Scale / meaning | Exposed as |
|---|---|---|---|
| `temperature_unit` | `"C"` | `C` / `F` (display) | select |
| `report_interval` | `900` | s, history upload interval | managed (set to 3600) |
| `collect_interval` | `900` | s, history sample interval | managed (set to 3600) |
| `pm_sampling_interval` | `1` | undocumented unit | number (disabled) |
| `co2_sampling_interval` | – | undocumented, only on some firmware | number (disabled) |
| `power_off_time` | `30` | min, battery only, 0 = never | number |
| `night_mode_start_time` | `1260` | minutes after midnight | time |
| `night_mode_end_time` | `360` | minutes after midnight | time |
| `display_off_time` | `30` | s, **ignored by recent firmware** | number |
| `auto_slideing_time` | `30` | s, screensaver delay (sic: "slideing") | number |
| `timezone` | `10` | hours × 10 | number (auto-managed) |
| `screensaver_type` | `1` | 0 rotating, 1 current, 2 clock + rotating, 3 clock + current | select |
| `is_12_hour_mode` | `0` | 0 = 24h | select |
| `pm25_standard` | `0` | colour standard for PM levels | – |
| `need_ack` | `1` | report-only, stripped before writing | – |
| `co2_asc` | `1` | automatic baseline calibration | switch |
| `co2_offset` | `0` | ppm | number |
| `co2_zoom` | `0` | % × 10 | number |
| `pm25_offset` / `pm10_offset` | `0` | µg/m³ | number |
| `pm25_zoom` / `pm10_zoom` | `0` | % × 10 | – |
| `pm25_calib_mode` | `0` | unknown | – |
| `temperature_offset` | `-50` | °C × 100 | number |
| `temperature_zoom` | `0` | % × 10 (assumed) | number |
| `humidity_offset` | `0` | % × 10 | number |
| `humidity_zoom` | `0` | % × 10 | – |
| `page_sequence` | `"pm25,pm10,co2,temp,pm25"` | screen page order | – |
| `temp_led_th` | `"2300,2650,2800"` | LED thresholds, °C × 100 | – |
| `humi_led_th` | `"2000,4000,6000"` | LED thresholds, % × 100 | – |
| `co2_led_th` | `"1000,2000,3000"` | LED thresholds, ppm | – |
| `pm25_led_th` / `pm10_led_th` | `"35,75,115,150,250"` | LED thresholds | – |

**Not available:** a setting to turn off the LED, Wi-Fi or Bluetooth. There is no BLE-related key at all.

### Write procedure used by this integration

1. Query `28` and wait for the answer (10 s timeout).
2. Merge the requested change into that fresh snapshot and drop `need_ack`.
3. Skip the write if the device already has the value.
4. Send `17` with the complete object.
5. Wait for a `28` that contains the new values (15 s). Only then is the write treated as successful.
   Otherwise the entity reverts and an error is shown.

## Bluetooth (GATT) provisioning interface

In pairing mode (hold the top bar about 8 s) the device exposes service
`22210000-554a-4546-5542-46534450464d` for setup. Packets are `<len><type><data>`, written in chunks of 20 bytes.

| Characteristic (write / notify) | Type | Payload |
|---|---|---|
| `0x000D` / `0x000E` | `0x01` | Wi-Fi: `"ssid","password"` |
| `0x000D` / `0x000E` | `0x04`, `0x07` | Wi-Fi scan (simple / detailed) |
| `0x000D` / `0x000E` | `0x08` | read Bluetooth MAC |
| `0x0001` / `0x0002` | `0x01` + `0x02` | link token (16 bytes) |
| `0x0001` / `0x0002` | `0x17` | MQTT: `host port login password` (space separated) |
| `0x0001` / `0x0002` | `0x18` | MQTT topics: `client_id read_topic write_topic` |
| `0x0017` / `0x0018` | `0x0B` / `0x0C` | read Wi-Fi / Bluetooth MAC |
| `0x0017` / `0x0018` | `0x02` / `0x03` | screen normal / black |

The **Wi-Fi MAC is the Bluetooth MAC minus 2** (confirmed on the CGDN1), so the topic MAC can be derived
from the BLE address. Writes are not acknowledged; success shows as the first MQTT message.
An independent MIT implementation lives in `custom_components/qingping_cgdn1/ble_provision.py`.

There is no known command to switch to HomeKit, enable TLS or disable Bluetooth. Cloud-provisioned devices get
Qingping's own broker (`mqtt.bj.cleargrass.com`, port 11883) with Alibaba IoT-style client IDs through
this same interface.

## ⚠️ Security note: OTA over MQTT

Analysis of the stock 4.8.x firmware shows that a type `23` message on the down topic
(`{"type":"23","url":"http://…","ota_type":1}`) makes the device download the URL, write it to the
inactive slot and reboot into it. It checks **only a CRC-32 trailer, not a signature**, and there is no
rollback. `ota_type` 0 targets the co-processor and 5 "HomeKit info".

Consequences:
- Write access to `qingping/+/down` gives full control over the device. Restrict it with an ACL.
- This integration never sends type 23 or anything that could trigger it.

## Credits

- Qingping public MQTT JSON protocol (developer.qingping.co).
- [bitrate16/qingping](https://github.com/bitrate16/qingping): BLE GATT protocol.
- [nemethhh/esphome-qingping-cgdn1](https://github.com/nemethhh/esphome-qingping-cgdn1): stock firmware analysis, type 23 OTA.
- [mash2k3/qingping_cgs1 discussion #57](https://github.com/mash2k3/qingping_cgs1/discussions/57): full CGDN1 settings dump, `display_off_time` and `screensaver_type` findings.
