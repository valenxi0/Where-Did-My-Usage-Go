# Full mode: check the work and write the roast

Edit the private `share.json` that `draft.py` wrote. The schema is in `share-schema.md`.

## Summaries

- Read the prompts and final messages in `activity.json` as clues, then confirm against files, commits, or explicit completion messages. Say "built" only with that proof. Otherwise say "worked on" or "explored".
- Write `summary` for named cards and `anonymous_summary` for hidden-name cards. The anonymous version names no product, company, client, or person.
- The draft guesses `anonymous_name` from project files (`Swift app`, `Next.js app`). Replace it with a generic description of the work, such as `macOS menu bar app`. Keep `Project N` only when nothing better is known.
- Set `highlight` to the single most concrete verified outcome.

## Prices

`draft.py` prints `No verified price: agent / model` for anything the bundled table lacks. Check that provider's own pricing page. If a price exists, write a private override table and rerun with `--pricing /path/extra.json` (see `api-pricing.md`). `python3 scripts/check_prices.py --write-missing /path/extra.json` fills models that have no first-party price from OpenRouter. Review that file before using it. Never type a dollar amount into `share.json`.

## Banked resets

Add a `reset_events` entry to `activity.json` and redraft only when a timestamped redemption receipt or account history proves a Codex banked reset was used in the window. A lower balance is not proof. Never trigger a reset.

## The roast

The best roast puts the effort next to the result: a big number next to a small, specific thing that was actually built or done. The automatic lines in `roast_options` only know numbers. You also know what was built, and the joke comes from that.

1. Pick one effort fact from `roast_material`: tokens, list price, cost per prompt, plan limit, busiest hour, or trend.
2. Pick one concrete thing from the verified summaries or habits: what the project is, what kept breaking, or the stock phrase they kept typing.
3. Put them side by side and end on the smaller, more specific one. Keep it deadpan and don't explain the joke.

Rules:

- One or two short sentences, under about 110 characters.
- Aim at the work and the workflow, never at the person's identity, looks, health, money, or skill.
- Use only true facts. Quote only the stock phrases listed in `roast_material`, never a free-form prompt.
- Don't open with their name, make tokens into characters, use exclamation marks or emojis, or call tokens money spent.
- Put the pick in `roast`, and a version with no project details in `anonymous_roast`.

Good:

- `Codex hit its weekly limit twice for a menu bar app. The menu bar is 24 pixels tall.`
- `1B tokens on one Next.js app. The landing page has never been more thoroughly considered.`
- `At list prices, every prompt you typed cost $9.61. The most common one was 'continue'.`

Bad:

- `Sam, the tokens have formed a union and named you in the complaint!` It's generic, uses the name, and personifies tokens.
- `1.7 billion tokens? Even your cache is asking for paid time off.` It's about the number, not about them.
- `Maybe learn to code instead of asking AI for everything.` It's aimed at the person's skill.

## Caption

If the user wants one, write a single line with a concrete outcome, one surprising number, and a question such as "Where did yours go?". Keep to the visibility they chose.
