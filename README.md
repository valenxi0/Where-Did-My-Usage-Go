# Where Did My Usage Go

[![test](https://github.com/valenxi0/Where-Did-My-Usage-Go/actions/workflows/test.yml/badge.svg)](https://github.com/valenxi0/Where-Did-My-Usage-Go/actions/workflows/test.yml)

You hit your weekly limit on Wednesday and have no idea how. This skill finds out.

It reads the history your coding agents already keep on your machine (Claude Code, Codex, Devin, and more) and turns your week into a card you can post: how many tokens you burned, what that would cost at API list prices, which tools and projects ate it, how much of your plan limit you used, and a roast about it.

It's just for fun. The numbers are real and carefully sourced, but the point is a weekly screenshot and a laugh, not accounting. Everything runs locally.

## A real week

Here is one real week (Sep 17-23, 2026) from [@valenxi](https://x.com/valenxi), in all three card styles:

<p>
<img src="docs/cards/classic.png" width="260" alt="Classic card: 1.3B tokens, $686 at API list prices, 178% of a weekly Codex limit, Unhinged tier">
<img src="docs/cards/terminal.png" width="260" alt="Terminal card: the same week as command-line output with bar charts for tools, projects, and prompts by hour">
<img src="docs/cards/receipt.png" width="260" alt="Receipt card: an itemized bill per tool and model, with projects, peak hours, and a $686 total">
</p>

| Style | What it is |
|---|---|
| **Classic** | Big numbers, the roast, and a stats row. Four color themes: `paper`, `night`, `ember`, `cobalt`. |
| **Terminal** | Your week as CLI output with bar charts, floating on a slate background. |
| **Receipt** | An itemized bill: each tool and its priciest models, where the tokens went, when you were busiest, and the total. |

<img src="docs/cards/classic-night.png" width="260" alt="Classic card in the night theme"> <img src="docs/cards/link-preview.png" width="420" alt="1200 by 630 link preview version of the card">

Every style also exports as an Instagram Story (1080×1920) and a link preview (1200×630).

## Install

With [`npx skills`](https://www.npmjs.com/package/skills) (Claude Code, Codex, and other agents):

```bash
npx skills add valenxi0/Where-Did-My-Usage-Go -g
```

As a Claude Code plugin:

```
/plugin marketplace add valenxi0/Where-Did-My-Usage-Go
/plugin install where-did-my-usage-go@where-did-my-usage-go
```

Or by hand: copy or symlink [`skills/where-did-my-usage-go`](skills/where-did-my-usage-go) into `~/.claude/skills` or `~/.codex/skills`.

PNG export needs Python 3.11+ and Pillow. If Pillow is missing, the skill runs the export through `uv run --with pillow`.

## Run it

| Where | Type |
|---|---|
| Claude Code | `/where-did-my-usage-go` |
| Claude Code, installed as a plugin | `/where-did-my-usage-go:where-did-my-usage-go` |
| Codex | `$where-did-my-usage-go` |

Add a window if you like (`/where-did-my-usage-go last 7 days`), or just ask: "where did my usage go this week?"

The skill asks one round of questions, then makes the card:

1. **Window:** last 24 hours, 7 days, 30 days, or custom
2. **Mode:** *quick* (free, about 5 seconds, automatic roast) or *full* (the agent checks what you actually built and writes three roasts for you to pick from)
3. **Name and X handle**, or stay `Player One`
4. **What the card shows:** everything, project names hidden, or fully anonymous
5. **Your plans** (optional), to compare the list price with what you pay
6. **Card style:** classic, terminal, or receipt, or preview all three
7. **Theme** for classic, and **formats** (post, Story, link preview)

It remembers your answers, so next week it only asks for the window.

**No agent needed** (zero tokens):

```bash
cd skills/where-did-my-usage-go
uv run --with pillow python scripts/quick.py --days 7 --name 'Your Name' --style receipt
```

## How it works

```
collect.py  ->  draft.py  ->  (agent verifies and writes roasts)  ->  export_card.py
```

1. **Finds your agents.** The collector lists every command on your `PATH` without running any of them, and checks each known agent's data folder. That covers agents you installed but haven't used, agents found only through their data folder, and generic command names such as Grok's `agent`. In full mode the agent then reviews the whole command list for coding agents missing from the built-in list and adds them with `--agent-cli`.
2. **Reads their history, read-only.**

   | Agent | Where the history lives |
   |---|---|
   | Codex | `~/.codex/sessions` (tokens, models, and plan-limit snapshots) |
   | Claude Code | `~/.claude/projects`, including subagent transcripts |
   | Devin CLI | `~/.local/share/devin/cli/sessions.db` |
   | OpenCode | `~/.local/share/opencode/opencode.db` |
   | Factory Droid | `~/.factory/sessions` (activity only, no tokens) |
   | Kimi Code | `~/.kimi-code/sessions` |
   | Grok | `~/.grok/sessions` |

   Cursor stores no token counts on your machine, so it can only be counted as activity.
3. **Adds it up.** Tokens by tool, project, and model. Prompt habits (counts only). Your busiest hour and day. How much of Codex's plan window you used, summed across resets. The same numbers for the previous window, for the trend.
4. **Prices it.** Each model is priced from a [bundled, sourced price table](skills/where-did-my-usage-go/references/pricing.json) copied from Anthropic's and OpenAI's pricing pages. Uncached input, cache reads, cache writes, output, and long-context requests are priced separately. `check_prices.py` compares the table with OpenRouter.
5. **Roasts you.** Quick mode picks the best automatic line. Full mode has the agent put the effort next to what you actually built ("Codex hit its weekly limit twice for a menu bar app. The menu bar is 24 pixels tall.") and lets you choose.
6. **Renders the card** with bundled fonts, so it looks the same on every OS.

Windows end at the last local midnight, so every run that day gives the same card. Pass `--through-now` to include today.

## Privacy

- **Reads, never writes, your agent histories.** It never launches an agent, signs in, or uses up plan allowance.
- **Keeps its reports in a private folder only you can read:** `~/Library/Application Support/where-did-my-usage-go` on macOS, `%LOCALAPPDATA%` on Windows, `~/.local/share` on Linux, or `WDMUG_DATA_DIR`. Nothing is written to the skill folder or any repository.
- **Makes no network requests or model calls.** The only exceptions are opt-in: `uv` may download Pillow once, and `check_prices.py` fetches OpenRouter's public price list. In full mode your agent reads short excerpts of your transcripts to summarize the work, the same way it reads any file you give it. Quick mode sends nothing anywhere.
- **Prompt habits are stored as counts.** The only phrases saved word for word come from a fixed list of stock replies like "continue" and "try again".
- **Shows only what you choose.** Project names appear only in "everything" mode; otherwise projects get generic labels like `Swift app`. Cards never show prompts, file contents, paths, or keys.
- **Blocks leaks.** Before rendering, export scans every string on the card and refuses if something looks like an API key, token, private key, email address, home-folder path, or IP address.

## What the numbers mean

- **Tokens:** input plus output recorded in local transcripts. Not plan quota, a bill, or value created. Cache reads count as input.
- **At API list prices:** what the same tokens would cost on each provider's standard API today. A `+` means it's a minimum: some models have no public price, or a log left out cache writes. It is not what you paid. See the [pricing guide](skills/where-did-my-usage-go/references/api-pricing.md).
- **Plan limit** (`codex weekly 178%`): how much of Codex's own weekly limit you used inside the window, summed across resets.
- **Tier:** tokens per hour, averaged over at least a day. Warm-up, Regular (100K/h), Heavy (1M/h), Unhinged (6M/h), and Legendary (30M/h, about 5B a week).
- **vs previous week:** the same-length window just before yours, counting only agents parsed automatically.
- **Busiest:** when you sent prompts, by local hour and weekday. That's when you were at the keyboard, not when the agents ran.
- **Where it went:** your top projects by tokens. Full mode checks summaries against files or commits; a request alone doesn't count as shipped.

## Run the scripts yourself

```bash
cd skills/where-did-my-usage-go
python3 scripts/collect.py --days 7
python3 scripts/draft.py --name 'Your Name' --x-handle '@you' --plan 'Claude Max=100'
# edit share.json: summaries, highlight, roast
uv run --with pillow python scripts/export_card.py --visibility private-projects --style all   # preview the styles
uv run --with pillow python scripts/export_card.py --visibility private-projects --style receipt --formats post,story,og
```

## Contributing

History formats change, and there are always more agents. Parsers for new agents, price updates, and new card styles are welcome.

```bash
uv run --with pillow python -m unittest discover -s tests
python3 examples/build_demo.py                                   # rebuild the fictional demo
python3 skills/where-did-my-usage-go/scripts/check_prices.py     # compare prices with OpenRouter
```

Made by [@valenxi](https://x.com/valenxi). MIT licensed.
