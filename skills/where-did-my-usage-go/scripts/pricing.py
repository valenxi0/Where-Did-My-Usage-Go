"""Calculate a conservative API equivalent from verified per-model rates."""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

BUNDLED = Path(__file__).resolve().parent.parent / "references/pricing.json"
STALE_AFTER_DAYS = 45
RATE_KEYS = ("input_per_million", "cached_input_per_million", "output_per_million")
WRITE_KEYS = ("cache_write_per_million", "cache_write_1h_per_million")
COUNT_KEYS = ("noncached_input_tokens", "cached_input_tokens", "cache_write_tokens", "cache_write_1h_tokens", "output_tokens")
_DATE_SUFFIX = re.compile(r"-\d{8}$")
_EFFORT_SUFFIX = re.compile(r"-(minimal|low|medium|high|xhigh|max|thinking)$")


def model_key(name):
    """Map a logged model ID to its price-table ID.

    Drops a provider prefix (`anthropic/…`), a context tag (`[1m]`), a dated
    snapshot suffix, and a reasoning-effort suffix, and treats dots as dashes
    (`glm-5.3` = `glm-5-3`). None of these change the per-token rate.
    """
    if not isinstance(name, str):
        return None
    name = re.sub(r"\[.*?\]$", "", name.strip().lower()).rsplit("/", 1)[-1].replace(".", "-")
    return _EFFORT_SUFFIX.sub("", _DATE_SUFFIX.sub("", name)) or None


def _rate(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _rates(entry):
    values = {key: _rate(entry.get(key)) for key in RATE_KEYS}
    if any(value is None for value in values.values()):
        return None
    values.update({key: _rate(entry[key]) for key in WRITE_KEYS if entry.get(key) is not None})
    return values


def _index(entries, into=None):
    into = {} if into is None else into
    for entry in entries or []:
        key = model_key(entry.get("model")) if isinstance(entry, dict) else None
        if key and entry.get("source_url") and _rates(entry):
            into[key] = entry
    return into


def load(*paths):
    """Merge price tables; later files override earlier ones model by model."""
    merged = {"as_of": None, "models": {}}
    for path in paths:
        table = json.loads(Path(path).read_text(encoding="utf-8"))
        dates = [value for value in (merged["as_of"], table.get("as_of")) if value]
        merged["as_of"] = min(dates) if dates else None  # the oldest check date governs staleness
        _index(table.get("models"), merged["models"])
    return merged


def stale(pricing, today=None):
    try:
        checked = date.fromisoformat(pricing["as_of"])
    except (KeyError, TypeError, ValueError):
        return True
    return ((today or date.today()) - checked).days > STALE_AFTER_DAYS


def estimate(sessions, pricing):
    """Return USD for matched token records and their coverage, or no estimate."""
    if not isinstance(pricing, dict) or not pricing.get("as_of") or not pricing.get("models"):
        return None
    models = pricing["models"] if isinstance(pricing["models"], dict) else _index(pricing["models"])
    total = Decimal(0)
    covered = recorded = 0
    components, unpriced = {}, {}
    for session in sessions:
        tokens = session.get("tokens") if isinstance(session, dict) else None
        if not isinstance(tokens, dict):
            continue
        recorded += max(0, int(tokens.get("input_tokens") or 0)) + max(0, int(tokens.get("output_tokens") or 0))
        for usage in session.get("model_usage") or []:
            counts = usage.get("tokens") if isinstance(usage, dict) else None
            if not isinstance(counts, dict):
                continue
            input_count = max(0, int(counts.get("input_tokens") or 0))
            output = max(0, int(counts.get("output_tokens") or 0))
            entry = models.get(model_key(usage.get("model")))
            long_context = usage.get("context") == "long" and isinstance(entry, dict) and isinstance(entry.get("long_context"), dict)
            rate = _rates(entry["long_context"] if long_context else entry) if entry else None
            cached = max(0, int(counts.get("cached_input_tokens") or 0))
            writes = max(0, int(counts.get("cache_write_tokens") or 0))
            writes_1h = max(0, int(counts.get("cache_write_1h_tokens") or 0))
            if (rate is None or cached + writes + writes_1h > input_count
                    or (writes and "cache_write_per_million" not in rate)
                    or (writes_1h and "cache_write_1h_per_million" not in rate)):
                key = (session.get("agent"), usage.get("model"))
                unpriced[key] = unpriced.get(key, 0) + input_count + output
                continue
            # A write rate with no recorded write count means writes were billed but not logged.
            # Pricing those tokens as plain input understates the total, so the result is a floor.
            writes_unrecorded = any(key in rate and field not in counts for key, field in
                                    (("cache_write_per_million", "cache_write_tokens"),
                                     ("cache_write_1h_per_million", "cache_write_1h_tokens")))
            uncached = input_count - cached - writes - writes_1h
            amount = (uncached * rate["input_per_million"] + cached * rate["cached_input_per_million"]
                      + writes * rate.get("cache_write_per_million", 0)
                      + writes_1h * rate.get("cache_write_1h_per_million", 0)
                      + output * rate["output_per_million"]) / 1_000_000
            total += amount
            covered += input_count + output
            key = (session.get("agent"), usage["model"], "long" if long_context else "standard")
            component = components.setdefault(key, {
                "agent": key[0], "model": key[1], "context": key[2], **dict.fromkeys(COUNT_KEYS, 0),
                "rates_per_million": {name: float(value) for name, value in rate.items()},
                "cache_writes_unrecorded": False, "source_url": entry["source_url"], "_usd": Decimal(0)})
            for name, value in zip(COUNT_KEYS, (uncached, cached, writes, writes_1h, output)):
                component[name] += value
            component["cache_writes_unrecorded"] |= writes_unrecorded
            component["_usd"] += amount
    if not covered:
        return None
    for component in components.values():
        component["usd"] = float(component.pop("_usd").quantize(Decimal("0.0001")))
    parts = list(components.values())
    return {"usd": float(total.quantize(Decimal("0.0001"))),
            "covered_tokens": covered, "recorded_tokens": recorded, "as_of": pricing["as_of"],
            "floor": any(part["cache_writes_unrecorded"] for part in parts),
            "components": parts,
            "unpriced": [{"agent": agent, "model": model, "tokens": count}
                         for (agent, model), count in sorted(unpriced.items(), key=lambda item: -item[1]) if count]}


def valid_estimate(value):
    """Reject a displayed amount that cannot be rebuilt from its saved breakdown."""
    if not isinstance(value, dict) or not isinstance(value.get("components"), list) or not value["components"]:
        return False
    try:
        total = Decimal(0)
        covered = 0
        for part in value["components"]:
            rates = {key: _rate(price) for key, price in part["rates_per_million"].items() if price is not None}
            counts = {key: part.get(key, 0) for key in COUNT_KEYS}
            if not part.get("source_url") or any(type(count) is not int or count < 0 for count in counts.values()):
                return False
            if (any(rates.get(key) is None for key in RATE_KEYS)
                    or (counts["cache_write_tokens"] and rates.get("cache_write_per_million") is None)
                    or (counts["cache_write_1h_tokens"] and rates.get("cache_write_1h_per_million") is None)):
                return False
            amount = (counts["noncached_input_tokens"] * rates["input_per_million"]
                      + counts["cached_input_tokens"] * rates["cached_input_per_million"]
                      + counts["cache_write_tokens"] * rates.get("cache_write_per_million", 0)
                      + counts["cache_write_1h_tokens"] * rates.get("cache_write_1h_per_million", 0)
                      + counts["output_tokens"] * rates["output_per_million"]) / 1_000_000
            if amount.quantize(Decimal("0.0001")) != _rate(part.get("usd")):
                return False
            total += amount
            covered += sum(counts.values())
        return (total.quantize(Decimal("0.0001")) == _rate(value.get("usd"))
                and covered == value.get("covered_tokens")
                and type(value.get("recorded_tokens")) is int
                and value["recorded_tokens"] >= covered)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False
