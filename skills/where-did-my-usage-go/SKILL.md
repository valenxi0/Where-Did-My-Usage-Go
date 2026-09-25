---
name: where-did-my-usage-go
description: Make a shareable card of the user's recent coding-agent usage, with tokens, API list price, plan-limit usage, top tools and projects, and a roast. Use when the user asks where their AI coding usage or limit went, or what they built in a time window.
---

# Where Did My Usage Go

Turn a window of the user's local coding-agent history into a PNG card. Run scripts from this skill's directory. Reports stay in the user's private app-data folder. Never upload transcripts or reports, and never send them to an image model.

## 1. Ask three questions

Load remembered answers first: `python3 -c "import sys; sys.path.insert(0, 'scripts'); import prefs; print(prefs.load())"`. Skip any question the user or `prefs.json` already answered. If `prefs.json` has no name, don't claim one is saved.

Ask the rest in a single question-tool call, so the user picks from options and must answer before you continue. In Claude Code that tool is `AskUserQuestion`, with all three questions in one call and the recommended option first. Only if the host has no such tool, or the call fails, ask the same three questions in one short message and wait for the reply:

1. **Window:** Last 7 days (recommended), Last 24 hours, Last 30 days, Custom. Never pick one silently.
2. **Card style:** Classic, Terminal, Receipt, or Show me all three.
3. **Who's on the card:** name and @handle, name but hide project names, or anonymous. If they pick a name, ask for it in the same turn. Never infer a name or handle from the machine or logs.

Use defaults for everything else: the `paper` theme, the feed post format, and no plan price.

## 2. Collect and draft

```
python3 scripts/collect.py --days N          # or --hours N
python3 scripts/draft.py [--name "NAME"] [--x-handle "@handle"]
```

The collector reads only known agents' history folders. If the user mentions an agent it missed, rerun with `--agent-cli COMMAND` and follow `references/agent-discovery.md`. Windows end at the last local midnight. Add `--through-now` only if the user asks to include today.

If the user asked for speed, or you can't read files, run `python3 scripts/quick.py --days N --style S --visibility V [--name ...]` instead, show the card, and stop.

## 3. Check the work and write the roast

Read `references/full-mode.md` now. It covers project summaries, generic labels for hidden names, missing prices, and the roast method. Write three roasts, show them with the best automatic line from `roast_options`, and let the user pick.

## 4. Export

```
python3 scripts/export_card.py --visibility named|private-projects|anonymous --style classic|terminal|receipt
```

`--style all` or `--theme all` writes previews to choose from. Add `--formats post,story,og` for a Story or a link preview. If Pillow is missing, prefix the command with `uv run --with pillow`. Export refuses text that looks like a key, email, path, or IP address. Fix `share.json` instead of forcing it.

Show the PNG. Then offer once: "Want a different theme, a Story version, or your plan price on it? Re-exporting is free." For plan prices, rerun `draft.py --plan "Name=USD"` with prices the user states. Never guess a price.

## Truth rules

- Tokens are recorded transcript usage. They are not plan quota, a bill, or value created.
- The API price is what those tokens would cost at today's list prices, not what the user paid. A `+` means it's a minimum.
- Say "built" only when files, commits, or completion messages prove it. Otherwise say "worked on".
- If no token data exists, say so. Never invent totals.
