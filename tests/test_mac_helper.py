"""Tests for tools/qingping-ble-setup/qingping_mac_helper.py (pure function, no HA)."""
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "tools" / "qingping-ble-setup" / "qingping_mac_helper.py"
_spec = importlib.util.spec_from_file_location("qingping_mac_helper", _PATH)
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)


@pytest.mark.parametrize(
    ("ble", "wifi"),
    [
        ("7C:C2:94:00:BE:F1", "7CC29400BEEF"),
        ("7c-c2-94-00-be-f1", "7CC29400BEEF"),
        ("7CC294000101", "7CC2940000FF"),   # borrow across bytes
        ("000000000001", "FFFFFFFFFFFF"),   # wrap-around
    ],
)
def test_wifi_mac_from_ble(ble, wifi):
    assert helper.wifi_mac_from_ble(ble) == wifi


def test_invalid_mac():
    with pytest.raises(ValueError):
        helper.wifi_mac_from_ble("not-a-mac")
