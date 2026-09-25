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

## 2. Show the card first

Run one command. It collects, drafts, and exports in about 10 seconds:

```
python3 scripts/quick.py --days N --style S --visibility named|private-projects|anonymous --excerpts [--name "NAME" --x-handle "@handle"]
```

Use `--hours N` for windows under a day. If Pillow is missing, prefix it with `uv run --with pillow`. Show the PNG path it prints right away, before doing anything else.

Windows end at the last local midnight; add `--through-now` only if the user asks to include today. The collector reads only known agents' history folders. If the user names an agent it missed, rerun with `--agent-cli COMMAND` and follow `references/agent-discovery.md`.

## 3. Offer the upgrade

Ask once: "Want me to check what you built and write a custom roast? About two minutes." Also mention that a different theme, a Story version, or their plan price is a free re-export.

If they want the upgrade, read `references/full-mode.md` and follow it: summaries from `evidence` and `clues`, then three roasts for the user to pick from. Then re-export:

```
python3 scripts/export_card.py --visibility V --style S [--theme T] [--formats post,story,og]
```

`--style all` or `--theme all` writes previews to choose from. For plan prices, rerun `draft.py --plan "Name=USD"` with prices the user states, then re-export. Never guess a price. Rerunning `draft.py` replaces upgrade edits (it keeps a backup), so add plan prices before the upgrade. Export refuses text that looks like a key, email, path, or IP address; fix `share.json` instead of forcing it.

## Truth rules

- Tokens are recorded transcript usage. They are not plan quota, a bill, or value created.
- The API price is what those tokens would cost at today's list prices, not what the user paid. A `+` means it's a minimum.
- Say "built" only when files, commits, or completion messages prove it. Otherwise say "worked on".
- If no token data exists, say so. Never invent totals.
