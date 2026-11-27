"""Translation files: valid for the HA frontend (ICU message format) and consistent."""
import json
import re
from pathlib import Path

import pytest

_DIR = Path(__file__).parents[1] / "custom_components" / "qingping_cgdn1"
FILES = [_DIR / "strings.json", *sorted((_DIR / "translations").glob("*.json"))]


def _strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


def _placeholders(text):
    return set(re.findall(r"{(\w+)}", text))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_icu_safe(path):
    """No '<'/'>' (UNCLOSED_TAG in the frontend), balanced braces, no apostrophe next to a brace."""
    for key, text in _strings(json.loads(path.read_text(encoding="utf-8"))):
        assert "<" not in text and ">" not in text, f"{path.name}:{key}: angle bracket"
        assert text.count("{") == text.count("}"), f"{path.name}:{key}: unbalanced braces"
        assert "'{" not in text and "}'" not in text, f"{path.name}:{key}: apostrophe escapes a placeholder"


def test_same_keys_and_placeholders():
    base = dict(_strings(json.loads((_DIR / "strings.json").read_text(encoding="utf-8"))))
    for path in FILES[1:]:
        other = dict(_strings(json.loads(path.read_text(encoding="utf-8"))))
        assert set(other) == set(base), f"{path.name}: keys differ: {set(other) ^ set(base)}"
        for key, text in base.items():
            assert _placeholders(other[key]) == _placeholders(text), f"{path.name}:{key}: placeholders differ"
