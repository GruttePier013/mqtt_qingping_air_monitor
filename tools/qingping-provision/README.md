# qingping-provision: Bluetooth setup for Windows, macOS and Linux

Points a Qingping Air Monitor Lite (CGDN1) at **your own MQTT broker** over Bluetooth. You don't need
a Qingping account, the app or the cloud. It is cross-platform thanks to
[bleak](https://github.com/hbldh/bleak), and MIT licensed.

> **Easiest:** you don't need this tool if Home Assistant has Bluetooth (a local adapter or an
> **ESPHome Bluetooth proxy with active connections**). Put the monitor in pairing mode and it
> appears under *Settings → Devices & services → Discovered*, where the integration provisions it
> for you. Use this tool when Home Assistant has no Bluetooth near the monitor.

It uses the same protocol code as the integration (`custom_components/qingping_cgdn1/ble_provision.py`).

## Windows 11 app (GUI)

The simplest way on Windows:

| Option | How |
|---|---|
| **Ready-made app** | Download `QingpingProvision.exe` from the [releases](https://github.com/GruttePier013/mqtt_qingping_air_monitor/releases) (or the *Windows GUI* workflow artifact) and double-click it. No Python needed. |
| **From the repo** | Double-click `start_gui.bat`. The first start creates a local Python environment and installs `bleak`, then the window opens. Needs Python 3.11+ from python.org. |
| **Build it yourself** | `build_exe.bat` → `dist\QingpingProvision.exe` (PyInstaller). |

The window has three steps:

1. **Monitor:** put it in pairing mode, click **Scan**, and pick it from the list. The Wi-Fi MAC
   (Bluetooth MAC − 2) is filled in automatically; *Read from device* asks the monitor itself.
2. **Wi-Fi network:** SSID and password (2.4 GHz).
3. **MQTT broker:** LAN IP, port, user and password for the monitor.

**Check** validates and shows the configuration (passwords hidden). **Write to monitor** provisions
it, with progress in the log. The language follows Windows (Dutch or English; `--lang en|nl` to force).

Passwords are never saved. Network name, broker, port, user and prefix are remembered in
`%APPDATA%\QingpingProvision\settings.json`. Windows SmartScreen may warn about the unsigned exe:
*More info → Run anyway*.

## Command line

### Install

#### Windows 10/11

1. Install Python 3.11 or newer from <https://www.python.org/downloads/> (tick *Add python.exe to PATH*).
2. Make sure Bluetooth is on (Settings → Bluetooth & devices).
3. In a terminal, from the repository folder:

```powershell
cd tools\qingping-provision
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

#### macOS / Linux

```bash
cd tools/qingping-provision
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

On macOS, allow Bluetooth access for your terminal app when asked. On Linux, BlueZ must be running.

### Use

**1. Pairing mode:** hold the top bar of the monitor for about 8 seconds until the large Wi-Fi icon appears.

**2. Find it:**

```text
python qingping_provision.py scan

Bluetooth address                         RSSI  Wi-Fi MAC (topic)  name
7C:C2:94:00:BE:F1                          -58  7CC29400BEEF       Qingping Air Monitor Lite
```

The Wi-Fi MAC used in the MQTT topics is the **Bluetooth MAC minus 2** (confirmed on the CGDN1).

**3. Provision:**

```text
python qingping_provision.py provision --address 7C:C2:94:00:BE:F1 ^
    --ssid MyIoTNetwork --mqtt-host 192.168.1.10 --mqtt-user qingping
Wi-Fi password (empty for an open network):
MQTT password:
Connecting to 7C:C2:94:00:BE:F1…
  → wifi
  → token
  → token
  → mqtt
  → topics
  → done
```

On macOS/Linux, use `\` instead of `^` to continue lines.

**4. Check:** within about a minute the monitor publishes on `qingping/<WIFI_MAC>/up`, and Home Assistant
offers it under *Discovered*.

#### Options

| Option | Default | Meaning |
|---|---|---|
| `--address` | required | from `scan`: a MAC on Windows/Linux, a UUID on macOS |
| `--wifi-mac` | Bluetooth MAC − 2 | override the topic MAC (needed on macOS, or use `--read-wifi-mac`) |
| `--read-wifi-mac` | off | ask the device for its Wi-Fi MAC over Bluetooth |
| `--ssid` | required | 2.4 GHz network |
| `--wifi-password` | prompt | or env `QINGPING_WIFI_PASSWORD` |
| `--mqtt-host` | required | broker **LAN IP** (the device can't resolve `core-mosquitto`) |
| `--mqtt-port` | `1883` | |
| `--mqtt-user` | `qingping` | a dedicated broker user, see `examples/mosquitto/` |
| `--mqtt-password` | prompt | or env `QINGPING_MQTT_PASSWORD` |
| `--prefix` | `qingping` | topic prefix; keep the default for the integration |
| `--dry-run` | off | validate and show the configuration, write nothing |

Passwords are prompted without echo, so they don't end up in your shell history, and are never printed.

## Limitations

- **No spaces** in the MQTT host, username or password, and **no `"`** in the SSID or Wi-Fi password.
  The device's setup protocol separates fields with spaces and quotes.
- The device does not confirm writes over Bluetooth. Success shows up as its first MQTT message.
- **No TLS:** the setup protocol has no TLS option; see `docs/PRIVACY.md`.
- Tested against the protocol with unit tests. Real-world reports on other firmware versions are welcome.

## Relation to `tools/qingping-ble-setup`

`tools/qingping-ble-setup` is the original reverse-engineering work by bitrate16 (AGPL-3.0, Linux and
`gatttool` only), shipped unmodified. This tool is an independent implementation of the same
documented protocol, written for cross-platform use and for the Home Assistant integration.
