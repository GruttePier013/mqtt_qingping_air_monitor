"""Tests for tools/qingping-provision/qingping_provision.py (dry run, no Bluetooth)."""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[1] / "tools" / "qingping-provision" / "qingping_provision.py"
_spec = importlib.util.spec_from_file_location("qingping_provision_cli", _PATH)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

BASE = ["provision", "--address", "7C:C2:94:00:BE:F1", "--ssid", "Example",
        "--mqtt-host", "192.0.2.10", "--wifi-password", "w", "--mqtt-password", "m", "--dry-run"]


def test_dry_run_derives_topics(capsys):
    assert cli.main(BASE) == 0
    out = capsys.readouterr().out
    assert "qingping/7CC29400BEEF/up" in out and "qingping/7CC29400BEEF/down" in out
    assert " w\n" not in out and " m\n" not in out   # passwords never printed


def test_dry_run_rejects_bad_input(capsys):
    assert cli.main([*BASE[:-1], "--mqtt-user", "has space", "--dry-run"]) == 2


def test_macos_uuid_needs_wifi_mac(capsys):
    args = ["provision", "--address", "1F2E3D4C-0000-1111-2222-333344445555", "--ssid", "x",
            "--mqtt-host", "192.0.2.10", "--wifi-password", "w", "--mqtt-password", "m", "--dry-run"]
    assert cli.main(args) == 2
    assert cli.main([*args, "--wifi-mac", "7CC29400BEEF"]) == 0
