"""Remembered answers (name, handle, plans, visibility, theme) so repeat runs ask nothing but the window."""

import json

from paths import ensure_parent, private_dir


def path():
    return private_dir() / "prefs.json"


def load():
    try:
        value = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save(**changes):
    prefs = {**load(), **{key: value for key, value in changes.items() if value is not None}}
    ensure_parent(path())
    path().write_text(json.dumps(prefs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path().chmod(0o600)
    return prefs


def parse_plan(value):
    """`Claude Max=200` -> {"name": "Claude Max", "usd_per_month": 200.0}."""
    name, _, amount = value.rpartition("=")
    try:
        usd = float(amount.strip().lstrip("$"))
    except ValueError:
        raise ValueError(f"Plan must look like 'Name=USD per month', got {value!r}") from None
    if not name.strip() or usd <= 0:
        raise ValueError(f"Plan must look like 'Name=USD per month', got {value!r}")
    return {"name": name.strip(), "usd_per_month": usd}
