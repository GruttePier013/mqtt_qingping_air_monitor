#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Derive the likely Wi-Fi MAC and MQTT arguments from a CGDN1 Bluetooth MAC.

ESP32 devices normally use base MAC (Wi-Fi station) + 2 for Bluetooth, so the
Wi-Fi MAC is the Bluetooth MAC minus 2. Always verify with the ``wifi_mac``
field of the first type-13 message on your broker.

Usage:
    python3 qingping_mac_helper.py 7C:C2:94:00:BE:F1 [--offset 2]
"""
from __future__ import annotations

import argparse
import re
import sys


def wifi_mac_from_ble(ble_mac: str, offset: int = 2) -> str:
    """Return the Wi-Fi MAC (12 upper-case hex chars) for a Bluetooth MAC."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", ble_mac)
    if len(digits) != 12:
        raise ValueError(f"not a MAC address: {ble_mac!r}")
    value = (int(digits, 16) - offset) % (1 << 48)
    return f"{value:012X}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ble_mac", help="Bluetooth MAC as shown by bluetoothctl")
    parser.add_argument("--offset", type=int, default=2,
                        help="Bluetooth = Wi-Fi + offset (default 2)")
    args = parser.parse_args()
    try:
        wifi = wifi_mac_from_ble(args.ble_mac, args.offset)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print(f"Wi-Fi MAC (topic): {wifi}  (verify with 'wifi_mac' in the first type-13 message)\n")
    print("Arguments for python3 -m qingping.bluetooth:")
    print(f"  --mac {args.ble_mac.upper()} \\")
    print(f"  --mqtt-client qingping-{wifi} \\")
    print(f"  --mqtt-read  qingping/{wifi}/down \\")
    print(f"  --mqtt-write qingping/{wifi}/up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
