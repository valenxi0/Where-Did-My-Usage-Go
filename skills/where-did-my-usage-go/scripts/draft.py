#!/usr/bin/env python3
"""Create a private, editable share-card draft from collected activity."""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paths import ensure_parent, private_dir
from card import compact, hour_label, normalize_x_handle, price, usd
import prefs
from prefs import parse_plan
from pricing import BUNDLED, estimate, load, stale


def recorded_tokens(session):
    usage = session.get("tokens")
    if not isinstance(usage, dict):
        return None
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)


def group_sessions(sessions, key):
    groups = defaultdict(list)
    for session in sessions:
        if isinstance(session, dict):
            groups[str(session.get(key) or "Unknown")].append(session)
    return groups


def total_or_unknown(sessions):
    values = [recorded_tokens(session) for session in sessions]
    known = [value for value in values if value is not None]
    return sum(known) if known else None


# Tokens per hour, averaged over the window (never less than a day, so one frantic hour cannot
# reach the top). Weekly equivalents: under ~17M, ~170M, ~1B, ~5B, and above.
TIER_FLOORS = (("warmup", 0), ("regular", 100_000), ("heavy", 1_000_000), ("unhinged", 6_000_000), ("legendary", 30_000_000))


def project_kind(path):
    """A generic, non-identifying label from the project's manifest files, e.g. `Swift app`."""
    root = Path(path)
    try:
        names = {entry.name for entry in root.iterdir()} if root.is_dir() else set()
    except OSError:
        return None
    if names & {"Package.swift"} or any(name.endswith(".xcodeproj") for name in names):
        return "Swift app"
    for manifest, kind in (("Cargo.toml", "Rust project"), ("go.mod", "Go project"), ("pubspec.yaml", "Flutter app"),
                           ("build.gradle", "Android app"), ("build.gradle.kts", "Android app"), ("Gemfile", "Ruby project")):
        if manifest in names:
            return kind
    if "package.json" in names:
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
            dependencies = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
        except (OSError, ValueError, AttributeError):
            dependencies = {}
        for dependency, kind in (("next", "Next.js app"), ("expo", "React Native app"), ("react-native", "React Native app"),
                                 ("electron", "Electron app"), ("svelte", "Svelte app"), ("vue", "Vue app"), ("react", "React app")):
            if dependency in dependencies:
                return kind
        return "TypeScript project" if "tsconfig.json" in names else "JavaScript project"
    if names & {"pyproject.toml", "requirements.txt", "setup.py"}:
        return "Python project"
    if "SKILL.md" in names or (root / "skills").is_dir():
        return "Agent skill"
    return None


def roast_tier(total_tokens, hours):
    if total_tokens is None:
        return "unknown"
    hourly = total_tokens / max(hours, 24)
    return next(name for name, floor in reversed(TIER_FLOORS) if hourly >= floor)


def roast_lines(facts):
    """Every roast the facts support, best first.

    Habits beat statistics: a specific thing the user kept doing is funnier than
    a ratio. Price and trend already headline the card, so they come last.
    """
    total, span, said = facts["total"], facts["span"], facts["habits"]
    prompts = max(said["prompts"], 1)
    candidates = [
        (said["stuck"] >= 8,
         lambda: f"{said['stuck']} prompts were some version of 'still broken'. Both of you know whose fault it was."),
        (said["nudges"] >= 10 and said["nudges"] / prompts >= 0.1,
         lambda: f"{said['nudges']} prompts were just 'continue' or 'yes'. That's not pair programming, that's supervising."),
        (facts["limit"] is not None and facts["limit"]["used_percent"] >= 100 and facts["limit"]["window_minutes"] >= 10080,
         lambda: f"{facts['limit']['used_percent']:.0f}% of a weekly {facts['limit']['agent']} limit, in one {span}. That's not how weeks work."),
        (total is not None and said["prompts"] >= 5 and total / said["prompts"] >= 1_000_000,
         lambda: f"You typed {said['prompts']} prompts. The agents answered with {compact(total)} tokens. Brevity is a gift you only give yourself."),
        (facts["catchphrase"] is not None and facts["catchphrase"][1] >= 5,
         lambda: f"You typed '{facts['catchphrase'][0]}' {facts['catchphrase'][1]} times. Every manager needs a catchphrase."),
        (facts["peak_hour"] is not None and facts["peak_hour"] < 5,
         lambda: f"Your busiest hour was {hour_label(facts['peak_hour'])}. The agents don't sleep, and apparently neither do you."),
        (facts["api_usd"] is not None and said["prompts"] >= 5 and facts["api_usd"] / said["prompts"] >= 2,
         lambda: f"At list prices, every prompt you typed cost {usd(facts['api_usd'] / said['prompts'])}. Choose your words accordingly."),
        (facts["top_model"] is not None and facts["top_model"][1] >= 100,
         lambda: f"{facts['top_model'][0]} alone ran up {price(facts['top_model'][1])} at list prices. It was not there for the easy questions."),
        (facts["top_project_share"] is not None and facts["top_project_share"] >= 60 and facts["project_count"] >= 3,
         lambda: f"{facts['top_project_share']}% of it went into one project. The other projects have noticed."),
        (said["late_night"] >= 10 and said["late_night"] / prompts >= 0.2,
         lambda: f"{round(said['late_night'] / prompts * 100)}% of your prompts went out between midnight and 5am. Nothing good gets merged at 3am."),
        (said["polite"] >= 15,
         lambda: f"You said please {said['polite']} times. Smart. They'll remember who was nice."),
        (facts["cache_share"] is not None and facts["cache_share"] >= 95,
         lambda: f"{facts['cache_share']}% of it was cache reads. The model mostly reread your repo."),
        (facts["top_agent_share"] is not None and facts["top_agent_share"] >= 90 and facts["agent_count"] > 1,
         lambda: f"{facts['top_agent']} did {facts['top_agent_share']}% of it. The other tools were moral support."),
        (facts["per_hour"] is not None and facts["per_hour"] >= 1_000_000,
         lambda: f"{compact(facts['per_hour'])} tokens an hour, averaged over every hour, including the ones you slept."),
        (facts["sessions"] >= 50,
         lambda: f"{facts['sessions']} sessions. At some point this stopped being assistance and became management."),
        (facts["agent_count"] >= 4,
         lambda: f"{facts['agent_count']} coding agents in one {span}. Nobody here is getting a performance review."),
        (total is not None and facts["tier"] == "warmup",
         lambda: f"{compact(total)} tokens. Some system prompts are longer than that."),
        (facts["plan_multiple"] is not None and facts["plan_multiple"] >= 3,
         lambda: f"At list prices that's {facts['plan_multiple']:.0f}x what your plans cost for the {span}. Someone is subsidizing you."),
        (facts["plan_multiple"] is None and facts["api_usd"] is not None and facts["api_usd"] >= 200,
         lambda: "At list prices, the subscription is doing a lot of heavy lifting."),
        (facts["change"] is not None and facts["change"] >= 2,
         lambda: f"More than double the previous {span}. Totally normal hobby behavior."),
    ]
    if total is None:
        return ["No token counts on record. Legally, none of this happened."]
    lines = [line() for matched, line in candidates if matched]
    return lines or [f"{compact(total)} tokens across {facts['sessions']} sessions, one quick question at a time."]


def roast_material(facts, projects, total):
    """Plain facts (not jokes) for the agent to combine with what was actually built."""
    said, lines = facts["habits"], []
    if total is not None:
        lines.append(f"{compact(total)} tokens from {said['prompts']} typed prompts across {facts['sessions']} sessions")
    for project in projects[:3]:
        if isinstance(project.get("tokens"), int):
            lines.append(f"{project['name']} (anonymous: {project['anonymous_name']}): {compact(project['tokens'])} tokens")
    if facts["api_usd"] is not None:
        lines.append(f"{usd(facts['api_usd'])} at API list prices")
    if facts["top_model"]:
        lines.append(f"Most expensive model: {facts['top_model'][0]} at {price(facts['top_model'][1])}")
    if facts["limit"]:
        lines.append(f"{facts['limit']['used_percent']:.0f}% of a {facts['limit']['window_minutes'] // 1440}-day {facts['limit']['agent']} limit, over {facts['limit']['cycles']} reset cycle(s)")
    if facts["change"]:
        lines.append(f"{facts['change']:.1f}x the previous {facts['span']}")
    if facts["catchphrase"]:
        lines.append(f"Most typed stock phrase: '{facts['catchphrase'][0]}' x{facts['catchphrase'][1]}")
    if facts["peak_hour"] is not None:
        lines.append(f"Busiest prompting hour: {hour_label(facts['peak_hour'])}")
    lines += [f"{label}: {said[key]}" for key, label in (("stuck", "'Still broken'-style prompts"), ("nudges", "Bare 'continue'/'yes' prompts"),
                                                          ("polite", "Prompts saying please or thanks"), ("late_night", "Prompts between midnight and 5am"))
              if said[key]]
    return lines


def comparison(activity, sessions):
    """Current vs previous window over the agents both windows parsed automatically."""
    previous = activity.get("previous_window")
    if not isinstance(previous, dict) or not isinstance(previous.get("total_tokens"), int) or previous["total_tokens"] <= 0:
        return None
    agents = set(previous.get("agents") or [])
    current = total_or_unknown([session for session in sessions if session.get("agent") in agents])
    return {"previous_tokens": previous["total_tokens"], "current_tokens": current} if current else None


def window_label(start, end, hours):
    """Short card label such as `Last 7 days · Sep 17-23, 2026`.

    The dates name the days covered, so a window ending at midnight stops at the day before.
    """
    span = f"Last {round(hours / 24)} days" if hours >= 48 and round(hours) % 24 == 0 else f"Last {round(hours)} hours"
    end = end - timedelta(microseconds=1)
    if (start.year, start.month, start.day) == (end.year, end.month, end.day):
        dates = f"{end:%b} {end.day}, {end.year}"
    elif (start.year, start.month) == (end.year, end.month):
        dates = f"{end:%b} {start.day}-{end.day}, {end.year}"
    elif start.year == end.year:
        dates = f"{start:%b} {start.day} - {end:%b} {end.day}, {end.year}"
    else:
        dates = f"{start:%b} {start.day}, {start.year} - {end:%b} {end.day}, {end.year}"
    return f"{span} · {dates}"


def verified_banked_resets(activity, start, end):
    """Count distinct, documented Codex banked redemptions in the window."""
    seen = set()
    for event in activity.get("reset_events") or []:
        if not isinstance(event, dict) or event.get("provider") != "Codex":
            continue
        if event.get("kind") != "banked" or event.get("status") != "redeemed":
            continue
        if event.get("evidence_type") not in ("redemption_receipt", "account_history"):
            continue
        if not isinstance(event.get("evidence"), str) or not event["evidence"].strip():
            continue
        try:
            at = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, ValueError):
            continue
        if at.tzinfo is None:
            continue
        at = at.astimezone(timezone.utc)
        if start.astimezone(timezone.utc) <= at < end.astimezone(timezone.utc):
            event_id = event.get("id")
            seen.add(event_id if isinstance(event_id, str) and event_id else (at.isoformat(), event["evidence"].strip()))
    return len(seen)


def plan_limit_used(sessions):
    """Share of the longest plan window (usually weekly) used inside the report window.

    Each reset starts a new cycle, so usage is summed across cycles rather than read
    from the latest snapshot. Usage before the first in-window snapshot of a cycle is
    not visible, so this can undercount slightly, never overcount.
    """
    cycles, plan, agent = {}, None, None
    for session in sessions:
        limits = session.get("plan_limits")
        if not isinstance(limits, dict):
            continue
        plan, agent = limits.get("plan") or plan, session.get("agent")
        for cycle in limits.get("cycles") or []:
            key = (cycle["window_minutes"], cycle["reset_hour"])
            low, high = cycles.get(key, (cycle["low"], cycle["high"]))
            cycles[key] = (min(low, cycle["low"]), max(high, cycle["high"]))
    if not cycles:
        return None
    minutes = max(key[0] for key in cycles)
    used = sum(high - low for (length, _), (low, high) in cycles.items() if length == minutes)
    return {"agent": agent, "plan": plan, "window_minutes": minutes, "used_percent": round(used, 1),
            "cycles": sum(length == minutes for length, _ in cycles)}


def plan_cost(plans, hours):
    """Subscription cost prorated to the window, for a list-price comparison."""
    plans = [plan for plan in plans or [] if isinstance(plan, dict) and plan.get("usd_per_month", 0) > 0]
    if not plans:
        return None
    monthly = sum(plan["usd_per_month"] for plan in plans)
    return {"names": [plan["name"] for plan in plans], "usd_per_month": monthly,
            "prorated_usd": round(monthly * hours / (24 * 30.44), 2)}


def draft(activity, display_name="Player One", anonymous_display_name="Player One", x_handle=None, pricing=None,
          plans=None):
    """Build share.json. `pricing` is a table from `pricing.load()`; None skips the API equivalent."""
    sessions = activity.get("sessions") or []
    start = datetime.fromisoformat(activity["window_start"]).astimezone()
    end = datetime.fromisoformat(activity["window_end"]).astimezone()
    hours = (end - start).total_seconds() / 3600
    banked_resets_used = verified_banked_resets(activity, start, end)
    total_tokens = total_or_unknown(sessions)
    api_cost = estimate(sessions, pricing)
    cached_tokens = sum(
        max(0, int((session.get("tokens") or {}).get("cached_input_tokens") or 0))
        for session in sessions if isinstance(session, dict)
    ) if total_tokens is not None else None
    tier = roast_tier(total_tokens, hours)
    subscription = plan_cost(plans, hours)
    trend = comparison(activity, sessions)
    agents = []
    ranked_agents = sorted(
        group_sessions(sessions, "agent").items(),
        key=lambda pair: (-(total_or_unknown(pair[1]) or 0), -len(pair[1])),
    )
    for name, group in ranked_agents[:3]:
        agents.append({"name": name, "sessions": len(group), "tokens": total_or_unknown(group)})
    if len(ranked_agents) > 3:
        remaining = [session for _, group in ranked_agents[3:] for session in group]
        agents.append({"name": "Other tools", "sessions": len(remaining), "tokens": total_or_unknown(remaining)})
    projects = []
    ranked = sorted(
        group_sessions(sessions, "project").items(),
        key=lambda pair: (-(total_or_unknown(pair[1]) or 0), -len(pair[1])),
    )
    kinds = []
    for index, (path, group) in enumerate(ranked[:3], 1):
        name = Path(path).name if path != "Unknown" else "Unknown project"
        kind = project_kind(path)
        kinds.append(kind)
        if kind is None:
            label = f"Project {index}"
        elif kinds.count(kind) > 1:
            label = f"{kind} {kinds.count(kind)}"
        else:
            label = kind
        projects.append({
            "name": name or "Unknown project", "anonymous_name": label,
            "summary": "", "anonymous_summary": "",
            "sessions": len(group), "tokens": total_or_unknown(group),
        })
    if len(ranked) > 3:
        remaining = [session for _, group in ranked[3:] for session in group]
        projects.append({
            "name": "Other projects", "anonymous_name": "Other projects",
            "summary": "", "anonymous_summary": "",
            "sessions": len(remaining), "tokens": total_or_unknown(remaining),
        })
    window = window_label(start, end, hours)
    active_names = {str(session.get("agent")) for session in sessions if isinstance(session, dict)}
    unchecked_sources = [source for source in activity.get("sources", [])
                         if str(source.get("status", "")).startswith("detected,")
                         and source.get("activity_in_window") is not False
                         and source.get("agent") not in active_names]
    unmeasured = sum(recorded_tokens(session) is None for session in sessions)
    notes = ["Recorded transcript tokens, not plan quota or a bill."]
    if api_cost:
        api_cost["unmeasured_sessions"] = unmeasured
        api_cost["unchecked_sources"] = len(unchecked_sources)
        api_cost["partial"] = (api_cost["covered_tokens"] < api_cost["recorded_tokens"]
                               or unmeasured > 0 or bool(unchecked_sources))
        notes.append(f"API equivalent uses list prices checked {api_cost['as_of']}; it is not what you paid.")
        if api_cost["covered_tokens"] < api_cost["recorded_tokens"]:
            share = round(api_cost["covered_tokens"] / api_cost["recorded_tokens"] * 100)
            notes.append(f"{share}% of recorded tokens had a public model price; the rest are not in the total.")
        if api_cost["floor"]:
            notes.append("Some cache writes were not logged and are priced as plain input, so it is a minimum.")
    else:
        notes.append("API equivalent unavailable: no recorded model matched a verified price.")
    if unchecked_sources:
        notes.append("Coverage incomplete; totals include verified activity only.")
    if unmeasured:
        notes.append("Some sessions have no token data; token totals are partial.")
    notes.append("Tokenizers and cache reporting vary by agent; project shares are approximate.")
    if len(ranked) > 3:
        notes.append("The three projects with the most recorded tokens are shown; others are grouped.")
    if banked_resets_used:
        notes.append(f"{banked_resets_used} verified Codex banked reset{'s' if banked_resets_used != 1 else ''} redeemed in this window.")
    top_agent = agents[0] if agents and isinstance(agents[0].get("tokens"), int) and total_tokens else None
    said = {key: sum(int((session.get("habits") or {}).get(key) or 0) for session in sessions)
            for key in ("prompts", "nudges", "stuck", "polite", "late_night")}
    weekday_prompts = [sum(((session.get("habits") or {}).get("weekdays") or [0] * 7)[day] for session in sessions)
                       for day in range(7)]
    hourly_prompts = [sum(((session.get("habits") or {}).get("hours") or [0] * 24)[hour] for session in sessions)
                      for hour in range(24)]
    value = (api_cost["usd"] / subscription["prorated_usd"]
             if api_cost and subscription and subscription["prorated_usd"] else None)
    phrases = {}
    for session in sessions:
        for phrase, count in ((session.get("habits") or {}).get("phrases") or {}).items():
            phrases[phrase] = phrases.get(phrase, 0) + count
    by_model = {}
    for component in (api_cost or {}).get("components", []):
        by_model[component["model"]] = by_model.get(component["model"], 0) + component["usd"]
    project_total = sum(project["tokens"] for project in projects if isinstance(project.get("tokens"), int))
    facts = {
        "catchphrase": max(phrases.items(), key=lambda item: item[1]) if phrases else None,
        "peak_hour": max(range(24), key=lambda hour: hourly_prompts[hour]) if sum(hourly_prompts) >= 10 else None,
        "top_model": max(by_model.items(), key=lambda item: item[1]) if by_model else None,
        "top_project_share": round(projects[0]["tokens"] / project_total * 100)
                             if projects and isinstance(projects[0].get("tokens"), int) and project_total else None,
        "project_count": len(ranked),
        "limit": plan_limit_used(sessions),
        "plan_multiple": value,
        "habits": said,
        "total": total_tokens, "tier": tier, "sessions": len(sessions), "agent_count": len(ranked_agents),
        "span": {24: "day", 168: "week", 720: "month"}.get(round(hours), "window"),
        "api_usd": api_cost["usd"] if api_cost else None,
        "change": trend["current_tokens"] / trend["previous_tokens"] if trend else None,
        "cache_share": round(cached_tokens / total_tokens * 100) if total_tokens and cached_tokens is not None else None,
        "top_agent": top_agent["name"] if top_agent else None,
        "top_agent_share": round(top_agent["tokens"] / total_tokens * 100) if top_agent else None,
        "per_hour": total_tokens / hours if total_tokens is not None and hours else None,
    }
    roasts = roast_lines(facts)
    material = roast_material(facts, projects, total_tokens)
    return {
        "title": "Where did my usage go?", "window": window, "window_hours": round(hours, 2),
        "window_end": end.isoformat(),
        "display_name": display_name, "anonymous_display_name": anonymous_display_name,
        "x_handle": normalize_x_handle(x_handle),
        "total_tokens": total_tokens, "cached_input_tokens": cached_tokens,
        "estimated_api_cost": api_cost,
        "banked_resets_used": banked_resets_used or None,
        "roast_tier": tier,
        "roast": roasts[0], "anonymous_roast": roasts[0], "roast_options": roasts, "roast_material": material,
        "comparison": trend,
        "plan_limit": plan_limit_used(sessions),
        "subscription": subscription,
        "prompt_hours": hourly_prompts if sum(hourly_prompts) else None,
        "prompt_weekdays": weekday_prompts if sum(weekday_prompts) else None,
        "agents": agents, "projects": projects,
        "notes": notes, "anonymous_notes": notes.copy(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=private_dir() / "activity.json")
    parser.add_argument("--output", type=Path, default=private_dir() / "share.json")
    parser.add_argument("--name", help="Display name for the named card (remembered; default Player One)")
    parser.add_argument("--anonymous-name", default="Player One", help="Alias for the anonymous card")
    parser.add_argument("--x-handle", help="Optional X handle for the named card, with or without @ (remembered)")
    parser.add_argument("--plan", action="append", default=[], metavar="NAME=USD",
                        help="A subscription and its monthly price, e.g. 'ChatGPT Pro=200'; repeatable, remembered")
    parser.add_argument("--no-plan", action="store_true", help="Forget remembered plans")
    parser.add_argument("--pricing", type=Path, action="append", default=[],
                        help="Extra verified price table merged over the bundled one; repeatable")
    parser.add_argument("--no-pricing", action="store_true", help="Skip the API equivalent entirely")
    args = parser.parse_args()
    if args.x_handle and not normalize_x_handle(args.x_handle):
        parser.error("X handle must contain only letters, numbers, or underscores")
    try:
        plans = [parse_plan(value) for value in args.plan]
    except ValueError as error:
        parser.error(str(error))
    remembered = prefs.load()
    name = args.name or remembered.get("name") or "Player One"
    handle = args.x_handle if args.x_handle is not None else remembered.get("x_handle")
    plans = [] if args.no_plan else plans or remembered.get("plans") or []
    prefs.save(name=name, x_handle=handle, plans=plans)
    activity = json.loads(args.input.read_text(encoding="utf-8"))
    pricing = None if args.no_pricing else load(BUNDLED, *args.pricing)
    result = draft(activity, name, args.anonymous_name, handle, pricing, plans)
    if pricing and stale(pricing):
        print(f"Price table was checked {pricing['as_of']}; refresh it (references/api-pricing.md) before sharing.")
    for item in (result["estimated_api_cost"] or {}).get("unpriced", []):
        print(f"No verified price: {item['agent']} / {item['model']} ({item['tokens']:,} tokens)")
    ensure_parent(args.output)
    if args.output.exists():
        # A redraft must never silently discard hand-edited summaries and roasts.
        backup = args.output.with_name(f"{args.output.stem}-{datetime.now():%Y%m%d-%H%M%S}.json")
        args.output.replace(backup)
        print(f"Kept the previous draft as {backup}")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(f"Wrote private draft to {args.output}; review names, summaries, and coverage before sharing.")


if __name__ == "__main__":
    main()
