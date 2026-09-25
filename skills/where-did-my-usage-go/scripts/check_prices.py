#!/usr/bin/env python3
"""Compare the bundled price table with OpenRouter's public model list.

Makes one network request to https://openrouter.ai/api/v1/models. First-party
provider pages stay authoritative: a mismatch is printed for a human to check,
never applied automatically. With --write-missing, models that appear in an
activity file but have no first-party price are written to an override table
using OpenRouter's rate, labeled with OpenRouter as the source.
"""

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

from paths import private_dir
from pricing import BUNDLED, load, model_key, stale

OPENROUTER = "https://openrouter.ai/api/v1/models"
FIELDS = {"input_per_million": "prompt", "cached_input_per_million": "input_cache_read",
          "cache_write_per_million": "input_cache_write", "output_per_million": "completion"}


def openrouter_rates(models):
    """Index OpenRouter's standard (non-batch) listings by price-table key."""
    rates = {}
    for item in models:
        slug = item.get("id", "")
        if ":" in slug or slug.startswith("~"):
            continue
        key = model_key(slug)
        pricing = item.get("pricing") or {}
        rates[key] = {name: round(float(pricing.get(field) or 0) * 1_000_000, 6) for name, field in FIELDS.items()}
        rates[key]["source_url"] = f"https://openrouter.ai/{slug}"
    return rates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activity", type=Path, default=private_dir() / "activity.json")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on an unexplained mismatch or a stale table (for CI)")
    parser.add_argument("--write-missing", type=Path, metavar="PATH",
                        help="Write OpenRouter rates for unpriced models in --activity to this override file")
    args = parser.parse_args()
    with urllib.request.urlopen(OPENROUTER, timeout=30) as response:
        remote = openrouter_rates(json.load(response)["data"])
    bundled = load(BUNDLED)["models"]
    mismatches = 0
    for key, entry in sorted(bundled.items()):
        theirs = remote.get(key)
        if theirs is None:
            print(f"  not on OpenRouter  {key}")
            continue
        diffs = [f"{name.removesuffix('_per_million')} {entry[name]} vs {theirs[name]}" for name in FIELDS
                 if entry.get(name) is not None and abs(float(entry[name]) - theirs[name]) > 1e-9]
        if diffs and entry.get("openrouter_differs"):
            print(f"{'known':>9}  {key}  ({entry['openrouter_differs']})")
            continue
        mismatches += bool(diffs)
        print(f"{'MISMATCH' if diffs else 'ok':>9}  {key}" + (f"  ({'; '.join(diffs)})" if diffs else ""))
    print(f"{mismatches} mismatch(es). Check each against the provider's own page before changing references/pricing.json.")
    table = load(BUNDLED)
    if stale(table):
        print(f"The bundled table was checked {table['as_of']}; it is stale.")
    if args.strict and (mismatches or stale(table)):
        sys.exit(1)
    if args.write_missing:
        activity = json.loads(args.activity.read_text(encoding="utf-8"))
        used = {model_key(usage.get("model")) for session in activity.get("sessions", [])
                for usage in session.get("model_usage") or [] if isinstance(usage, dict)}
        # OpenRouter reports 0 for a write rate a model does not charge; omit it so it is not priced at zero.
        found = [{"model": key, **{name: value for name, value in remote[key].items()
                                   if value or name != "cache_write_per_million"}}
                 for key in sorted(filter(None, used)) if key not in bundled and key in remote]
        args.write_missing.write_text(json.dumps({"as_of": date.today().isoformat(), "models": found}, indent=2) + "\n",
                                      encoding="utf-8")
        print(f"Wrote {len(found)} OpenRouter-priced model(s) to {args.write_missing}; review, then pass it to draft.py --pricing.")


if __name__ == "__main__":
    main()
