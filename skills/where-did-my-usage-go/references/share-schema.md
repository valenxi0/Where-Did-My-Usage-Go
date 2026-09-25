# Share report schema

The renderer accepts a JSON object with these fields:

```json
{
  "title": "Where did my usage go?",
  "window": "Last 7 days · Sep 17-24, 2026",
  "window_hours": 168,
  "display_name": "Sample Dev",
  "x_handle": "sampledev",
  "anonymous_display_name": "Player One",
  "total_tokens": 1234567,
  "cached_input_tokens": 900000,
  "estimated_api_cost": null,
  "banked_resets_used": 1,
  "roast_tier": "heavy",
  "roast": "97% of it was cache reads. The model mostly reread your repo.",
  "anonymous_roast": "97% of it was cache reads. The model mostly reread your repo.",
  "comparison": {"previous_tokens": 520000, "current_tokens": 1234567},
  "highlight": "Built a new settings screen and fixed login.",
  "anonymous_highlight": "Built a settings screen and fixed an account flow.",
  "agents": [
    {"name": "Codex", "sessions": 12, "tokens": 1234567},
    {"name": "Claude Code", "sessions": 4, "tokens": null}
  ],
  "projects": [
    {
      "name": "My App",
      "anonymous_name": "Project 1",
      "summary": "Built a new settings screen and fixed login.",
      "anonymous_summary": "Built a settings screen and fixed an account flow.",
      "sessions": 8,
      "tokens": 987654
    },
    {
      "name": "Other projects",
      "anonymous_name": "Other projects",
      "summary": "",
      "anonymous_summary": "",
      "sessions": 8,
      "tokens": 246913
    }
  ],
  "notes": ["Local transcript totals; subscription quota is not available.", "Some sessions have no token data; totals are partial."],
  "anonymous_notes": ["Local transcript totals; subscription quota is not available.", "Some sessions have no token data; totals are partial."]
}
```

`window_hours` lets the card show a tokens-per-hour rate; omit it to hide that figure. Use `null` for unknown token counts. `total_tokens` is the sum of known input and output usage across counted sessions. `cached_input_tokens` is a subset of input, not an extra amount. `agents` contains only tools with verified activity in the selected window; installation alone does not qualify. The card shows per-tool totals, approximate project shares of recorded tokens, and session counts. Tokenizers and cache reporting can vary by agent. If some active sessions lack token data, say so in `notes` and `anonymous_notes`; project shares are then partial. Do not label token counts as subscription quota or cost.

`comparison` is `null` or the recorded tokens of the preceding window of the same length next to the current total. Both totals count only agents the collector parses on its own, so manually added agents do not skew the trend. The card shows it as `2.5x previous week` or `+18% vs previous week`.

`roast_options` lists every automatic roast the data supports, best first. Each fact has several phrasings: the report's week picks which one leads, and phrasings from the last eight exported cards (`recent_roasts` in `prefs.json`) are skipped when possible. Each top project also has `evidence` (commit subjects from the window, from a read-only `git log`) and `clues` (the agents' last replies there), so full mode can summarize without exploring. Neither appears on a card. `plan_limit` is `null` or `{agent, plan, window_minutes, used_percent, cycles}`: how much of the agent's longest plan window was used inside the report window, summed across resets. `subscription` is `null` or `{names, usd_per_month, prorated_usd}` from the user's stated plans. `prompt_hours` is 24 prompt counts by local hour, and `prompt_weekdays` is 7 counts starting Monday. `roast_tier` is one of `warmup`, `regular`, `heavy`, `unhinged`, `legendary`, or `unknown`.

`estimated_api_cost` is `null` or a generated USD estimate from exact model usage matched to a verified rate snapshot. `floor` is true when a model charges for cache writes that the log did not record. `unpriced` lists agent and model pairs with no verified price. `covered_tokens` counts priced input and output tokens; `recorded_tokens` counts all recorded input and output tokens. `partial` also becomes true for active sessions with no tokens or unchecked sources. `components` lists each priced model's token categories, rates, source URL, and subtotal. The amount is an API equivalent at the checked rates, not an invoice, actual spend, or subscription savings. Follow [api-pricing.md](api-pricing.md) to supply rates. The renderer displays an unavailable label when no estimate exists. The repository's fictional `tests/fixtures/demo.json` is generated from explicit usage and rate fixtures.

`banked_resets_used` is `null` unless a successful Codex banked redemption in the chosen window is backed by a timestamped receipt or account history. The private activity file may contain `reset_events` with `provider: "Codex"`, `kind: "banked"`, `status: "redeemed"`, `occurred_at` as a timezone-aware ISO timestamp, `evidence_type: "redemption_receipt"` or `"account_history"`, and a short `evidence` description. The draft counts distinct events in the window. Current available resets, automatic/global resets, and paid instant resets are separate facts and do not count here.

`x_handle` is optional, accepts the handle with or without `@`, and appears only on the named card. The card does not have a profile image. When rendering anonymously, the renderer uses `anonymous_display_name`, `anonymous_roast`, `anonymous_highlight`, `anonymous_name`, `anonymous_summary`, and `anonymous_notes`. It omits `x_handle`. Missing anonymous fields are omitted or replaced with generic text. Do not copy a private name into those fields.
