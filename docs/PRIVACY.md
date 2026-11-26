# Privacy and security

This page explains which data leaves your home when you run a Qingping Air Monitor Lite (CGDN1)
with this integration, which risks remain, and how to close them. It separates three layers: the
**integration**, the **provisioning** (one-time setup) and the **device itself**.

> This is a best-effort analysis based on observed traffic, public documentation and community
> research. It is not a security audit. Firmware behaviour can change with updates.

## 1. The integration

| Topic | Behaviour |
|---|---|
| Network | Talks only to your MQTT broker through Home Assistant's MQTT integration. No cloud, no HTTP calls, no telemetry. |
| Stored data | Readings, settings, firmware version, MAC and RSSI, in the HA state machine and recorder. |
| **Discarded on arrival** | `hk_salt` (HomeKit pairing salt), SSID and BSSID from `wifi_info`. They never reach entities, attributes, the database or the in-memory diagnostics buffer. |
| Diagnostics download | Additionally redacts `hk_salt`, `wifi_info`, `ssid`, `bssid` and `password`. |
| Commands sent | Only types 11, 12, 17 (settings), 18 and 28. **Never** firmware updates (type 23). |

Why SSID and BSSID matter: a router's BSSID (its MAC address), together with the network name, can
be looked up in public Wi-Fi geolocation databases and often points to a street address.

## 2. Provisioning (one-time setup)

| Route | What Qingping learns or stores |
|---|---|
| **A. Developer portal** | Your account, the device MAC, and the Private Access config: **broker LAN address, port, MQTT username and password, topics**. The config reaches the device through Qingping's cloud, so the device needs internet during setup. |
| **C. Qingping support** | Same as A, plus the details you mailed. |
| **B. Bluetooth (HA flow or CLI)** | Nothing. Wi-Fi and MQTT settings go straight from Home Assistant or your PC to the device over Bluetooth. The HA flow keeps the passwords in memory for the flow only; they are not stored or logged. |

Recommendations for routes A and C:
- Use a **dedicated** broker user with the minimum ACL (below), so the leaked credentials are worth little.
- The broker address is a private LAN address and is not reachable from the internet, as long as
  you never port-forward MQTT.

The companion apps (Qingping+, Qingping IoT) are published by Qingping Technology (Beijing) Co., Ltd.
Their app-store privacy labels list location, contact info, identifiers and diagnostics as possibly
collected. Some users could only add devices with the app region set to China.

## 3. The device itself

### 3.1 Cloud contact while it has internet

Research on the sibling CGS2 shows these endpoints, and the CGDN1 is expected to behave similarly:

- `mqtt.bj.cleargrass.com`, `gateway.cleargrass.com`, `qing.cleargrass.com` (Qingping cloud)
- `cn.ot.io.mi.com`, `cn.ots.io.mi.com` (Xiaomi IoT)
- HTTP endpoints for firmware checks, pairing status and weather. **Weather is located from your public IP address.**

With internet blocked, the monitor keeps working with Private Access, but it may generate many DNS
queries. Answer them locally (sinkhole) instead of letting them time out.

### 3.2 MQTT without TLS

In the tested setup (port 1883) the device's MQTT connection is plain TCP: readings, settings and the
broker password travel unencrypted on your network. TLS support on the CGDN1 is undocumented: the Bluetooth setup
protocol only carries `host port username password` with no TLS flag, and the sibling CGS2 ships with
`tls=0`. Qingping's **HTTPS data push** exists, but it runs from Qingping's cloud to your server, so it
replaces local MQTT with a cloud path. The practical protection is network isolation (checklist below). Keep the monitors on a trusted or IoT network segment.

### 3.3 Type 13 broadcasts Wi-Fi identity and a HomeKit salt

About every minute the device publishes SSID, RSSI and BSSID (`wifi_info`) plus `hk_salt`.
**Every client that can subscribe to `qingping/#` on your broker sees this.** The integration drops
it, but other subscribers (MQTT Explorer, Node-RED, a bridge to another broker) may not. Limit read
access to `qingping/#` as well.

### 3.4 Unsigned firmware updates over MQTT ⚠️

The stock firmware accepts a **type 23** message on its down topic, downloads the given URL and
flashes it, checking only a CRC-32 trailer: **no signature check and no rollback**. Anyone who can
publish to `qingping/<MAC>/down` can install arbitrary firmware. That firmware would then run on
your network with your Wi-Fi password in flash.

**Mitigation:** only Home Assistant may write to `qingping/+/down`. See the ACL below.

### 3.5 Bluetooth

- **Provisioning interface:** only active in pairing mode (hold the top bar about 8 s), so physical
  access is needed. In pairing mode, anyone in BLE range can write Wi-Fi and MQTT settings. Don't
  leave a unit in pairing mode unattended.
- **Advertisements with readings** (Qingping format, service UUID `FDCD`): the stock firmware's BLE
  is meant for pairing (HomeKit/MiIO), and users report that measurement broadcasts stop about an
  hour after a network reset or only appear during setup, unless "BLE gateway" is enabled in Mi Home.
  If they are broadcast, anyone nearby can read them, and CO₂ per room reveals occupancy.
  **Check your own units:** Home Assistant → Settings → Bluetooth → *Advertisement monitor*, and look for
  service data `0000fdcd-…` from the monitor. There is **no MQTT setting to disable Bluetooth**.
  The only way to control it fully is alternative firmware, which carries a risk of bricking the device.

## 4. Hardening checklist

- [ ] Monitors on an **IoT VLAN or guest network**; only TCP 1883 to the broker allowed.
- [ ] **Internet blocked** for the monitors after setup; DNS for `*.cleargrass.com`, `*.qingping.co`
      and `*.mi.com` answered locally (e.g. `0.0.0.0`).
- [ ] **Dedicated broker user** for the monitors.
- [ ] **ACL**: monitors write `qingping/+/up` and read `qingping/+/down`; only HA writes `qingping/+/down`;
      read access to `qingping/#` only for HA and trusted tools.
- [ ] Broker **not reachable from the internet** (no port-forward, no public bridge).
- [ ] Prefer **Bluetooth provisioning** (route B) so your credentials never reach Qingping.
- [ ] Firmware updates: open internet temporarily, update in the app, block again.
- [ ] Check the **Bluetooth advertisement monitor** for `FDCD` broadcasts from your units.
- [ ] Share **diagnostics** files, not raw MQTT dumps; raw type-13 messages contain your SSID and BSSID.

### Example Mosquitto ACL

```
# Home Assistant
user homeassistant
topic readwrite #

# Qingping monitors
user qingping
topic write qingping/+/up
topic read  qingping/+/down
```

See [`examples/mosquitto/`](../examples/mosquitto/) for the add-on configuration.

## Sources

- [ea/cgs2_decloud](https://github.com/ea/cgs2_decloud): CGS2 cloud endpoints, weather by public IP, TLS disabled, default credentials.
- [nemethhh/esphome-qingping-cgdn1](https://github.com/nemethhh/esphome-qingping-cgdn1): stock CGDN1 firmware analysis, unsigned type-23 OTA, stock BLE purpose.
- [bitrate16/qingping](https://github.com/bitrate16/qingping): BLE provisioning protocol.
- [GreyEarl/qingping-air-monitor-mqtt](https://github.com/GreyEarl/qingping-air-monitor-mqtt): internet only needed for setup; DNS behaviour when blocked.
- [ble_monitor issue #707](https://github.com/custom-components/ble_monitor/issues/707) and [a81x/qingping-air](https://github.com/a81x/qingping-air): BLE broadcast behaviour.
- Apple App Store privacy labels for Qingping+ and Qingping IoT.
