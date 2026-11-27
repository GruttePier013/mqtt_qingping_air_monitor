#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Provision a Qingping Air Monitor Lite (CGDN1) to your own MQTT broker over Bluetooth.

Cross-platform (Windows 10+, macOS, Linux) using ``bleak``. It uses the same
protocol module as the Home Assistant integration
(``custom_components/qingping_cgdn1/ble_provision.py``).

Put the monitor in pairing mode first: hold the top bar ~8 s until the large
Wi-Fi icon appears.

Examples:
    python qingping_provision.py scan
    python qingping_provision.py provision --address 7C:C2:94:00:BE:F1 \\
        --ssid MyIoT --mqtt-host 192.168.1.10 --mqtt-user qingping
    python qingping_provision.py provision ... --dry-run

Passwords are asked interactively (not echoed, not in your shell history)
unless passed with --wifi-password / --mqtt-password or the environment
variables QINGPING_WIFI_PASSWORD / QINGPING_MQTT_PASSWORD.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

_HERE = Path(__file__).resolve().parent
_CANDIDATES = (
    _HERE / "ble_provision.py",  # copied next to this script
    _HERE.parents[1] / "custom_components" / "qingping_cgdn1" / "ble_provision.py",  # in the repo
)


def _load_protocol() -> ModuleType:
    for path in _CANDIDATES:
        if path.is_file():
            spec = importlib.util.spec_from_file_location("qingping_ble_provision", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module  # dataclasses need the module registered
            spec.loader.exec_module(module)
            return module
    raise SystemExit("ble_provision.py not found: run from the repository or copy it next to this script")


bp = _load_protocol()


def _password(value: str | None, env: str, prompt: str, allow_empty: bool = False) -> str:
    if value is not None:
        return value
    if env in os.environ:
        return os.environ[env]
    while True:
        entered = getpass.getpass(prompt)
        if entered or allow_empty:
            return entered
        print("  (cannot be empty)")


def _is_mac(address: str) -> bool:
    try:
        bp.normalize_mac(address)
    except bp.ProvisioningError:
        return False
    return True


# ------------------------------------------------------------------ scan
async def cmd_scan(args: argparse.Namespace) -> int:
    from bleak import BleakScanner

    print(f"Scanning {args.timeout:.0f} s for monitors in pairing mode…")
    found = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    rows = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        if name.startswith("Qingping"):
            wifi = bp.wifi_mac_from_ble(device.address) if _is_mac(device.address) else "(read it: --read-wifi-mac)"
            rows.append((device.address, adv.rssi, name, wifi))
    if not rows:
        print("No Qingping found. Is the monitor showing the large Wi-Fi icon? Is Bluetooth on?")
        return 1
    print(f"{'Bluetooth address':<40} {'RSSI':>5}  {'Wi-Fi MAC (topic)':<18} name")
    for address, rssi, name, wifi in sorted(rows, key=lambda r: -r[1]):
        print(f"{address:<40} {rssi:>5}  {wifi:<18} {name}")
    return 0


# ------------------------------------------------------------- provision
async def _connect(address: str, timeout: float):
    from bleak import BleakClient, BleakScanner

    device = await BleakScanner.find_device_by_address(address, timeout=timeout)
    if device is None:
        raise bp.ProvisioningError(f"{address} not found: in pairing mode and within range?")
    client = BleakClient(device, timeout=timeout)
    await client.connect()
    return client


async def cmd_provision(args: argparse.Namespace) -> int:
    wifi_mac = args.wifi_mac
    if not wifi_mac and _is_mac(args.address):
        wifi_mac = bp.wifi_mac_from_ble(args.address)

    client = None
    try:
        if args.dry_run and not wifi_mac:
            raise bp.ProvisioningError("--dry-run needs --wifi-mac when the address is not a MAC (macOS)")
        if not args.dry_run:
            print(f"Connecting to {args.address}…")
            client = await _connect(args.address, args.timeout)
            if not wifi_mac or args.read_wifi_mac:
                read = await bp.read_wifi_mac(client)
                print(f"Device reports Wi-Fi MAC: {read or 'no answer'}")
                wifi_mac = wifi_mac or read
            if not wifi_mac:
                raise bp.ProvisioningError("Wi-Fi MAC unknown: pass --wifi-mac (Bluetooth MAC minus 2)")

        config = bp.ProvisionConfig.for_wifi_mac(
            wifi_mac,
            wifi_ssid=args.ssid,
            wifi_password=_password(args.wifi_password, "QINGPING_WIFI_PASSWORD",
                                    "Wi-Fi password (empty for an open network): ", allow_empty=True),
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            mqtt_username=args.mqtt_user,
            mqtt_password=_password(args.mqtt_password, "QINGPING_MQTT_PASSWORD", "MQTT password: "),
            prefix=args.prefix,
        )
        config.validate()
        print("Configuration (passwords hidden):")
        for key, value in config.redacted().items():
            print(f"  {key:<14} {value}")
        if args.dry_run:
            print("Dry run: nothing written.")
            return 0

        await bp.provision(client, config, progress=lambda step: print("  → all packets sent" if step == "done" else f"  → sending: {step}"))
    except bp.ProvisioningError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    except Exception as err:  # noqa: BLE001 - bleak/OS errors, shown plainly
        print(f"Bluetooth error: {type(err).__name__}: {err}", file=sys.stderr)
        return 3
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    print("\nTransfer complete: all settings were sent over Bluetooth. The monitor confirms nothing, so check:\n"
          f"  1. The large Wi-Fi icon disappears; the monitor joins '{args.ssid}'.\n"
          f"  2. Mosquitto log: 'New client connected ... as {config.client_id} ... u'{config.mqtt_username}''.\n"
          "     'not authorised' means a wrong user or password: pairing mode on and write again.\n"
          f"  3. Messages arrive on {config.topic_write} within about a minute.\n"
          "  4. Home Assistant: Settings → Devices & services → Discovered (new monitor), or values again (existing).")
    return 0


# ------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Point a Qingping Air Monitor Lite (CGDN1) at your own MQTT broker over Bluetooth.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="list monitors in pairing mode")
    scan.add_argument("--timeout", type=float, default=10.0)

    prov = sub.add_parser("provision", help="write Wi-Fi and MQTT settings")
    prov.add_argument("--address", required=True,
                      help="Bluetooth address from 'scan' (a MAC on Windows/Linux, a UUID on macOS)")
    prov.add_argument("--wifi-mac", help="Wi-Fi MAC for the topics (default: Bluetooth MAC minus 2)")
    prov.add_argument("--read-wifi-mac", action="store_true", help="also ask the device for its Wi-Fi MAC")
    prov.add_argument("--ssid", required=True, help="2.4 GHz Wi-Fi network name")
    prov.add_argument("--wifi-password", help="Wi-Fi password (prompted if omitted)")
    prov.add_argument("--mqtt-host", required=True, help="broker LAN IP address")
    prov.add_argument("--mqtt-port", type=int, default=1883)
    prov.add_argument("--mqtt-user", default="qingping")
    prov.add_argument("--mqtt-password", help="MQTT password (prompted if omitted)")
    prov.add_argument("--prefix", default=bp.DEFAULT_PREFIX, help="topic prefix (default: qingping)")
    prov.add_argument("--timeout", type=float, default=20.0)
    prov.add_argument("--dry-run", action="store_true", help="validate and show, write nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = cmd_scan if args.command == "scan" else cmd_provision
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
