"""Turn a saved share report into the exact fields a card displays.

Both the PNG and the HTML preview read from `view()`, so visibility rules live
in one place: anonymous and private-projects cards never see named fields.
"""

import re

from pricing import valid_estimate

REPO_LABEL = "github.com/valenxi0/where-did-my-usage-go"
REPO_URL = "https://github.com/valenxi0/Where-Did-My-Usage-Go"
FALLBACK_ROAST = "The tokens would like a word."
X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,30}$")
TIERS = {"warmup": 1, "regular": 2, "heavy": 3, "unhinged": 4, "legendary": 5}
TIER_LABELS = {"warmup": "Warm-up", "regular": "Regular", "heavy": "Heavy", "unhinged": "Unhinged",
               "legendary": "Legendary", "unknown": "Unrated"}


def normalize_x_handle(value):
    if not isinstance(value, str):
        return None
    handle = value.strip().lstrip("@")
    return handle if X_HANDLE.fullmatch(handle) else None


def number(value):
    return f"{value:,}" if isinstance(value, int) and value >= 0 else "Unknown"


def compact(value):
    if not isinstance(value, (int, float)) or value < 0:
        return "?"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.0f}K"
    return number(int(value))


def plural(count, noun):
    return f"{number(count)} {noun}{'' if count == 1 else 's'}"


def price(amount):
    """Card-sized dollars: cents only below $100."""
    return f"${amount:,.0f}" if amount >= 100 else usd(amount)


def trend_label(comparison, hours):
    if not isinstance(comparison, dict):
        return None
    previous, current = comparison.get("previous_tokens"), comparison.get("current_tokens")
    if not isinstance(previous, int) or not isinstance(current, int) or previous <= 0:
        return None
    span = {24: "day", 168: "week", 720: "month"}.get(round(hours or 0), "window")
    ratio = current / previous
    if ratio >= 2:
        return f"{ratio:.1f}x previous {span}"
    change = round((ratio - 1) * 100)
    return f"{'+' if change >= 0 else '-'}{abs(change)}% vs previous {span}"


def hour_label(hour):
    return f"{hour % 12 or 12}{'am' if hour < 12 else 'pm'}"


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def busiest(card):
    """`Tuesdays around 10pm`, or just `around 10pm` when the window is too short for a weekday."""
    if not card["hours"] or sum(card["hours"]) < 10:
        return None
    hour = hour_label(max(range(24), key=lambda value: card["hours"][value]))
    days = card["weekdays"]
    if days and (card["window_hours"] or 0) >= 72 and sum(1 for count in days if count) >= 2:
        return f"{WEEKDAYS[max(range(7), key=lambda value: days[value])]}s around {hour}"
    return f"around {hour}"


def stat_cells(card, limit=4):
    """The most telling stats first; the card has room for four."""
    cells = []
    if card["resets"]:
        cells.append(("resets used", str(card["resets"])))
    if card["plan_multiple"] is not None:
        cells.append(("vs your plans", f"{card['plan_multiple']:.0f}x" if card["plan_multiple"] >= 10 else f"{card['plan_multiple']:.1f}x"))
    if card["limit"]:
        period = {300: "5h", 1440: "daily", 10080: "weekly"}.get(card["limit"]["window_minutes"], "limit")
        cells.append((f"{card['limit']['agent'].lower()} {period}", f"{card['limit']['used_percent']:.0f}%"))
    cells.append(("sessions", number(card["sessions"])))
    if card["cache_share"] is not None:
        cells.append(("cache reads", f"{card['cache_share']}%"))
    if card["per_hour"] is not None:
        cells.append(("per hour", compact(card["per_hour"])))
    cells.append(("tools", str(len(card["agents"]))))
    return cells[:limit]


def usd(amount):
    return f"${amount:,.2f}" if amount >= 0.01 else f"${amount:,.4f}"


def api_cost_label(value):
    if not valid_estimate(value):
        return "API equivalent unavailable"
    covered = value.get("covered_tokens")
    recorded = value.get("recorded_tokens")
    if isinstance(covered, int) and isinstance(recorded, int) and covered < recorded:
        coverage = f" · {compact(covered)}/{compact(recorded)} tokens priced"
    elif value.get("unmeasured_sessions"):
        count = value["unmeasured_sessions"]
        coverage = f" · {count} session{'s' if count != 1 else ''} unmeasured"
    elif value.get("unchecked_sources"):
        coverage = " · coverage incomplete"
    else:
        coverage = " · recorded tokens priced"
    return f"Est. API equivalent {usd(value['usd'])}{coverage}"


def _share(tokens, total):
    return round(tokens / total * 100) if isinstance(tokens, int) and total else None


def view(data, visibility):
    anonymous = visibility == "anonymous"
    hide_projects = visibility in ("anonymous", "private-projects")
    agents = [item for item in data.get("agents", []) if isinstance(item, dict)]
    projects = [item for item in data.get("projects", []) if isinstance(item, dict)]
    total = data.get("total_tokens")
    if not isinstance(total, int) or total < 0:
        known = [item["tokens"] for item in agents if isinstance(item.get("tokens"), int)]
        total = sum(known) if known else None
    cached = data.get("cached_input_tokens")
    cached = max(0, min(cached, total)) if isinstance(cached, int) and isinstance(total, int) else None
    hours = data.get("window_hours")
    agent_total = sum(item["tokens"] for item in agents if isinstance(item.get("tokens"), int))
    project_total = sum(item["tokens"] for item in projects if isinstance(item.get("tokens"), int))

    project_rows = []
    for index, item in enumerate(projects, 1):
        if hide_projects:
            label, summary = item.get("anonymous_name") or f"Project {index}", item.get("anonymous_summary")
        else:
            label, summary = item.get("name") or f"Project {index}", item.get("summary")
        project_rows.append({"label": label, "summary": summary or "", "tokens": item.get("tokens"),
                             "sessions": item.get("sessions"), "share": _share(item.get("tokens"), project_total)})

    highlight = data.get("anonymous_highlight") if hide_projects else data.get("highlight")
    if not highlight:
        highlight = next((row["summary"] for row in project_rows if row["summary"]), None)
    name = (data.get("anonymous_display_name") if anonymous else data.get("display_name")) or "Player One"
    handle = None if anonymous else normalize_x_handle(data.get("x_handle"))
    if handle and name.casefold() == f"@{handle}".casefold():
        handle = None
    tier = data.get("roast_tier") if data.get("roast_tier") in TIER_LABELS else "unknown"
    resets = data.get("banked_resets_used")
    estimate = data.get("estimated_api_cost")
    return {
        "name": name,
        "handle": handle,
        "window": data.get("window") or "",
        "roast": (data.get("anonymous_roast") if anonymous else data.get("roast")) or FALLBACK_ROAST,
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "tier_level": TIERS.get(tier, 0),
        "total": total,
        "cached": cached,
        "cache_share": _share(cached, total),
        "per_hour": round(total / hours) if isinstance(total, int) and isinstance(hours, (int, float)) and hours > 0 else None,
        "sessions": sum(max(0, int(item.get("sessions") or 0)) for item in agents),
        "agents": [{"label": item.get("name") or "Unknown tool", "tokens": item.get("tokens"),
                    "sessions": item.get("sessions"), "share": _share(item.get("tokens"), agent_total)}
                   for item in agents],
        "projects": project_rows,
        "highlight": highlight,
        "notes": [note for note in ((data.get("anonymous_notes") if hide_projects else data.get("notes")) or [])
                  if isinstance(note, str)],
        "resets": resets if isinstance(resets, int) and resets > 0 else None,
        "api_usd": estimate["usd"] if valid_estimate(estimate) else None,
        "api_partial": bool(valid_estimate(estimate) and estimate.get("partial")),
        "api_floor": bool(valid_estimate(estimate) and estimate.get("floor")),
        "trend": trend_label(data.get("comparison"), hours),
        "limit": data.get("plan_limit") if isinstance(data.get("plan_limit"), dict) else None,
        "plan_multiple": (estimate["usd"] / data["subscription"]["prorated_usd"]
                          if valid_estimate(estimate) and isinstance(data.get("subscription"), dict)
                          and data["subscription"].get("prorated_usd") else None),
        "hours": data.get("prompt_hours") if isinstance(data.get("prompt_hours"), list) and len(data["prompt_hours"]) == 24 else None,
        "weekdays": data.get("prompt_weekdays") if isinstance(data.get("prompt_weekdays"), list) and len(data["prompt_weekdays"]) == 7 else None,
        "window_hours": hours if isinstance(hours, (int, float)) else None,
        "api_label": api_cost_label(estimate),
    }
