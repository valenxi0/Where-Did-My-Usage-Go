"""Rebuild the fictional share card from synthetic usage and the bundled price table."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "skills/where-did-my-usage-go/scripts"))

from draft import draft  # noqa: E402
from pricing import BUNDLED, load  # noqa: E402


DEMO_PLANS = [{"name": "ChatGPT Plus", "usd_per_month": 20}, {"name": "Claude Pro", "usd_per_month": 20}]


def build():
    activity = json.loads((ROOT / "demo-activity.json").read_text())
    share = draft(activity, "Sample Dev", "Player One", "sampledev", load(BUNDLED), DEMO_PLANS)
    share["window"] = "Example · Last 7 days"
    share["highlight"] = "Built search filters and fixed a stubborn save bug."
    share["anonymous_highlight"] = "Built search filters and fixed a save bug."
    summaries = {
        "Recipe Atlas": ("Built search filters and cleaned up the mobile recipe view.",
                         "Built search filters and polished a mobile view."),
        "Weekend Game": ("Prototyped a new level and fixed a stubborn save bug.",
                         "Prototyped a new level and fixed a save bug."),
        "Ideas Lab": ("Explored three directions for a new tool.",
                      "Explored three directions for a new tool."),
    }
    for project in share["projects"]:
        project["summary"], project["anonymous_summary"] = summaries[project["name"]]
    share["notes"].insert(0, "Fictional example with real list prices.")
    share["anonymous_notes"] = share["notes"].copy()
    return share


if __name__ == "__main__":
    (ROOT / "demo.json").write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n")
