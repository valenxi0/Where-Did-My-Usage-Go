# Contributing

The most useful contributions are support for another coding agent and price updates. Card styles and fixes are welcome too.

## Setup

```bash
git clone https://github.com/valenxi0/Where-Did-My-Usage-Go
cd Where-Did-My-Usage-Go
uv run --with pillow python -m unittest discover -s tests
```

The scripts need only Python 3.11 or later. Pillow is needed only for PNG export and its tests.

When you run the scripts against your own history while developing, set `WDMUG_DATA_DIR` on the same command line, as in `WDMUG_DATA_DIR=/tmp/wdmug python3 scripts/collect.py --days 7`. Without it, the scripts write to your real private report folder.

## Add an agent

All collectors live in `skills/where-did-my-usage-go/scripts/collect.py`.

1. Find where the agent saves its history on disk, and check the format by reading it. Never run the agent to create test data.
2. Write a reader that takes the history path plus the window's `start` and `end`, and returns sessions in the same shape as the existing readers: `agent`, `session_id`, `project`, `tokens` (`input_tokens`, `output_tokens`, `cached_input_tokens`), `model_usage`, `prompts`, `final_messages`, and `habits`. Use `tokens: None` if the agent doesn't record tokens. Don't write zero.
3. Count only events inside the window, and remove duplicates if the agent repeats messages. `devin_sessions` and `claude_session` both show how.
4. Register the agent in `discover()` and `read_sessions()`, and add it to `AUTO_AGENTS` if the reader is automatic.
5. Add a test in `tests/test_reports.py` built from a small, made-up history file. Never commit real transcripts.
6. Add the agent to the "How it works" table in the README.

## Update a price

Prices live in `skills/where-did-my-usage-go/references/pricing.json`. Copy each rate from the provider's own pricing page, put that page in `source_url`, and set `as_of` to the day you checked. `python3 skills/where-did-my-usage-go/scripts/check_prices.py` compares the table with OpenRouter. When the two disagree, the provider's page wins. Record a known difference in `openrouter_differs`. The [pricing guide](skills/where-did-my-usage-go/references/api-pricing.md) explains every field.

## Card styles

Classic is in `render_png.py`. Terminal and receipt are in `styles.py`. Every style takes the view from `card.view()`, which is where the visibility rules live, so a new style inherits them. Test that an anonymous card renders identical bytes when the named fields change. `test_anonymous_image_ignores_named_only_content` checks every style listed in `STYLES`.

## Before you open a pull request

- Run the tests.
- If your change affects the demo report, rebuild it with `python3 tests/fixtures/build_demo.py`.
- Keep real usage data, names, and paths out of the commit.
