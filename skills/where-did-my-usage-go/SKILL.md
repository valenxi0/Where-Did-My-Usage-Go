---
name: where-did-my-usage-go
description: Create a shareable card of recent coding-agent activity, recorded tokens, and API-equivalent cost when the user asks where their AI coding usage went or what they built in a time window.
---

# Where Did My Usage Go

Turn a time window of local coding-agent history into a truthful PNG card plus an HTML preview. Everything stays local. Never upload transcripts or reports, and never send them to an image model.

Run every script from this skill's directory. Private files go to the user's app-data folder (`WDMUG_DATA_DIR` overrides it), never into the skill or a repository.

## 1. Ask once, then collect

Read `prefs.json` in the private folder first (`python3 -c "import sys; sys.path.insert(0, 'scripts'); import prefs; print(prefs.load())"`). It remembers name, handle, plans, visibility, and theme from earlier runs.

Ask everything in one turn. Use the host's multiple-choice question tool when it has one (for example `AskUserQuestion` in Claude Code), with the recommended option first. Otherwise, write one short numbered message with the defaults shown. Skip any question the user already answered or that `prefs.json` answers, and offer "same as last time" instead.

1. **Window:** last 24 hours, last 7 days (recommended for a weekly post), last 30 days, or custom. Always ask; never pick one silently.
2. **Mode:** quick (free: automatic roast, no project summaries, about 5 seconds) or full (you verify what was built and write the roast; uses tokens).
3. **Who is on the card:** display name and optional X handle, or `Player One`. Never infer them from the machine or logs.
4. **What it shows:** everything, hide project names (`private-projects`), or anonymous. Unanswered means anonymous.
5. **Plans (optional):** which AI subscriptions they pay for and the monthly price of each, for the "vs your plans" stat. Never guess a price. A plan name in the logs (Codex records one) is a hint to confirm, not an answer.
6. **Card style:** `classic` (big numbers, color themes), `terminal` (CLI output with bar charts), or `receipt` (an itemized bill per tool, with projects and peak hours), or "show me all three". For "show me", run `export_card.py --style all` after drafting, show the previews, then continue with their pick.
7. **Theme (classic only):** `paper` (off-white, electric blue), `night` (near-black, lime), `ember` (charcoal, orange), `cobalt` (navy, periwinkle), or "show me all four". For "show me", run `export_card.py --theme all` after drafting, show the four previews, then export with their pick. Always ask; do not silently use the default.
8. **Formats (optional):** feed post (default), Story, link preview.

**Quick mode:** run `python3 scripts/quick.py --days N --visibility V --style S --formats post[,story,og] [--name ... --x-handle ... --plan "Name=USD"]`, show the PNG, and stop.

**Full mode:** run `python3 scripts/collect.py --days N` (or `--hours N`) and continue below.

Windows end at the last local midnight (`--days`) or the top of the hour (`--hours`), so every run that day gives the same card. Add `--through-now` only if the user asks to include today.

## 2. Check coverage

Open the private `activity.json`. Scan all of `cli_inventory` and `sources` for coding agents, including ones not in the built-in list. For each detected agent that is not parsed automatically, follow `references/agent-discovery.md`, then rerun with `--agent-cli COMMAND` as needed. Codex, Claude Code (including subagents), OpenCode, Factory Droid, Kimi Code, Grok, and the Devin CLI are parsed automatically. Cursor keeps no local token counts, so at most its activity can be verified.

An installed agent appears on the card only if it has verified activity in the window.

## 3. Draft

```
python3 scripts/draft.py [--name "NAME"] [--x-handle "@handle"] [--plan "ChatGPT Pro=200" ...]
```

Name, handle, and plans are remembered for the next run.

The draft prices recorded usage with the bundled table in `references/pricing.json`. For each model it prints `No verified price`, check the provider's official price page. If a price exists, add it to a private override table and rerun with `--pricing /path/to/extra.json` (see `references/api-pricing.md`). If the draft says the table is stale, refresh it the same way. `python3 scripts/check_prices.py --write-missing /path/extra.json` compares the table with OpenRouter and writes OpenRouter rates for models that have no first-party price. Review that file before using it. Never type a dollar amount into `share.json`.

## 4. Edit `share.json`

- **Summaries and `highlight`:** say "built" only when files, commits, or explicit completion messages prove it. Otherwise say "worked on" or "explored". Use prompts and final messages as clues, not proof.
- **Project labels on hidden-name cards:** the draft guesses `anonymous_name` from the project's files (`Swift app`, `Next.js app`, `Agent skill`). Replace it with a generic description of what was built, such as `macOS menu bar app` or `recipe search site`, with no product, company, or client name. `Project N` is only for when nothing better is known.
- **`roast`:** the draft fills `roast_options` with automatic lines and `roast_material` with plain facts. Write three candidates using the method below, show them with the best automatic option, and let the user pick. Put the pick in `roast`. Put a version with no project details in `anonymous_roast`.
- **`anonymous_*` fields:** no project names, task names, or handle.
- **Banked resets:** add a `reset_events` entry to `activity.json` and redraft only when a timestamped redemption receipt or account history proves a Codex banked reset was used in the window. A lower balance is not proof. Never trigger a reset.
- Review the whole file for secrets, personal data, and unsupported claims.

**Roast method.** The best roasts put the effort and the result side by side: a huge number next to a small, specific thing that was actually built or done. The automatic lines only know numbers. You also know what was built, and that is where the joke is.

1. Pick one effort fact from `roast_material`: tokens, list price, cost per prompt, plan limit, busiest hour, or trend.
2. Pick one concrete thing from the verified summaries or habits: what the project is, what kept breaking, or the stock phrase they kept typing.
3. Put them side by side and end on the smaller, more specific one. Deadpan, no explaining.

Rules:
- One or two short sentences, under about 110 characters.
- Aim at the work and the workflow, never the person's identity, looks, health, money, or skill.
- Use only facts that are true. Quote only the stock phrases in `roast_material`, never a free-form prompt.
- The anonymous version must not reveal what the project is if that would identify it.
- Do not open with their name, make tokens into characters, use exclamation marks or emojis, or call tokens money spent.

Good:
- `Codex hit its weekly limit twice for a menu bar app. The menu bar is 24 pixels tall.`
- `1B tokens on one Next.js app. The landing page has never been more thoroughly considered.`
- `At list prices, every prompt you typed cost $9.61. The most common one was 'continue'.`
- `You said please 112 times. Smart. They'll remember who was nice.`

Bad:
- `Resonance, the tokens have formed a union and named you in the complaint!` (generic, uses the name, personifies tokens)
- `1.7 billion tokens? Even your cache is asking for paid time off.` (about the number, not about them)
- `Maybe learn to code instead of asking AI for everything.` (aimed at the person's ability)

## 5. Export and share

```
python3 scripts/export_card.py --visibility named|private-projects|anonymous [--style classic|terminal|receipt] [--theme paper] [--formats post,story,og]
```

Visibility, style, and theme are remembered. Every style shows "Created by @valenxi on X" near the bottom. The link preview (`og`) uses the classic layout for every style so it stays legible as a thumbnail. `private-projects` shows the name and handle but hides project and task names. Export refuses to run if the visible text looks like it contains a key, token, email, home-folder path, or IP address. Fix `share.json` rather than passing `--allow-flagged`, unless the flagged text is harmless. PNG export needs Pillow; if it is missing, prefix the command with `uv run --with pillow`. Look at the PNG before the user shares it. Re-exporting makes no model calls.

If the user wants a caption, write one line with a concrete outcome, one surprising number, and a question such as "Where did yours go?". Respect the visibility choice they made.

## Truth rules

- Tokens are recorded transcript usage. They are not plan quota, a bill, or value created.
- The API equivalent is what the recorded tokens would cost at today's list prices. It is not what the user paid.
- `+` after the price means it is a minimum: some usage had no public price or no recorded cache writes.
- The plan-limit stat (for example `codex weekly 214%`) sums how much of each plan window was used inside the report window, across resets. It comes from the agent's own quota snapshots.
- "vs your plans" compares the list-price total with the user's stated plan prices, prorated to the window. It is a comparison, not savings.
- Tiers are tokens per hour over the window, counted as at least a day: Warm-up, Regular (100K/h), Heavy (1M/h), Unhinged (6M/h), Legendary (30M/h, about 5B a week).
- If no token data exists, the tier is `unknown`. Never invent totals.
