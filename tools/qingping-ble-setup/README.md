# Offline BLE provisioning for the CGDN1 (original Linux tool)

> **Looking for Windows/macOS, or setup straight from Home Assistant?** Use
> [`tools/qingping-provision`](../qingping-provision/README.md) or the integration's Bluetooth
> discovery. This folder keeps the original tool, which needs Linux and `gatttool`.

This folder contains **[bitrate16/qingping](https://github.com/bitrate16/qingping)**, shipped
**unmodified** (see [UPSTREAM.md](UPSTREAM.md)). It points a Qingping Air Monitor Lite at your own MQTT
broker over Bluetooth: **no Qingping account, no app, no cloud**.

- License: **AGPL-3.0-or-later**, © 2025 bitrate16 (see [LICENSE](LICENSE)). This is separate from the MIT-licensed integration.
- Upstream documentation: [README.upstream.md](README.upstream.md), [bluetooth.md](bluetooth.md) (protocol), [pipeline.md](pipeline.md).
- The Home Assistant integration does **not** use or import this tool. You run it once per device from a computer.

## What it does

While the monitor is in pairing mode, the tool connects to its BLE setup service and writes, in this order:

1. **Wi-Fi** network name and password
2. a 16-byte **link token** (used by the app for the cloud; any random value works for your own broker)
3. **MQTT broker**: host, port, username, password
4. **MQTT topics**: client ID, the topic the device *reads* (down) and the topic it *writes* (up)

The monitor then joins Wi-Fi and starts publishing to your broker.

### What it does *not* do

- **HomeKit:** there is no BLE command to switch the monitor to HomeKit. HomeKit is a separate pairing
  route: reset the network settings and add the monitor in the Apple Home app.
- **Settings** such as offsets or night mode: those go over MQTT once the device is connected, and the
  Home Assistant integration handles them.
- **Firmware updates.**
- **Disabling Bluetooth or the LED:** no such command is known.

## Requirements

- **Linux** with BlueZ and the **`gatttool`** binary. The tool uses `pygatt`'s GATTTool backend through
  `pexpect`. On some distributions `gatttool` comes in a separate "deprecated tools" package.
  A Raspberry Pi works well. Windows and macOS are **not** supported by this backend.
- Python 3.10 or newer.
- The monitor within a few metres.

```bash
cd tools/qingping-ble-setup
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
which gatttool          # must print a path
```

## Step by step

### 1. Pairing mode

Hold the **top touch bar for about 8 seconds** until a large Wi-Fi icon appears. This resets the
network settings and opens the BLE setup service.

### 2. Find the Bluetooth MAC

```bash
bluetoothctl --timeout 15 scan on | grep -i qingping
# Device 7C:C2:94:00:BE:F1 Qingping Air Monitor Lite
```

### 3. Work out the Wi-Fi MAC

The MQTT topics use the **Wi-Fi MAC**, which differs from the Bluetooth MAC. On the CGDN1 the
Bluetooth MAC is the Wi-Fi MAC **+ 2** (confirmed):

| Bluetooth MAC | Wi-Fi MAC (topic) |
|---|---|
| `7C:C2:94:00:BE:F1` | `7CC29400BEEF` |

The `qingping_mac_helper.py` script in this folder does the arithmetic:

```bash
python3 qingping_mac_helper.py 7C:C2:94:00:BE:F1
```

### 4. Provision

```bash
python3 -m qingping.bluetooth --verbose \
  --mac 7C:C2:94:00:BE:F1 \
  --wifi-ssid "MyIoTNetwork" --wifi-password "wifi-password" \
  --link-token "$(python3 -c 'import secrets; print(secrets.token_hex(16))')" \
  --mqtt-host 192.0.2.10 --mqtt-port 1883 \
  --mqtt-login qingping --mqtt-password 'broker-password' \
  --mqtt-client qingping-7CC29400BEEF \
  --mqtt-read  qingping/7CC29400BEEF/down \
  --mqtt-write qingping/7CC29400BEEF/up
```

| Argument | Value for this integration |
|---|---|
| `--mac` | **Bluetooth** MAC (with colons) |
| `--mqtt-client` | `qingping-<WIFI_MAC>`, the same as what portal-provisioned devices use |
| `--mqtt-read` | `qingping/<WIFI_MAC>/down`: what the **device** subscribes to |
| `--mqtt-write` | `qingping/<WIFI_MAC>/up`: what the **device** publishes to |
| `--mqtt-host` | the broker's **LAN IP** (a hostname works only if the device can resolve it) |

> With `--verbose` the Wi-Fi and MQTT passwords are printed. Clear your terminal history if needed.

### 5. Verify

Subscribe to everything from the monitors:

```bash
mosquitto_sub -h 192.0.2.10 -u homeassistant -P '…' -t 'qingping/#' -v
```

Within about a minute you should see a type 13 message on `qingping/7CC29400BEEF/up`. Check that its
`wifi_mac` field equals the MAC in the topic. If it doesn't, or messages arrive on a different topic,
put the monitor back in pairing mode and run step 4 again with the correct Wi-Fi MAC.

Then add the device in Home Assistant (it appears under *Discovered*).

## Known limitations of the upstream tool

Shipped as is. Known quirks, which don't affect the normal provisioning flow:

- `DataPacket.parse_packets()` and the error branch of `make_packet()` refer to undefined names.
  Neither is used by the CLI.
- The CLI writes but does not wait for or check confirmations from the device. Verify with MQTT as in step 5.
- Tested by its author on the CGDN1. Other models or firmware versions may behave differently.
  Use at your own risk.

## Security notes

- The BLE setup service is only open in pairing mode, so physical access is needed. Don't leave a
  unit in pairing mode unattended.
- With this route your broker credentials never reach Qingping. See [docs/PRIVACY.md](../../docs/PRIVACY.md).
