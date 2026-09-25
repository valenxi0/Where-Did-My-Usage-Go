import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "skills/where-did-my-usage-go/scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


collect = module("collect")
render = module("render")
draft = module("draft")
pricing = module("pricing")


class ReportTests(unittest.TestCase):
    def test_codex_uses_cumulative_deltas_once_and_filters_time(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        def token(at, input_tokens, output_tokens):
            return {"timestamp": at, "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": input_tokens, "output_tokens": output_tokens,
                    "cached_input_tokens": 0}}}}
        rows = [
            {"type": "session_meta", "payload": {"id": "one", "cwd": "/test"}},
            token("2026-01-01T23:59:00Z", 100, 20),
            token("2026-01-02T00:01:00Z", 110, 25),
            token("2026-01-02T00:02:00Z", 110, 25),
            token("2026-01-02T00:03:00Z", 140, 35),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows))
            result = collect.codex_session(path, start, end)
        self.assertEqual(result["tokens"]["input_tokens"], 40)
        self.assertEqual(result["tokens"]["output_tokens"], 15)

    def test_codex_attributes_in_window_deltas_to_recorded_model(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [
                {"type": "turn_context", "payload": {"model": "model-one"}},
                {"timestamp": "2026-01-02T12:00:00Z", "type": "event_msg", "payload": {
                    "type": "token_count", "info": {"total_token_usage": {
                        "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30}}}},
            ]))
            result = collect.codex_session(path, start, start + timedelta(days=1))
        self.assertEqual(result["model_usage"][0]["model"], "model-one")
        self.assertEqual(result["model_usage"][0]["tokens"], result["tokens"])

    def test_codex_preserves_recorded_cache_writes_for_pricing(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [
                {"type": "turn_context", "payload": {"model": "model-one"}},
                {"timestamp": "2026-01-02T12:00:00Z", "type": "event_msg", "payload": {
                    "type": "token_count", "info": {"total_token_usage": {
                        "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30,
                        "cache_write_input_tokens": 10}}}},
            ]))
            result = collect.codex_session(path, start, start + timedelta(days=1))
        self.assertEqual(result["tokens"], {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30})
        self.assertEqual(result["model_usage"][0]["tokens"]["cache_write_tokens"], 10)

    def test_claude_deduplicates_streamed_response(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        def response(output):
            return {"type": "assistant", "timestamp": "2026-01-02T00:01:00Z", "message": {
                "id": "message-one", "model": "model-one", "usage": {"input_tokens": 10, "output_tokens": output,
                "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3,
                "cache_creation": {"ephemeral_5m_input_tokens": 2, "ephemeral_1h_input_tokens": 0}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [response(2), response(5)]))
            result = collect.claude_session(path, start, end)
        self.assertEqual(result["tokens"], {"input_tokens": 15, "output_tokens": 5, "cached_input_tokens": 3})
        self.assertEqual(result["model_usage"], [{"model": "model-one", "tokens": {
            "input_tokens": 15, "output_tokens": 5, "cached_input_tokens": 3,
            "cache_write_tokens": 2, "cache_write_1h_tokens": 0}}])

    def test_api_equivalent_prices_cache_types_and_marks_partial_coverage(self):
        activity = {"window_start": "2026-01-02T00:00:00+00:00", "window_end": "2026-01-03T00:00:00+00:00",
                    "sessions": [
                        {"agent": "Claude Code", "project": "/repo", "tokens": {
                            "input_tokens": 1_000_000, "output_tokens": 100_000, "cached_input_tokens": 300_000},
                         "model_usage": [{"model": "exact-model", "tokens": {
                             "input_tokens": 1_000_000, "output_tokens": 100_000,
                             "cached_input_tokens": 300_000, "cache_write_tokens": 100_000,
                             "cache_write_1h_tokens": 100_000}}]},
                        {"agent": "Factory Droid", "project": "/repo", "tokens": None},
                    ]}
        pricing = {"as_of": "2026-01-03", "models": [{"model": "exact-model",
                    "input_per_million": 2, "cached_input_per_million": 0.2,
                    "cache_write_per_million": 2.5, "cache_write_1h_per_million": 4,
                    "output_per_million": 10,
                    "source_url": "https://example.com/official"}]}
        share = draft.draft(activity, pricing=pricing)
        self.assertEqual(share["estimated_api_cost"]["usd"], 2.71)
        self.assertTrue(share["estimated_api_cost"]["partial"])
        html = render.render(share, "named")
        self.assertIn("Est. API equivalent $2.71 · 1 session unmeasured", html)
        self.assertNotIn("Agent operator", html)
        self.assertNotIn("Player card / 001", html)
        self.assertIsNone(draft.draft(activity)["estimated_api_cost"])

    def test_unlogged_cache_writes_are_priced_as_input_and_flagged_as_a_floor(self):
        activity = {"window_start": "2026-01-02T00:00:00+00:00", "window_end": "2026-01-03T00:00:00+00:00",
                    "sessions": [{"agent": "Codex", "project": "/repo", "tokens": {
                        "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30},
                        "model_usage": [{"model": "model-one", "tokens": {
                            "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30}}]}]}
        pricing = {"as_of": "2026-01-03", "models": [{"model": "model-one",
                    "input_per_million": 20000, "cached_input_per_million": 2000,
                    "cache_write_per_million": 25000, "output_per_million": 100000,
                    "source_url": "https://example.com/pricing"}]}
        result = draft.draft(activity, pricing=pricing)["estimated_api_cost"]
        self.assertEqual(result["usd"], 3.46)
        self.assertTrue(result["floor"])
        self.assertTrue(any("minimum" in note for note in draft.draft(activity, pricing=pricing)["notes"]))

    def test_prices_match_by_model_across_agents_and_logged_name_variants(self):
        self.assertEqual(pricing.model_key("anthropic/claude-opus-5-5-20260301"), "claude-opus-5-5")
        self.assertEqual(pricing.model_key("claude-opus-5-5-medium"), "claude-opus-5-5")
        self.assertEqual(pricing.model_key("claude-opus-5-5[1m]"), "claude-opus-5-5")
        table = pricing.load(pricing.BUNDLED)
        sessions = [{"agent": "Devin", "tokens": {"input_tokens": 1_000_000, "output_tokens": 0},
                     "model_usage": [{"model": "claude-opus-5-5-medium", "tokens": {
                         "input_tokens": 1_000_000, "output_tokens": 0, "cached_input_tokens": 0,
                         "cache_write_tokens": 0, "cache_write_1h_tokens": 0}}]},
                    {"agent": "Devin", "tokens": {"input_tokens": 500, "output_tokens": 0},
                     "model_usage": [{"model": "swe-2-high", "tokens": {"input_tokens": 500, "output_tokens": 0}}]}]
        result = pricing.estimate(sessions, table)
        self.assertEqual(result["usd"], 4.0)
        self.assertEqual(result["unpriced"], [{"agent": "Devin", "model": "swe-2-high", "tokens": 500}])

    def test_long_context_requests_use_long_context_rates(self):
        table = pricing.load(pricing.BUNDLED)
        usage = {"input_tokens": 1_000_000, "output_tokens": 0, "cached_input_tokens": 0, "cache_write_tokens": 0}
        session = {"agent": "Codex", "tokens": usage, "model_usage": [{"model": "gpt-6-sol", "context": "long", "tokens": usage}]}
        self.assertEqual(pricing.estimate([session], table)["usd"], 4.0)
        session["model_usage"][0].pop("context")
        self.assertEqual(pricing.estimate([session], table)["usd"], 2.0)

    def test_bundled_price_table_is_valid_and_sourced(self):
        raw = json.loads(pricing.BUNDLED.read_text())
        self.assertEqual(len(pricing.load(pricing.BUNDLED)["models"]), len(raw["models"]))
        self.assertTrue(all(entry["source_url"].startswith("https://") for entry in raw["models"]))

    def test_committed_demo_matches_a_rebuild_with_bundled_prices(self):
        examples = ROOT.parents[2] / "tests/fixtures"
        activity = json.loads((examples / "demo-activity.json").read_text())
        committed = json.loads((examples / "demo.json").read_text())
        spec = importlib.util.spec_from_file_location("build_demo", examples / "build_demo.py")
        build_demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_demo)
        rebuilt = draft.draft(activity, "Sample Dev", "Player One", "sampledev", pricing.load(pricing.BUNDLED),
                              build_demo.DEMO_PLANS)
        self.assertEqual(committed["total_tokens"], rebuilt["total_tokens"])
        self.assertEqual(committed["estimated_api_cost"], rebuilt["estimated_api_cost"])
        self.assertEqual(committed["subscription"], rebuilt["subscription"])

    def test_factory_counts_activity_without_inventing_tokens(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "factory.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [
                {"type": "session_start", "id": "factory-one", "cwd": "/repo"},
                {"type": "message", "timestamp": "2026-01-01T23:00:00Z",
                 "message": {"role": "user", "content": [{"type": "text", "text": "Old request"}]}},
                {"type": "message", "timestamp": "2026-01-02T12:00:00Z",
                 "message": {"role": "user", "content": [{"type": "text", "text": "Build a widget"}]}},
            ]))
            session = collect.factory_session(path, start, start + timedelta(days=1))
        self.assertEqual(session["agent"], "Factory Droid")
        self.assertEqual(session["tokens"], None)
        self.assertEqual(session["prompts"], ["Build a widget"])

    def test_kimi_counts_in_window_turn_usage_once(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "session-one"
            path = root / "agents/main/wire.jsonl"
            path.parent.mkdir(parents=True)
            (root / "state.json").write_text(json.dumps({"workDir": "/repo"}))
            at = int((start + timedelta(hours=1)).timestamp() * 1000)
            old = int((start - timedelta(hours=1)).timestamp() * 1000)
            path.write_text("\n".join(json.dumps(row) for row in [
                {"type": "usage.record", "time": old, "usageScope": "turn", "usage": {"inputOther": 1000}},
                {"type": "turn.prompt", "time": at, "input": "Build a widget"},
                {"type": "usage.record", "time": at, "usageScope": "turn", "usage":
                 {"inputOther": 20, "inputCacheRead": 30, "inputCacheCreation": 5, "output": 10}},
            ]))
            session = collect.kimi_session(path, start, start + timedelta(days=1))
        self.assertEqual(session["tokens"], {"input_tokens": 55, "output_tokens": 10, "cached_input_tokens": 30})
        self.assertEqual(session["project"], "/repo")

    def test_grok_deduplicates_completed_turns_in_window(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "session-one"
            root.mkdir()
            (root / "summary.json").write_text(json.dumps({"info": {"cwd": "/repo"}}))
            path = root / "updates.jsonl"
            at = int((start + timedelta(hours=1)).timestamp())
            old = int((start - timedelta(hours=1)).timestamp())
            def turn(timestamp, prompt_id, input_tokens):
                return {"timestamp": timestamp, "params": {"update": {"sessionUpdate": "turn_completed",
                    "prompt_id": prompt_id, "usage": {"inputTokens": input_tokens, "outputTokens": 4,
                    "cachedReadTokens": 3}}}}
            path.write_text("\n".join(json.dumps(row) for row in [turn(old, "old", 100), turn(at, "one", 20), turn(at, "one", 20)]))
            session = collect.grok_session(path, start, start + timedelta(days=1))
        self.assertEqual(session["tokens"], {"input_tokens": 20, "output_tokens": 4, "cached_input_tokens": 3})
        self.assertEqual(session["project"], "/repo")

    def test_anonymous_card_does_not_copy_named_content_and_escapes_html(self):
        data = {"title": "Where did my usage go?", "window": "Past 7 days",
                "subtitle": "Secret subtitle", "notes": ["Secret note"],
                "display_name": "@secret-person", "anonymous_display_name": "Player One", "x_handle": "secret_person",
                "roast": "@secret-person spent the tokens", "anonymous_roast": "Player One found the token bonfire.",
                "highlight": "Secret achievement", "anonymous_highlight": "Built a feature.",
                "agents": [{"name": "Codex", "sessions": 1, "tokens": 100}],
                "projects": [{"name": "Secret App", "summary": "<script>alert('secret')</script>",
                              "anonymous_name": "Project 1", "anonymous_summary": "Built a feature.", "sessions": 1}]}
        anonymous = render.render(data, "anonymous")
        named = render.render(data, "named")
        self.assertNotIn("Secret App", anonymous)
        self.assertNotIn("Secret subtitle", anonymous)
        self.assertNotIn("Secret note", anonymous)
        self.assertNotIn("@secret-person", anonymous)
        self.assertNotIn("secret_person", anonymous)
        self.assertNotIn("Secret achievement", anonymous)
        self.assertNotIn("alert", anonymous)
        self.assertIn("Project 1", anonymous)
        self.assertIn("Player One found the token bonfire.", anonymous)
        self.assertIn('href="https://x.com/valenxi">Created by @valenxi on X</a>', anonymous)
        self.assertIn("&lt;script&gt;", named)
        self.assertIn("https://x.com/secret_person", named)
        self.assertNotIn('class="avatar"', named)

        private_projects = render.render(data, "private-projects")
        self.assertIn("@secret-person spent the tokens", private_projects)
        self.assertIn("https://x.com/secret_person", private_projects)
        self.assertIn("Project 1", private_projects)
        self.assertNotIn("Secret App", private_projects)
        self.assertNotIn("Secret achievement", private_projects)
        self.assertNotIn("Secret note", private_projects)

    def test_draft_shows_only_active_agents_and_marks_incomplete_coverage_without_names(self):
        activity = {
            "window_start": "2026-01-02T00:00:00+00:00", "window_end": "2026-01-03T00:00:00+00:00",
            "sources": [{"agent": "Cursor", "status": "detected, unparsed"}],
            "sessions": [
                {"agent": "Codex", "project": "/repo/alpha", "tokens": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 80}},
                {"agent": "Codex", "project": "/repo/alpha", "tokens": None},
                {"agent": "Claude Code", "project": "/repo/beta", "tokens": {"input_tokens": 30, "output_tokens": 10, "cached_input_tokens": 20}},
            ],
        }
        result = draft.draft(activity)
        self.assertEqual(result["projects"][0]["tokens"], 120)
        self.assertEqual(result["agents"][0]["tokens"], 120)
        self.assertEqual(result["total_tokens"], 160)
        self.assertEqual(result["cached_input_tokens"], 100)
        self.assertTrue(any("partial" in note for note in result["notes"]))
        self.assertEqual([agent["name"] for agent in result["agents"]], ["Codex", "Claude Code"])
        self.assertNotIn("Cursor", json.dumps(result))
        self.assertTrue(any("Coverage incomplete" in note for note in result["notes"]))

    def test_confirmed_inactive_agent_does_not_appear_or_add_coverage_note(self):
        activity = {"window_start": "2026-01-02T00:00:00+00:00",
                    "window_end": "2026-01-03T00:00:00+00:00",
                    "sources": [{"agent": "Unused Agent", "status": "detected, unparsed", "activity_in_window": False}],
                    "sessions": [{"agent": "Codex", "project": "/repo/alpha", "tokens": {"input_tokens": 50, "output_tokens": 10}}]}
        share = draft.draft(activity)
        self.assertEqual([agent["name"] for agent in share["agents"]], ["Codex"])
        self.assertNotIn("Unused Agent", render.render(share, "named"))
        self.assertFalse(any("Coverage incomplete" in note for note in share["notes"]))

    def test_window_label_is_short_and_uses_plain_hyphens(self):
        end = datetime(2026, 9, 24, 15, 0)
        self.assertEqual(draft.window_label(end - timedelta(days=7), end, 168), "Last 7 days · Sep 17-24, 2026")
        self.assertEqual(draft.window_label(end - timedelta(hours=5), end, 5), "Last 5 hours · Sep 24, 2026")
        self.assertEqual(draft.window_label(end - timedelta(days=30), end, 720), "Last 30 days · Aug 25 - Sep 24, 2026")
        midnight = datetime(2026, 9, 24)
        self.assertEqual(draft.window_label(midnight - timedelta(days=7), midnight, 168), "Last 7 days · Sep 17-23, 2026")

    def test_discovery_includes_nested_claude_subagent_transcripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / ".claude/projects/-repo/session.jsonl"
            subagent = root / ".claude/projects/-repo/session/subagents/agent-one.jsonl"
            for path in (main, subagent):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            _, claude_files, _ = collect.discover(root / ".codex", root / ".claude", root / "opencode", [],
                                                  factory_home=root, kimi_home=root, grok_home=root)
        self.assertEqual(sorted(path.name for path in claude_files), ["agent-one.jsonl", "session.jsonl"])

    def test_habits_count_human_prompts_only(self):
        at = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
        said = [(at, "continue"), (at, "it's still broken, please look"), (at, "<command-name>/clear</command-name>"),
                (at, "[Request interrupted by user]"), (None, "yes"), (at, "")]
        counts = collect.habits(said)
        self.assertEqual({key: counts[key] for key in ("prompts", "nudges", "stuck", "polite")},
                         {"prompts": 2, "nudges": 1, "stuck": 1, "polite": 1})

    def test_roasts_prefer_habits_over_statistics(self):
        facts = {"limit": None, "plan_multiple": None, "catchphrase": None, "peak_hour": None, "top_model": None,
                 "top_project_share": None, "project_count": 1, "total": 2_000_000_000, "span": "week", "tier": "legendary", "sessions": 60, "agent_count": 4,
                 "api_usd": 900.0, "change": 6.0, "cache_share": 98, "top_agent": "Codex", "top_agent_share": 69,
                 "per_hour": 10_000_000, "habits": {"prompts": 40, "nudges": 0, "stuck": 12, "polite": 0, "late_night": 0}}
        lines = draft.roast_lines(facts)
        self.assertIn("still broken", lines[0])
        self.assertIn("Brevity", lines[1])
        self.assertTrue(lines[-1].startswith("More than double"))
        self.assertFalse(any(line.startswith(("Sample", "Player")) or "!" in line for line in lines))

    def test_dotted_and_dashed_model_ids_match(self):
        self.assertEqual(pricing.model_key("z-ai/glm-5.3-flash"), pricing.model_key("glm-5-3-flash-high"))

    def test_redraft_keeps_the_previous_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "activity.json").write_text(json.dumps({
                "window_start": "2026-01-02T00:00:00+00:00", "window_end": "2026-01-03T00:00:00+00:00", "sessions": []}))
            (root / "share.json").write_text('{"roast": "hand edited"}')
            with patch("sys.argv", ["draft.py", "--input", str(root / "activity.json"), "--output",
                                    str(root / "share.json"), "--no-pricing"]):
                draft.main()
            backups = list(root.glob("share-*.json"))
        self.assertEqual(len(backups), 1)

    def test_devin_reader_dedupes_forked_messages_and_keeps_prompts(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        at = int((start + timedelta(hours=1)).timestamp())
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE sessions (id TEXT, working_directory TEXT)")
            connection.execute("CREATE TABLE message_nodes (session_id TEXT, created_at INTEGER, chat_message TEXT)")
            connection.execute("INSERT INTO sessions VALUES ('one', '/repo/app')")
            reply = {"message_id": "m2", "role": "assistant", "content": "Done.", "metadata": {
                "generation_model": "claude-opus-5-5-medium",
                "metrics": {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 90, "cache_creation_tokens": None}}}
            prompt = {"message_id": "m1", "role": "user", "content": "still broken", "metadata": {"is_user_input": True}}
            for message in (prompt, reply, reply):
                connection.execute("INSERT INTO message_nodes VALUES ('one', ?, ?)", (at, json.dumps(message)))
            connection.commit()
            connection.close()
            [session] = collect.devin_sessions(database, start, start + timedelta(days=1))
        self.assertEqual(session["tokens"], {"input_tokens": 100, "output_tokens": 5, "cached_input_tokens": 90})
        self.assertNotIn("cache_write_tokens", session["model_usage"][0]["tokens"])
        self.assertEqual(session["habits"]["stuck"], 1)

    def test_plan_limit_sums_usage_across_resets(self):
        sessions = [{"agent": "Codex", "plan_limits": {"plan": "pro", "cycles": [
                        {"window_minutes": 10080, "reset_hour": 1, "low": 40.0, "high": 100.0}]}},
                    {"agent": "Codex", "plan_limits": {"plan": "pro", "cycles": [
                        {"window_minutes": 10080, "reset_hour": 1, "low": 30.0, "high": 60.0},
                        {"window_minutes": 10080, "reset_hour": 2, "low": 0.0, "high": 25.0},
                        {"window_minutes": 300, "reset_hour": 9, "low": 0.0, "high": 90.0}]}}]
        limit = draft.plan_limit_used(sessions)
        self.assertEqual((limit["window_minutes"], limit["used_percent"], limit["cycles"]), (10080, 95.0, 2))

    def test_plan_cost_is_prorated_and_parsed_strictly(self):
        prefs = module("prefs")
        self.assertEqual(prefs.parse_plan("Claude Max=$100"), {"name": "Claude Max", "usd_per_month": 100.0})
        with self.assertRaises(ValueError):
            prefs.parse_plan("Claude Max")
        self.assertEqual(draft.plan_cost([{"name": "A", "usd_per_month": 30.44}], 24)["prorated_usd"], 1.0)

    def test_export_scan_flags_secrets_but_not_ordinary_card_text(self):
        scan = module("scan")
        self.assertEqual(scan.findings({"roast": "98% cache reads. @valenxi on X, 1.8B tokens, $928"}), [])
        kinds = {kind for kind, _ in scan.findings(["key sk-ant-abcdefghijklmnopqrstuv", "me@example.com", "/Users/sample/app"])}
        self.assertEqual(kinds, {"API key or token", "email address", "home folder path"})

    def test_project_kind_gives_generic_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "web").mkdir()
            (root / "web/package.json").write_text('{"dependencies": {"next": "16"}}')
            (root / "mac/Island.xcodeproj").mkdir(parents=True)
            (root / "empty").mkdir()
            self.assertEqual(draft.project_kind(root / "web"), "Next.js app")
            self.assertEqual(draft.project_kind(root / "mac"), "Swift app")
            self.assertIsNone(draft.project_kind(root / "empty"))
            self.assertIsNone(draft.project_kind(root / "missing"))

    def test_busiest_names_a_weekday_only_for_multi_day_windows(self):
        card = module("card")
        hours, days = [0] * 24, [0, 3, 9, 0, 0, 0, 0]
        hours[22] = 12
        base = {"hours": hours, "weekdays": days}
        self.assertEqual(card.busiest({**base, "window_hours": 168}), "Wednesdays around 10pm")
        self.assertEqual(card.busiest({**base, "window_hours": 24}), "around 10pm")
        self.assertIsNone(card.busiest({"hours": None, "weekdays": None, "window_hours": 168}))

    def test_windows_end_on_a_fixed_boundary(self):
        now = datetime(2026, 9, 24, 19, 42, 10, tzinfo=timezone(timedelta(hours=-7)))
        self.assertEqual(collect.window_end(now, True), datetime(2026, 9, 24, 7, tzinfo=timezone.utc))
        self.assertEqual(collect.window_end(now, False), datetime(2026, 9, 25, 2, tzinfo=timezone.utc))
        self.assertEqual(collect.window_end(now, True, through_now=True), now.astimezone(timezone.utc))

    def test_only_stock_phrases_are_stored_verbatim(self):
        at = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
        counts = collect.habits([(at, "Continue."), (at, "continue"), (at, "rename Acme to Nimbus"), (at, "try again")])
        self.assertEqual(counts["phrases"], {"continue": 2, "try again": 1})

    def test_roast_tier_uses_window_rate_and_handles_unknown(self):
        week = 24 * 7
        self.assertEqual(draft.roast_tier(None, 24), "unknown")
        self.assertEqual(draft.roast_tier(10_000_000, week), "warmup")
        self.assertEqual(draft.roast_tier(100_000_000, week), "regular")
        self.assertEqual(draft.roast_tier(1_600_000_000, week), "unhinged")
        self.assertEqual(draft.roast_tier(1_000_000_000, week), "heavy")
        self.assertEqual(draft.roast_tier(6_000_000_000, week), "legendary")
        # A one-hour burst is averaged over a full day, so it cannot reach the top tier.
        self.assertEqual(draft.roast_tier(40_000_000, 1), "heavy")

    def test_banked_reset_requires_redemption_evidence_in_window(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        activity = {"reset_events": [
            {"provider": "Codex", "kind": "banked", "status": "redeemed",
             "occurred_at": "2026-01-02T12:00:00Z", "evidence_type": "redemption_receipt",
             "evidence": "Successful redemption receipt", "id": "one"},
            {"provider": "Codex", "kind": "banked", "status": "redeemed",
             "occurred_at": "2026-01-02T12:00:00Z", "evidence_type": "redemption_receipt",
             "evidence": "Successful redemption receipt", "id": "one"},
            {"provider": "Codex", "kind": "banked", "status": "redeemed",
             "occurred_at": "2026-01-02T13:00:00Z", "evidence_type": "user_report",
             "evidence": "I think I used one"},
            {"provider": "Codex", "kind": "banked", "status": "redeemed",
             "occurred_at": "2026-01-01T12:00:00Z", "evidence_type": "account_history",
             "evidence": "Outside selected window"},
        ]}
        self.assertEqual(draft.verified_banked_resets(activity, start, end), 1)

    def test_discovery_marks_cli_only_agents_as_unparsed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, sources = collect.discover(root / "codex", root / "claude", root / "opencode", ["aider"])
        aider = next(source for source in sources if source["agent"] == "Aider")
        self.assertEqual(aider["status"], "detected, unparsed")
        self.assertEqual(aider["cli"], "aider")
        self.assertFalse(aider["local_history"])

    def test_inventory_and_additional_agent_do_not_depend_on_fixed_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = "future-coding-agent" + (".cmd" if os.name == "nt" else "")
            (root / command).write_text("#!/bin/sh\n")
            (root / command).chmod(0o755)
            (root / "ordinary-file").write_text("not executable")
            names = collect.inventory_executables(str(root) + os.pathsep + str(root / "missing"))
            _, _, sources = collect.discover(root / "codex", root / "claude", root / "opencode", names, ["future-coding-agent"])
        self.assertIn("future-coding-agent", names)
        self.assertNotIn("ordinary-file", names)
        self.assertTrue(any(source["cli"] == "future-coding-agent" and source["status"] == "detected, unparsed" for source in sources))

    def test_generic_agent_command_is_identified_by_grok_install_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent_path = root / ".grok/bin/agent"
            agent_path.parent.mkdir(parents=True)
            agent_path.write_text("#!/bin/sh\n")
            with patch.object(Path, "home", return_value=root), patch.object(collect.shutil, "which", return_value=str(agent_path)):
                _, _, sources = collect.discover(root / "codex", root / "claude", root / "opencode", ["agent"])
        grok = next(source for source in sources if source["agent"] == "Grok")
        self.assertEqual(grok["cli"], "agent")
        self.assertEqual(grok["status"], "detected, no readable history")

    def test_reset_count_appears_only_when_verified(self):
        data = {"agents": [], "projects": [], "banked_resets_used": 1}
        self.assertIn("1 Codex banked reset used", render.render(data, "anonymous"))
        data["banked_resets_used"] = None
        self.assertNotIn("banked reset used", render.render(data, "anonymous"))

    def test_opencode_includes_cache_in_input_once(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opencode.db"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE session (id TEXT, directory TEXT);
                CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
                CREATE TABLE part (message_id TEXT, time_created INTEGER, data TEXT);
            """)
            connection.execute("INSERT INTO session VALUES (?, ?)", ("session-one", "/repo/demo"))
            at = int((start + timedelta(hours=1)).timestamp() * 1000)
            message = {"role": "assistant", "tokens": {"input": 50, "output": 10, "cache": {"read": 20, "write": 5}}}
            connection.execute("INSERT INTO message VALUES (?, ?, ?, ?)", ("message-one", "session-one", at, json.dumps(message)))
            connection.commit()
            connection.close()
            results = collect.opencode_sessions(path, start, end)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tokens"], {"input_tokens": 75, "output_tokens": 10, "cached_input_tokens": 20})

    def test_opencode_reports_unreadable_database_to_collector(self):
        start = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opencode.db"
            path.write_text("not a sqlite database")
            with self.assertRaises(sqlite3.DatabaseError):
                collect.opencode_sessions(path, start, start + timedelta(days=1), strict=True)


if __name__ == "__main__":
    unittest.main()
