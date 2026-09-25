#!/usr/bin/env python3
"""Collect local coding-agent activity into a private JSON file.

No network calls, pricing estimates, or transcript content in stdout.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paths import ensure_parent, private_dir

# OpenAI bills a whole request at long-context rates above this many input tokens.
LONG_CONTEXT_INPUT = 272_000
# Agents whose histories this script parses by itself; only these feed the previous-window trend.
AUTO_AGENTS = ("Codex", "Claude Code", "OpenCode", "Factory Droid", "Kimi Code", "Grok", "Devin")


def instant(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def epoch_instant(value):
    try:
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def lines(path):
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item
    except (OSError, UnicodeError):
        return


def excerpt(value, limit=400):
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    if isinstance(value, list):
        return excerpt(" ".join(part.get("text", "") for part in value if isinstance(part, dict)), limit)
    return ""


NUDGE = re.compile(r"^(continue|go on|keep going|proceed|yes|yep|yeah|ok|okay|do it|go|next|sure|lgtm|y)\W*$", re.I)
STUCK = re.compile(r"\b(still (broken|not working|failing|wrong|the same)|(doesn'?t|does not|not) work(ing)?|same (error|issue|problem)"
                   r"|broke(n)? again|try again|wtf|why (is|does|did|isn'?t|doesn'?t))\b", re.I)
# Only these stock phrases are ever counted verbatim, so no project or personal text can be stored.
STOCK_PHRASES = ("continue", "go on", "keep going", "proceed", "yes", "ok", "okay", "do it", "go", "next", "lgtm",
                 "fix it", "try again", "again", "still broken", "ship it", "run it", "test it", "commit", "push",
                 "commit and push", "deploy", "looks good", "perfect", "nice", "thanks", "why", "undo", "revert", "no")
POLITE = re.compile(r"\b(please|pls|thanks|thank you)\b", re.I)


def habits(said):
    """Count prompt habits for the roast. Stores counts only, never extra text.

    `said` holds (time, text) for each human prompt; tool output and harness
    notes (which start with `<` or `[`) are ignored.
    """
    human = [(at.astimezone(), text) for at, text in said if at and text and not text.startswith(("<", "[", "Caveat:"))]
    return {"prompts": len(human),
            "nudges": sum(bool(NUDGE.match(text.strip())) for _, text in human),
            "stuck": sum(bool(STUCK.search(text)) for _, text in human),
            "polite": sum(bool(POLITE.search(text)) for _, text in human),
            "late_night": sum(at.hour < 5 for at, _ in human),
            "hours": [sum(at.hour == hour for at, _ in human) for hour in range(24)],
            "weekdays": [sum(at.weekday() == day for at, _ in human) for day in range(7)],
            "phrases": {phrase: count for phrase in STOCK_PHRASES
                        if (count := sum(re.sub(r"[^a-z ]", "", text.lower()).strip() == phrase for _, text in human))}}


def token_fields(value):
    value = value if isinstance(value, dict) else {}
    fields = {key: max(0, int(value.get(key) or 0)) for key in ("input_tokens", "output_tokens", "cached_input_tokens")}
    if "cache_write_input_tokens" in value:
        fields["cache_write_tokens"] = max(0, int(value.get("cache_write_input_tokens") or 0))
    return fields


def codex_session(path, start, end):
    meta = {}
    events = []
    previous = {}
    prompts, said = [], []
    finals = []
    limit_cycles = {"plan": None, "cycles": {}}
    model = None
    by_model = {}
    write_known = {}
    for item in lines(path):
        kind = item.get("type")
        payload = item.get("payload") or {}
        at = instant(item.get("timestamp"))
        if kind == "session_meta":
            meta = payload
        elif kind == "turn_context":
            model = payload.get("model") or None
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            limits = payload.get("rate_limits")
            if at and start <= at < end and isinstance(limits, dict):
                track_limits(limit_cycles, limits)
            cumulative = info.get("total_token_usage")
            if isinstance(cumulative, dict):
                current = token_fields(cumulative)
                if current["input_tokens"] + current["output_tokens"] < previous.get("input_tokens", 0) + previous.get("output_tokens", 0):
                    previous = {}
                delta = {key: max(0, current[key] - previous.get(key, 0)) for key in current}
                previous = current
                if at and start <= at < end and any(delta.values()):
                    events.append((at, delta))
                    if model:
                        tier = (model, "long" if delta["input_tokens"] > LONG_CONTEXT_INPUT else None)
                        bucket = by_model.setdefault(tier, dict.fromkeys(delta, 0))
                        write_known[tier] = write_known.get(tier, True) and "cache_write_tokens" in delta
                        for key, value in delta.items():
                            bucket[key] = bucket.get(key, 0) + value
        elif at and start <= at < end and kind == "event_msg" and payload.get("type") == "user_message":
            value = excerpt(payload.get("message"))
            said.append((at, value))
            if value and len(prompts) < 5:
                prompts.append(value)
        elif at and start <= at < end and kind == "event_msg" and payload.get("type") == "agent_message":
            value = excerpt(payload.get("message"))
            if value:
                finals.append(value)
    if not events and not prompts:
        return None
    totals = {key: sum(delta[key] for _, delta in events) for key in ("input_tokens", "output_tokens", "cached_input_tokens")}
    for name, usage in by_model.items():
        if not write_known[name]:
            usage.pop("cache_write_tokens", None)
    return {
        "agent": "Codex", "session_id": meta.get("id") or path.stem,
        "project": meta.get("cwd") or "Unknown project",
        "tokens": totals if events else None,
        "model_usage": [{"model": name, **({"context": tier} if tier else {}), "tokens": usage}
                        for (name, tier), usage in by_model.items()],
        "prompts": prompts, "final_messages": finals[-3:], "habits": habits(said),
        "plan_limits": plan_limits(limit_cycles),
        "first_activity_at": min([at for at, _ in events], default=None).isoformat() if events else None,
    }


def track_limits(state, limits):
    """Keep the lowest and highest used percent seen in each plan window cycle."""
    state["plan"] = limits.get("plan_type") or state["plan"]
    for window in (limits.get("primary"), limits.get("secondary")):
        if not isinstance(window, dict) or not window.get("window_minutes") or window.get("used_percent") is None:
            continue
        # Reset times jitter by seconds between events; an hour bucket identifies the cycle.
        key = (int(window["window_minutes"]), round(float(window.get("resets_at") or 0) / 3600))
        used = float(window["used_percent"])
        low, high = state["cycles"].get(key, (used, used))
        state["cycles"][key] = (min(low, used), max(high, used))


def plan_limits(state):
    if not state["cycles"]:
        return None
    return {"plan": state["plan"], "cycles": [{"window_minutes": minutes, "reset_hour": hour, "low": low, "high": high}
                                              for (minutes, hour), (low, high) in sorted(state["cycles"].items())]}


def claude_session(path, start, end):
    responses = {}
    prompts, said = [], []
    finals = []
    project = None
    for item in lines(path):
        at = instant(item.get("timestamp"))
        if not at or not start <= at < end:
            continue
        project = item.get("cwd") or project
        kind = item.get("type")
        message = item.get("message") or {}
        if kind == "assistant" and isinstance(message, dict):
            usage = message.get("usage")
            response_id = message.get("id") or item.get("uuid")
            if response_id and isinstance(usage, dict):
                creation = usage.get("cache_creation") or {}
                if not isinstance(creation, dict):
                    creation = {}
                write_5m = max(0, int(creation.get("ephemeral_5m_input_tokens") or 0))
                write_1h = max(0, int(creation.get("ephemeral_1h_input_tokens") or 0))
                write_total = max(0, int(usage.get("cache_creation_input_tokens") or 0))
                current = {
                    "input_tokens": int(usage.get("input_tokens") or 0) + write_total + int(usage.get("cache_read_input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "cached_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
                }
                prior = responses.get(response_id, {})
                model = message.get("model")
                responses[response_id] = {key: max(0, current[key], prior.get(key, 0)) for key in current}
                responses[response_id]["model"] = model if isinstance(model, str) else prior.get("model")
                responses[response_id]["cache_write_tokens"] = max(write_5m, prior.get("cache_write_tokens", 0))
                responses[response_id]["cache_write_1h_tokens"] = max(write_1h, prior.get("cache_write_1h_tokens", 0))
                responses[response_id]["write_known"] = (write_5m + write_1h == write_total) and prior.get("write_known", True)
            content = message.get("content")
            if isinstance(content, list):
                value = excerpt(content)
                if value:
                    finals.append(value)
        elif kind == "user" and isinstance(message, dict) and not item.get("isMeta"):
            value = excerpt(message.get("content"))
            said.append((at, value))
            if value and len(prompts) < 5:
                prompts.append(value)
    if not responses and not prompts:
        return None
    totals = {key: sum(value[key] for value in responses.values()) for key in ("input_tokens", "output_tokens", "cached_input_tokens")}
    by_model = {}
    model_write_known = {}
    for value in responses.values():
        if not value.get("model"):
            continue
        bucket = by_model.setdefault(value["model"], dict.fromkeys((*totals, "cache_write_tokens", "cache_write_1h_tokens"), 0))
        model_write_known[value["model"]] = model_write_known.get(value["model"], True) and value.get("write_known", False)
        for key in bucket:
            bucket[key] += value.get(key, 0)
    for name, usage in by_model.items():
        if not model_write_known[name]:
            usage.pop("cache_write_tokens", None)
            usage.pop("cache_write_1h_tokens", None)
    return {
        "agent": "Claude Code", "session_id": path.stem,
        "project": project or "Unknown project",
        "tokens": totals if responses else None,
        "model_usage": [{"model": name, "tokens": usage} for name, usage in by_model.items()],
        "prompts": prompts, "final_messages": finals[-3:], "habits": habits(said),
    }


def opencode_sessions(database, start, end, strict=False):
    if not database.is_file():
        return []
    connection = None
    try:
        connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        rows = connection.execute(
            "SELECT s.id, s.directory, m.id AS message_id, m.time_created, m.data "
            "FROM message m JOIN session s ON s.id = m.session_id "
            "WHERE m.time_created >= ? AND m.time_created < ? ORDER BY s.id, m.time_created",
            (start_ms, end_ms),
        ).fetchall()
        grouped = {}
        for row in rows:
            entry = grouped.setdefault(row["id"], {
                "agent": "OpenCode", "session_id": row["id"],
                "project": row["directory"] or "Unknown project",
                "tokens": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0},
                "prompts": [], "final_messages": [], "_said": [],
            })
            try:
                message = json.loads(row["data"])
            except json.JSONDecodeError:
                continue
            if message.get("role") == "assistant":
                usage = message.get("tokens") or {}
                cache = usage.get("cache") or {}
                entry["tokens"]["input_tokens"] += max(0, int(usage.get("input") or 0)) + max(0, int(cache.get("read") or 0)) + max(0, int(cache.get("write") or 0))
                entry["tokens"]["output_tokens"] += max(0, int(usage.get("output") or 0))
                entry["tokens"]["cached_input_tokens"] += max(0, int(cache.get("read") or 0))
                model = message.get("modelID") or message.get("model")
                if message.get("providerID") and isinstance(model, str):
                    model = f"{message['providerID']}/{model}"
                if isinstance(model, str) and model:
                    by_model = entry.setdefault("_model_usage", {})
                    request_input = max(0, int(usage.get("input") or 0)) + max(0, int(cache.get("read") or 0)) + max(0, int(cache.get("write") or 0))
                    tier = (model, "long" if request_input > LONG_CONTEXT_INPUT else None)
                    bucket = by_model.setdefault(tier, {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cache_write_tokens": 0})
                    bucket["input_tokens"] += max(0, int(usage.get("input") or 0)) + max(0, int(cache.get("read") or 0)) + max(0, int(cache.get("write") or 0))
                    bucket["output_tokens"] += max(0, int(usage.get("output") or 0))
                    bucket["cached_input_tokens"] += max(0, int(cache.get("read") or 0))
                    bucket["cache_write_tokens"] += max(0, int(cache.get("write") or 0))
            content_rows = connection.execute(
                "SELECT data FROM part WHERE message_id = ? ORDER BY time_created LIMIT 5", (row["message_id"],)
            ).fetchall()
            content = []
            for content_row in content_rows:
                try:
                    part = json.loads(content_row["data"])
                except json.JSONDecodeError:
                    continue
                if part.get("type") == "text":
                    content.append(part.get("text", ""))
            value = excerpt(" ".join(content))
            if message.get("role") == "user":
                entry["_said"].append((epoch_instant(row["time_created"]), value))
            if value and message.get("role") == "user" and len(entry["prompts"]) < 5:
                entry["prompts"].append(value)
            elif value and message.get("role") == "assistant":
                entry["final_messages"].append(value)
        for entry in grouped.values():
            entry["model_usage"] = [{"model": name, **({"context": tier} if tier else {}), "tokens": usage}
                                    for (name, tier), usage in entry.pop("_model_usage", {}).items()]
            entry["final_messages"] = entry["final_messages"][-3:]
            entry["habits"] = habits(entry.pop("_said"))
            if not any(entry["tokens"].values()):
                entry["tokens"] = None
        return list(grouped.values())
    except (OSError, sqlite3.DatabaseError):
        if strict:
            raise
        return []
    finally:
        if connection is not None:
            connection.close()


def devin_sessions(database, start, end):
    """Devin CLI keeps sessions in SQLite; forked chains repeat messages, so dedupe by message ID."""
    if not database.is_file():
        return []
    connection = None
    try:
        connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT s.id, s.working_directory, m.created_at, m.chat_message FROM message_nodes m "
            "JOIN sessions s ON s.id = m.session_id WHERE m.created_at >= ? AND m.created_at < ? ORDER BY m.created_at",
            (int(start.timestamp()), int(end.timestamp()) + 1)).fetchall()
    except (OSError, sqlite3.DatabaseError):
        return []
    finally:
        if connection is not None:
            connection.close()
    grouped, seen = {}, set()
    for session_id, directory, created, raw in rows:
        at = epoch_instant(created)
        try:
            message = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not at or not start <= at < end or not isinstance(message, dict) or message.get("message_id") in seen:
            continue
        seen.add(message.get("message_id"))
        entry = grouped.setdefault(session_id, {"agent": "Devin", "session_id": session_id,
                                                "project": directory or "Unknown project", "tokens": None,
                                                "_models": {}, "prompts": [], "final_messages": [], "_said": [],
                                                "first_activity_at": at.isoformat()})
        metadata = message.get("metadata") or {}
        metrics = metadata.get("metrics") or {}
        if message.get("role") == "user" and metadata.get("is_user_input"):
            value = excerpt(message.get("content"))
            entry["_said"].append((at, value))
            if value and len(entry["prompts"]) < 5:
                entry["prompts"].append(value)
        elif message.get("role") == "assistant" and metrics.get("output_tokens") is not None:
            reads = max(0, int(metrics.get("cache_read_tokens") or 0))
            writes = metrics.get("cache_creation_tokens")
            usage = {"input_tokens": max(0, int(metrics.get("input_tokens") or 0)) + reads + max(0, int(writes or 0)),
                     "output_tokens": max(0, int(metrics["output_tokens"])), "cached_input_tokens": reads}
            entry["tokens"] = {key: (entry["tokens"] or {}).get(key, 0) + value for key, value in usage.items()}
            bucket = entry["_models"].setdefault(metadata.get("generation_model") or "unknown", {"writes_known": True})
            for key, value in usage.items():
                bucket[key] = bucket.get(key, 0) + value
            if writes is None:
                bucket["writes_known"] = False
            else:
                bucket["cache_write_tokens"] = bucket.get("cache_write_tokens", 0) + max(0, int(writes))
            value = excerpt(message.get("content"))
            if value:
                entry["final_messages"].append(value)
    for entry in grouped.values():
        models = entry.pop("_models")
        for usage in models.values():
            if not usage.pop("writes_known"):
                usage.pop("cache_write_tokens", None)
        entry["model_usage"] = [{"model": name, "tokens": usage} for name, usage in models.items()]
        entry["final_messages"] = entry["final_messages"][-3:]
        entry["habits"] = habits(entry.pop("_said"))
    return list(grouped.values())


def factory_session(path, start, end):
    meta = {}
    prompts, finals, said = [], [], []
    first_activity = None
    for item in lines(path):
        if item.get("type") == "session_start":
            meta = item
            continue
        if item.get("type") != "message":
            continue
        at = instant(item.get("timestamp"))
        if not at or not start <= at < end:
            continue
        message = item.get("message") or {}
        role = message.get("role") if isinstance(message, dict) else None
        if role not in ("user", "assistant"):
            continue
        first_activity = min(first_activity, at) if first_activity else at
        value = excerpt(message.get("content"))
        if role == "user":
            said.append((at, value))
        if role == "user" and value and len(prompts) < 5:
            prompts.append(value)
        elif role == "assistant" and value:
            finals.append(value)
    if first_activity is None:
        return None
    return {"agent": "Factory Droid", "session_id": meta.get("id") or path.stem,
            "project": meta.get("cwd") or "Unknown project", "tokens": None,
            "prompts": prompts, "final_messages": finals[-3:], "habits": habits(said),
            "first_activity_at": first_activity.isoformat()}


def kimi_session(path, start, end):
    state_path = path.parents[2] / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    totals = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    prompts, said = [], []
    first_activity = None
    has_usage = False
    for item in lines(path):
        at = epoch_instant(item.get("time"))
        if not at or not start <= at < end:
            continue
        if item.get("type") == "turn.prompt":
            first_activity = min(first_activity, at) if first_activity else at
            value = excerpt(item.get("input"))
            said.append((at, value))
            if value and len(prompts) < 5:
                prompts.append(value)
        elif item.get("type") == "usage.record" and item.get("usageScope") == "turn":
            usage = item.get("usage") or {}
            if not isinstance(usage, dict):
                continue
            first_activity = min(first_activity, at) if first_activity else at
            has_usage = True
            cache_read = max(0, int(usage.get("inputCacheRead") or 0))
            cache_creation = max(0, int(usage.get("inputCacheCreation") or 0))
            totals["input_tokens"] += max(0, int(usage.get("inputOther") or 0)) + cache_read + cache_creation
            totals["output_tokens"] += max(0, int(usage.get("output") or 0))
            totals["cached_input_tokens"] += cache_read
    if first_activity is None:
        return None
    return {"agent": "Kimi Code", "session_id": path.parents[2].name,
            "project": state.get("workDir") or "Unknown project", "tokens": totals if has_usage else None,
            "prompts": prompts, "final_messages": [], "habits": habits(said),
            "first_activity_at": first_activity.isoformat()}


def grok_session(path, start, end):
    session_root = path.parent
    try:
        summary = json.loads((session_root / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary = {}
    turns = {}
    first_activity = None
    try:
        with path.open("rb") as stream:
            for line in stream:
                if b"turn_completed" not in line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                update = ((item.get("params") or {}).get("update") or {})
                at = epoch_instant(item.get("timestamp"))
                if not isinstance(update, dict) or update.get("sessionUpdate") != "turn_completed" or not at or not start <= at < end:
                    continue
                first_activity = min(first_activity, at) if first_activity else at
                usage = update.get("usage")
                if not isinstance(usage, dict):
                    continue
                key = update.get("prompt_id") or ((item.get("params") or {}).get("_meta") or {}).get("eventId")
                if not key:
                    continue
                turns[str(key)] = {
                    "input_tokens": max(0, int(usage.get("inputTokens") or 0)),
                    "output_tokens": max(0, int(usage.get("outputTokens") or 0)),
                    "cached_input_tokens": max(0, int(usage.get("cachedReadTokens") or 0)),
                }
    except OSError:
        return None
    if first_activity is None:
        for item in lines(session_root / "events.jsonl"):
            if item.get("type") != "turn_started":
                continue
            at = instant(item.get("ts"))
            if at and start <= at < end:
                first_activity = min(first_activity, at) if first_activity else at
    if first_activity is None:
        return None
    totals = {key: sum(value[key] for value in turns.values()) for key in
              ("input_tokens", "output_tokens", "cached_input_tokens")}
    info = summary.get("info") or {}
    return {"agent": "Grok", "session_id": session_root.name,
            "project": info.get("cwd") or "Unknown project", "tokens": totals if turns else None,
            "prompts": [], "final_messages": [], "first_activity_at": first_activity.isoformat()}


def inventory_executables(path_value=None):
    """List executable command names on PATH without launching any command."""
    names = set()
    windows = os.name == "nt"
    extensions = {value.lower() for value in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if value}
    for directory in (path_value if path_value is not None else os.environ.get("PATH", "")).split(os.pathsep):
        if not directory:
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if not entry.is_file():
                            continue
                        if windows:  # Windows marks executables by extension, and every file passes X_OK
                            stem, suffix = os.path.splitext(entry.name)
                            if suffix.lower() in extensions:
                                names.add(stem)
                        elif os.access(entry.path, os.X_OK):
                            names.add(entry.name)
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(names)


def discover(codex_home, claude_home, opencode_home, executable_names=None, extra_agent_clis=(),
             factory_home=None, kimi_home=None, grok_home=None, devin_home=None):
    sources = []
    executable_names = set(inventory_executables() if executable_names is None else executable_names)
    factory_home = factory_home or Path.home() / ".factory"
    kimi_home = kimi_home or Path.home() / ".kimi-code"
    grok_home = grok_home or Path.home() / ".grok"
    codex_files = sorted((codex_home / "sessions").glob("**/*.jsonl")) + sorted((codex_home / "archived_sessions").glob("*.jsonl"))
    claude_files = sorted((claude_home / "projects").glob("**/*.jsonl"))
    factory_files = sorted((factory_home / "sessions").glob("*/*.jsonl"))
    kimi_files = sorted((kimi_home / "sessions").glob("**/agents/main/wire.jsonl"))
    grok_files = sorted((grok_home / "sessions").glob("**/updates.jsonl"))
    known_clis = {
        "Codex": "codex", "Claude Code": "claude", "OpenCode": "opencode",
        "Cursor": ("cursor-agent", "cursor"), "Gemini CLI": "gemini", "Devin": "devin",
        "Aider": "aider", "Goose": "goose", "Amp": "amp",
        "GitHub Copilot CLI": "copilot", "Factory Droid": "droid",
        "Hermes": "hermes", "Kimi Code": "kimi", "Grok": ("grok", "agent"),
    }

    def source(agent, files, history_root=None, supported=False):
        commands = known_clis[agent]
        commands = commands if isinstance(commands, tuple) else (commands,)
        command = None
        for candidate in commands:
            if candidate not in executable_names:
                continue
            if agent == "Grok" and candidate == "agent":
                resolved = Path(shutil.which(candidate) or "").resolve()
                if ".grok" not in resolved.parts and "grok" not in resolved.name.lower():
                    continue
            command = candidate
            break
        cli_available = command is not None
        history_present = bool(files) or bool(history_root and history_root.exists())
        if supported and files:
            status = "parsed"
        elif cli_available or history_present:
            status = "detected, no readable history" if supported else "detected, unparsed"
        else:
            status = "not found"
        return {"agent": agent, "status": status, "files": files,
                "cli": command if cli_available else None, "local_history": history_present,
                "activity_in_window": None}

    sources.append(source("Codex", len(codex_files), supported=True))
    sources.append(source("Claude Code", len(claude_files), supported=True))
    opencode_database = opencode_home / "opencode.db"
    sources.append(source("OpenCode", int(opencode_database.is_file()), supported=True))
    sources.append(source("Factory Droid", len(factory_files), supported=True))
    sources.append(source("Kimi Code", len(kimi_files), supported=True))
    sources.append(source("Grok", len(grok_files), supported=True))
    devin_database = (devin_home or Path.home() / ".local/share/devin") / "cli/sessions.db"
    sources.append(source("Devin", int(devin_database.is_file()), supported=True))
    candidates = {
        "Cursor": Path.home() / ".cursor",
        "Gemini CLI": Path.home() / ".gemini",
        "Aider": Path.home() / ".aider",
        "Goose": Path.home() / ".config/goose",
        "Amp": Path.home() / ".local/share/amp",
        "GitHub Copilot CLI": Path.home() / ".copilot",
        "Hermes": Path.home() / ".hermes",
    }
    for agent, root in candidates.items():
        entry = source(agent, 0, history_root=root)
        if entry["status"] != "not found":
            sources.append(entry)
    registered_commands = {
        command for value in known_clis.values()
        for command in (value if isinstance(value, tuple) else (value,))
    }
    for command in sorted(set(extra_agent_clis) - registered_commands):
        if command in executable_names:
            sources.append({"agent": f"Additional CLI: {command}", "status": "detected, unparsed",
                            "files": 0, "cli": command, "local_history": False,
                            "activity_in_window": None})
    return codex_files, claude_files, sources


def modified_in_window(path, start):
    try:
        return path.stat().st_mtime >= start.timestamp()
    except OSError:
        return False


def read_sessions(args, codex_files, claude_files, start, end, sources=None):
    """Parse every supported history for one window; `sources` records read errors."""
    sessions = []
    for path in codex_files:
        if not modified_in_window(path, start):
            continue
        value = codex_session(path, start, end)
        if value:
            sessions.append(value)
    for path in claude_files:
        if not modified_in_window(path, start):
            continue
        value = claude_session(path, start, end)
        if value:
            sessions.append(value)
    try:
        sessions.extend(opencode_sessions(args.opencode_home / "opencode.db", start, end, strict=True))
    except (OSError, sqlite3.DatabaseError):
        if sources is not None:
            source = next(item for item in sources if item["agent"] == "OpenCode")
            source["status"] = "detected, unparsed"
            source["read_error"] = "OpenCode database format could not be read"
    sessions.extend(devin_sessions(args.devin_home / "cli/sessions.db", start, end))
    for root, pattern, reader in (
        (args.factory_home, "sessions/*/*.jsonl", factory_session),
        (args.kimi_home, "sessions/**/agents/main/wire.jsonl", kimi_session),
        (args.grok_home, "sessions/**/updates.jsonl", grok_session),
    ):
        for path in sorted(root.glob(pattern)):
            if not modified_in_window(path, start):
                continue
            value = reader(path, start, end)
            if value:
                sessions.append(value)
    unique = {}
    for session in sessions:
        key = (session["agent"], session["session_id"])
        previous = unique.get(key)
        count = sum((session.get("tokens") or {}).values())
        if previous is None or count > sum((previous.get("tokens") or {}).values()):
            unique[key] = session
    return list(unique.values())


def previous_summary(sessions, start, end):
    """Totals only for the preceding window: enough for a trend, no transcript text."""
    measured = [session["tokens"] for session in sessions if isinstance(session.get("tokens"), dict)]
    return {"window_start": start.isoformat(), "window_end": end.isoformat(), "agents": list(AUTO_AGENTS),
            "sessions": len(sessions),
            "total_tokens": sum(int(tokens.get("input_tokens") or 0) + int(tokens.get("output_tokens") or 0)
                                for tokens in measured) if measured else None}


def window_end(now, whole_days, through_now=False):
    """End windows on a fixed boundary so every run that day (or hour) gives the same card."""
    if through_now:
        return now.astimezone(timezone.utc)
    boundary = now.replace(hour=0, minute=0, second=0, microsecond=0) if whole_days else now.replace(minute=0, second=0, microsecond=0)
    return boundary.astimezone(timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument("--hours", type=float)
    window.add_argument("--days", type=float)
    parser.add_argument("--output", type=Path, default=private_dir() / "activity.json")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--claude-home", type=Path, default=Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")))
    parser.add_argument("--opencode-home", type=Path, default=Path.home() / ".local/share/opencode")
    parser.add_argument("--factory-home", type=Path, default=Path.home() / ".factory")
    parser.add_argument("--kimi-home", type=Path, default=Path.home() / ".kimi-code")
    parser.add_argument("--grok-home", type=Path, default=Path.home() / ".grok")
    parser.add_argument("--devin-home", type=Path, default=Path.home() / ".local/share/devin")
    parser.add_argument("--through-now", action="store_true",
                        help="End the window now instead of at the last midnight (--days) or top of the hour (--hours)")
    parser.add_argument("--agent-cli", action="append", default=[], metavar="COMMAND",
                        help="Register an additional coding-agent command found in the PATH inventory")
    args = parser.parse_args()
    duration = timedelta(hours=args.hours) if args.hours is not None else timedelta(days=args.days)
    if duration <= timedelta(0):
        parser.error("Time window must be positive")
    end = window_end(datetime.now().astimezone(), args.days is not None, args.through_now)
    start = end - duration
    executable_names = inventory_executables()
    missing_clis = set(args.agent_cli) - set(executable_names)
    if missing_clis:
        parser.error("Agent CLI not found on PATH: " + ", ".join(sorted(missing_clis)))
    codex_files, claude_files, sources = discover(
        args.codex_home, args.claude_home, args.opencode_home, executable_names, args.agent_cli,
        args.factory_home, args.kimi_home, args.grok_home, args.devin_home)
    sessions = read_sessions(args, codex_files, claude_files, start, end, sources)
    previous = read_sessions(args, codex_files, claude_files, start - duration, start)
    active_agents = {session["agent"] for session in sessions}
    for source in sources:
        if source["agent"] in active_agents:
            source["activity_in_window"] = True
    report = {"window_start": start.isoformat(), "window_end": end.isoformat(),
              "cli_inventory": executable_names, "sources": sources, "sessions": sessions,
              "previous_window": previous_summary(previous, start - duration, start)}
    ensure_parent(args.output)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(f"Collected {len(sessions)} sessions from {sum(source.get('files', 0) for source in sources)} local history files into {args.output}")
    print(f"Inventoried {len(executable_names)} executable command names on PATH; review cli_inventory for additional coding agents.")
    print("Contains private transcript excerpts. Review before sharing.")


if __name__ == "__main__":
    main()
