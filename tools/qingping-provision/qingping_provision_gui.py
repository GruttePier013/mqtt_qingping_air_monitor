#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Windows 11 GUI for provisioning a Qingping Air Monitor Lite (CGDN1) over Bluetooth.

Double-click ``start_gui.bat`` (first run installs ``bleak`` in a local venv), or run
``QingpingProvision.exe`` from the GitHub release, or ``pythonw qingping_provision_gui.py``.

The window walks through three steps: find the monitor (in pairing mode), enter
the Wi-Fi network and the MQTT broker, write. Passwords are never saved; the
other fields are remembered in %APPDATA%\\QingpingProvision\\settings.json.

Bluetooth runs on its own asyncio loop in a worker thread (MTA on Windows), so
the Tk main loop never blocks and WinRT does not collide with Tk's thread.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import locale
import os
import queue
import sys
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))))
import qingping_provision as cli  # noqa: E402  (shares the protocol loader)

bp = cli.bp
APP_NAME = "QingpingProvision"
VERSION = "2.3.0"

# ------------------------------------------------------------------ texts
TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Qingping Air Monitor Lite: Bluetooth setup",
        "step1": "1  Monitor",
        "step1_help": "Hold the top bar of the monitor for about 8 seconds until the large Wi-Fi icon appears, then click Scan.",
        "scan": "Scan",
        "scanning": "Scanning…",
        "col_name": "Name", "col_address": "Bluetooth address", "col_rssi": "Signal", "col_wifi": "Wi-Fi MAC (topic)",
        "wifi_mac": "Wi-Fi MAC", "read_mac": "Read from device",
        "step2": "2  Wi-Fi network (2.4 GHz)",
        "ssid": "Network name (SSID)", "wifi_password": "Password", "show": "Show",
        "step3": "3  MQTT broker",
        "host": "Broker LAN IP", "port": "Port", "user": "User for the monitor", "mqtt_password": "Password",
        "prefix": "Topic prefix",
        "check": "Check", "provision": "Write to monitor",
        "log": "Log",
        "no_device": "Select a monitor in the list (Scan first).",
        "found": "Found {n} monitor(s).",
        "none_found": "No monitor found. Is the large Wi-Fi icon showing and Bluetooth turned on?",
        "connecting": "Connecting to {address}…",
        "step": "  → {step}",
        "done": "Done. The monitor now joins \"{ssid}\" and should publish on {topic} within about a minute. "
                "In Home Assistant it appears under Settings → Devices & services → Discovered.",
        "done_title": "Monitor configured",
        "error_title": "Error",
        "config": "Configuration (passwords hidden):",
        "mac_read": "Device reports Wi-Fi MAC: {mac}",
        "mac_none": "The device did not answer. Enter the Wi-Fi MAC (Bluetooth MAC minus 2).",
        "bt_error": "Bluetooth error: {error}",
        "busy": "Busy…",
        "ready": "Ready",
    },
    "nl": {
        "title": "Qingping Air Monitor Lite: instellen via Bluetooth",
        "step1": "1  Monitor",
        "step1_help": "Houd de balk bovenop de monitor ongeveer 8 seconden ingedrukt tot het grote wifi-icoon verschijnt en klik dan op Zoeken.",
        "scan": "Zoeken",
        "scanning": "Zoeken…",
        "col_name": "Naam", "col_address": "Bluetooth-adres", "col_rssi": "Signaal", "col_wifi": "Wifi-MAC (topic)",
        "wifi_mac": "Wifi-MAC", "read_mac": "Uitlezen",
        "step2": "2  Wifi-netwerk (2,4 GHz)",
        "ssid": "Netwerknaam (SSID)", "wifi_password": "Wachtwoord", "show": "Tonen",
        "step3": "3  MQTT-broker",
        "host": "Broker LAN-IP", "port": "Poort", "user": "Gebruiker voor de monitor", "mqtt_password": "Wachtwoord",
        "prefix": "Topic-prefix",
        "check": "Controleren", "provision": "Naar monitor schrijven",
        "log": "Logboek",
        "no_device": "Kies een monitor in de lijst (eerst Zoeken).",
        "found": "{n} monitor(s) gevonden.",
        "none_found": "Geen monitor gevonden. Staat het grote wifi-icoon in beeld en is Bluetooth aan?",
        "connecting": "Verbinden met {address}…",
        "step": "  → {step}",
        "done": "Klaar. De monitor verbindt nu met \"{ssid}\" en publiceert binnen ongeveer een minuut op {topic}. "
                "In Home Assistant verschijnt hij onder Instellingen → Apparaten & diensten → Ontdekt.",
        "done_title": "Monitor ingesteld",
        "error_title": "Fout",
        "config": "Configuratie (wachtwoorden verborgen):",
        "mac_read": "Apparaat meldt wifi-MAC: {mac}",
        "mac_none": "Het apparaat antwoordde niet. Vul het wifi-MAC in (Bluetooth-MAC min 2).",
        "bt_error": "Bluetooth-fout: {error}",
        "busy": "Bezig…",
        "ready": "Gereed",
    },
}


def detect_language(override: str | None = None) -> str:
    if override in TEXTS:
        return override  # type: ignore[return-value]
    candidates = [os.environ.get("LANG", "")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            candidates.append(locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), ""))
        except Exception:  # noqa: BLE001
            pass
    return "nl" if any(c.lower().startswith(("nl", "dutch")) for c in candidates) else "en"


# --------------------------------------------------------------- settings
SETTING_KEYS = ("ssid", "host", "port", "user", "prefix")  # never passwords


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / APP_NAME / "settings.json"


def load_settings(path: Path | None = None) -> dict[str, str]:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items() if k in SETTING_KEYS}


def save_settings(values: dict[str, Any], path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: str(values[k]) for k in SETTING_KEYS if k in values}
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")


# ------------------------------------------------------------ pure logic
def build_config(values: dict[str, str]) -> Any:
    """ProvisionConfig from form values (raises bp.ProvisioningError / ValueError)."""
    wifi_mac = (values.get("wifi_mac") or "").strip()
    if not wifi_mac:
        address = (values.get("address") or "").strip()
        if not cli._is_mac(address):
            raise bp.ProvisioningError("Wi-Fi MAC unknown")
        wifi_mac = bp.wifi_mac_from_ble(address)
    try:
        port = int(str(values.get("port", "1883")).strip())
    except ValueError as err:
        raise bp.ProvisioningError("MQTT port must be a number") from err
    config = bp.ProvisionConfig.for_wifi_mac(
        wifi_mac,
        wifi_ssid=values.get("ssid", ""),
        wifi_password=values.get("wifi_password", ""),
        mqtt_host=(values.get("host") or "").strip(),
        mqtt_port=port,
        mqtt_username=(values.get("user") or "").strip(),
        mqtt_password=values.get("mqtt_password", ""),
        prefix=(values.get("prefix") or bp.DEFAULT_PREFIX).strip(),
    )
    config.validate()
    return config


def scan_rows(found: dict[str, tuple[Any, Any]]) -> list[tuple[str, str, int, str]]:
    """(name, address, rssi, wifi_mac) for Qingping devices, strongest first."""
    rows = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        if name.startswith("Qingping"):
            wifi = bp.wifi_mac_from_ble(device.address) if cli._is_mac(device.address) else ""
            rows.append((name, device.address, int(adv.rssi), wifi))
    return sorted(rows, key=lambda r: -r[2])


# ------------------------------------------------------------- BLE worker
class BleWorker:
    """Runs coroutines on a private asyncio loop in a daemon thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


async def ble_scan(timeout: float = 8.0) -> list[tuple[str, str, int, str]]:
    from bleak import BleakScanner

    return scan_rows(await BleakScanner.discover(timeout=timeout, return_adv=True))


async def ble_read_wifi_mac(address: str) -> str | None:
    client = await cli._connect(address, 20.0)
    try:
        return await bp.read_wifi_mac(client)
    finally:
        await client.disconnect()


async def ble_provision(address: str, config: Any, progress: Callable[[str], None]) -> None:
    client = await cli._connect(address, 20.0)
    try:
        await bp.provision(client, config, progress=progress)
    finally:
        await client.disconnect()


# -------------------------------------------------------------------- GUI
def _enable_dpi_awareness() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor, sharp on Windows 11
        except Exception:  # noqa: BLE001
            pass


class App:
    def __init__(self, lang: str) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk, self.ttk, self.messagebox = tk, ttk, messagebox
        self.t = TEXTS[lang]
        self.worker = BleWorker()
        self.events: queue.Queue[tuple[Callable[..., None], tuple]] = queue.Queue()

        self.root = tk.Tk()
        self.root.title(self.t["title"])
        self.root.minsize(760, 640)
        self._set_icon()
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Step.TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        saved = load_settings()
        self.vars = {
            "wifi_mac": tk.StringVar(), "ssid": tk.StringVar(value=saved.get("ssid", "")),
            "wifi_password": tk.StringVar(), "host": tk.StringVar(value=saved.get("host", "")),
            "port": tk.StringVar(value=saved.get("port", "1883")),
            "user": tk.StringVar(value=saved.get("user", "qingping")),
            "mqtt_password": tk.StringVar(), "prefix": tk.StringVar(value=saved.get("prefix", bp.DEFAULT_PREFIX)),
        }
        self.status = tk.StringVar(value=self.t["ready"])
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._pump)

    # -- layout --------------------------------------------------------
    def _build(self) -> None:
        tk, ttk, t = self.tk, self.ttk, self.t
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        # step 1
        s1 = ttk.LabelFrame(outer, text=t["step1"], padding=10, style="Step.TLabelframe")
        s1.grid(row=0, column=0, sticky="nsew")
        s1.columnconfigure(0, weight=1)
        ttk.Label(s1, text=t["step1_help"], wraplength=700, justify="left").grid(row=0, column=0, columnspan=4, sticky="w")
        cols = ("name", "address", "rssi", "wifi")
        self.tree = ttk.Treeview(s1, columns=cols, show="headings", height=4, selectmode="browse")
        for col, key, width in zip(cols, ("col_name", "col_address", "col_rssi", "col_wifi"), (220, 260, 70, 150)):
            self.tree.heading(col, text=t[key])
            self.tree.column(col, width=width, stretch=col in ("name", "address"))
        self.tree.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=(8, 6))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.scan_btn = ttk.Button(s1, text=t["scan"], command=self.scan)
        self.scan_btn.grid(row=2, column=0, sticky="w")
        ttk.Label(s1, text=t["wifi_mac"]).grid(row=2, column=1, sticky="e", padx=(12, 4))
        ttk.Entry(s1, textvariable=self.vars["wifi_mac"], width=16).grid(row=2, column=2, sticky="w")
        self.read_btn = ttk.Button(s1, text=t["read_mac"], command=self.read_mac)
        self.read_btn.grid(row=2, column=3, sticky="w", padx=(6, 0))

        # step 2
        s2 = ttk.LabelFrame(outer, text=t["step2"], padding=10, style="Step.TLabelframe")
        s2.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        s2.columnconfigure(1, weight=1)
        self._row(s2, 0, t["ssid"], self.vars["ssid"])
        self.wifi_entry = self._row(s2, 1, t["wifi_password"], self.vars["wifi_password"], secret=True)

        # step 3
        s3 = ttk.LabelFrame(outer, text=t["step3"], padding=10, style="Step.TLabelframe")
        s3.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        s3.columnconfigure(1, weight=1)
        self._row(s3, 0, t["host"], self.vars["host"])
        self._row(s3, 1, t["port"], self.vars["port"], width=8)
        self._row(s3, 2, t["user"], self.vars["user"])
        self.mqtt_entry = self._row(s3, 3, t["mqtt_password"], self.vars["mqtt_password"], secret=True)
        self._row(s3, 4, t["prefix"], self.vars["prefix"], width=16)

        # actions
        bar = ttk.Frame(outer)
        bar.grid(row=3, column=0, sticky="ew", pady=(12, 6))
        bar.columnconfigure(1, weight=1)
        self.check_btn = ttk.Button(bar, text=t["check"], command=self.check)
        self.check_btn.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=6)
        self.progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.go_btn = ttk.Button(bar, text=t["provision"], command=self.provision, style="Accent.TButton")
        self.go_btn.grid(row=0, column=2, sticky="e")

        # log
        logf = ttk.LabelFrame(outer, text=t["log"], padding=6)
        logf.grid(row=4, column=0, sticky="nsew")
        outer.rowconfigure(4, weight=1)
        self.log_text = tk.Text(logf, height=8, wrap="word", state="disabled", font=("Consolas", 9), relief="flat")
        self.log_text.pack(fill="both", expand=True)
        ttk.Label(outer, textvariable=self.status, anchor="w").grid(row=5, column=0, sticky="ew", pady=(4, 0))

    def _row(self, parent, row: int, label: str, var, secret: bool = False, width: int = 40):
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var, width=width, show="•" if secret else "")
        entry.grid(row=row, column=1, sticky="w", pady=3)
        if secret:
            shown = self.tk.BooleanVar(value=False)
            ttk.Checkbutton(parent, text=self.t["show"], variable=shown,
                            command=lambda: entry.configure(show="" if shown.get() else "•")
                            ).grid(row=row, column=2, sticky="w", padx=8)
        return entry

    def _set_icon(self) -> None:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        ico = base / "app.ico"
        if sys.platform == "win32" and ico.is_file():
            try:
                self.root.iconbitmap(default=str(ico))
            except Exception:  # noqa: BLE001
                pass

    # -- helpers -------------------------------------------------------
    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _post(self, fn: Callable[..., None], *args: Any) -> None:
        """Thread-safe: run fn(*args) on the Tk thread."""
        self.events.put((fn, args))

    def _pump(self) -> None:
        try:
            while True:
                fn, args = self.events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for btn in (self.scan_btn, self.read_btn, self.check_btn, self.go_btn):
            btn.configure(state=state)
        self.status.set(self.t["busy"] if busy else self.t["ready"])
        self.root.configure(cursor="watch" if busy else "")

    def _run(self, coro, on_ok: Callable[[Any], None]) -> None:
        self._busy(True)

        def _done(fut: Future) -> None:
            try:
                result = fut.result()
            except Exception as err:  # noqa: BLE001
                self._post(self._fail, err)
            else:
                self._post(on_ok, result)
            self._post(self._busy, False)

        self.worker.submit(coro).add_done_callback(_done)

    def _fail(self, err: Exception) -> None:
        text = str(err) if isinstance(err, bp.ProvisioningError) else self.t["bt_error"].format(
            error=f"{type(err).__name__}: {err}")
        self.log(text)
        self.messagebox.showerror(self.t["error_title"], text, parent=self.root)

    def _values(self) -> dict[str, str]:
        values = {k: v.get() for k, v in self.vars.items()}
        values["address"] = self._selected_address() or ""
        return values

    def _selected_address(self) -> str | None:
        sel = self.tree.selection()
        return self.tree.set(sel[0], "address") if sel else None

    # -- actions -------------------------------------------------------
    def _on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel:
            wifi = self.tree.set(sel[0], "wifi")
            if wifi:
                self.vars["wifi_mac"].set(wifi)

    def scan(self) -> None:
        self.log(self.t["scanning"])
        self.tree.delete(*self.tree.get_children())
        self._run(ble_scan(), self._scanned)

    def _scanned(self, rows) -> None:
        for name, address, rssi, wifi in rows:
            self.tree.insert("", "end", values=(name, address, f"{rssi} dBm", wifi))
        self.log(self.t["found"].format(n=len(rows)) if rows else self.t["none_found"])
        if rows:
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self._on_select()

    def read_mac(self) -> None:
        address = self._selected_address()
        if not address:
            self.messagebox.showinfo(self.t["title"], self.t["no_device"], parent=self.root)
            return
        self.log(self.t["connecting"].format(address=address))
        self._run(ble_read_wifi_mac(address), self._mac_read)

    def _mac_read(self, mac: str | None) -> None:
        if mac:
            self.vars["wifi_mac"].set(mac)
            self.log(self.t["mac_read"].format(mac=mac))
        else:
            self.log(self.t["mac_none"])

    def check(self) -> Any:
        try:
            config = build_config(self._values())
        except (bp.ProvisioningError, ValueError) as err:
            self._fail(err)
            return None
        self.log(self.t["config"])
        for key, value in config.redacted().items():
            self.log(f"  {key:<14} {value}")
        return config

    def provision(self) -> None:
        address = self._selected_address()
        if not address:
            self.messagebox.showinfo(self.t["title"], self.t["no_device"], parent=self.root)
            return
        config = self.check()
        if config is None:
            return
        save_settings({k: self.vars[k].get() for k in SETTING_KEYS})
        self.progress.configure(value=0)
        self.log(self.t["connecting"].format(address=address))

        def progress(step: str) -> None:
            self._post(self.log, self.t["step"].format(step=step))
            self._post(self.progress.step, 1)

        def ok(_result) -> None:
            self.progress.configure(value=6)
            msg = self.t["done"].format(ssid=config.wifi_ssid, topic=config.topic_write)
            self.log(msg)
            self.vars["wifi_password"].set("")
            self.vars["mqtt_password"].set("")
            self.messagebox.showinfo(self.t["done_title"], msg, parent=self.root)

        self._run(ble_provision(address, config, progress), ok)

    def close(self) -> None:
        self.worker.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qingping CGDN1 Bluetooth setup (GUI)")
    parser.add_argument("--lang", choices=sorted(TEXTS), help="force language")
    parser.add_argument("--selftest", action="store_true",
                        help="build the window, validate a sample config, close (CI smoke test)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    _enable_dpi_awareness()
    app = App(detect_language(args.lang))
    if args.selftest:
        import bleak  # noqa: F401  - fails the test if bleak is not bundled

        sample = {"address": "7C:C2:94:00:BE:F1", "ssid": "Example", "wifi_password": "w",
                  "host": "192.0.2.10", "port": "1883", "user": "qingping", "mqtt_password": "m"}
        assert build_config(sample).topic_write == "qingping/7CC29400BEEF/up"
        app.root.after(800, app.close)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
