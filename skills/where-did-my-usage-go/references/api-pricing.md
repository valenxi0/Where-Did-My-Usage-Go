# API equivalent pricing

`draft.py` prices recorded usage with `references/pricing.json`, a dated table of standard direct-API rates copied from official pages. It prints every model it could not price and warns when the table is more than 45 days old.

## How a model is matched

Prices belong to models, not agents: Devin running `claude-opus-5-5-medium` uses the Claude Opus 5.5 price. Before lookup, a logged ID drops its provider prefix (`anthropic/`), context tag (`[1m]`), dated snapshot suffix (`-20260301`), and reasoning-effort suffix (`-medium`, `-high`). None of these change the per-token rate. Anything else must match exactly. Never price one model with another model's rate.

## Adding or refreshing prices

Check the provider's official page, for example [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing), [OpenAI API pricing](https://developers.openai.com/api/docs/pricing), or [xAI pricing](https://docs.x.ai/developers/pricing). Write a private override file outside the skill and pass it with `--pricing` (repeatable). Entries replace bundled entries model by model:

```json
{
  "as_of": "YYYY-MM-DD",
  "models": [
    {
      "model": "exact-model-id",
      "input_per_million": 0,
      "cached_input_per_million": 0,
      "cache_write_per_million": 0,
      "cache_write_1h_per_million": 0,
      "output_per_million": 0,
      "long_context": {"above_input_tokens": 272000, "input_per_million": 0, "cached_input_per_million": 0, "cache_write_per_million": 0, "output_per_million": 0},
      "source_url": "https://provider.example/official-pricing"
    }
  ]
}
```

The zeroes are placeholders. Include a write rate only if the provider charges one: `cache_write_per_million` is the default or five-minute write, and `cache_write_1h_per_million` is Anthropic's one-hour write. Include `long_context` only when the provider bills whole requests above a size at a higher rate. The collector tags Codex and OpenCode requests over 272K input tokens. If a model has no long-context block, tagged requests use its standard rates, because providers such as Anthropic price the full window at standard rates. Leave out batch, flex, fast, regional, and tool charges unless the logs prove they applied.

`scripts/check_prices.py` compares every bundled price with [OpenRouter's model list](https://openrouter.ai/api/v1/models) and prints mismatches. The provider's own page wins a disagreement: on 2026-09-24, OpenRouter listed `gpt-5.6-sol` at half of OpenAI's published rate. With `--write-missing PATH`, it writes OpenRouter rates for models in your activity that have no first-party price, such as open-weight models served by an agent vendor. OpenRouter is then recorded as the source.

To update the bundled table in the repository, edit `references/pricing.json`, set `as_of`, and keep every entry's `source_url`.

## The math

For each model and context tier:

`(uncached input × input + cache reads × cached input + 5m writes × write + 1h writes × 1h write + output × output) / 1,000,000`

where uncached input = input − cache reads − writes. `share.json` saves every component's counts, rates, source, and subtotal under `estimated_api_cost.components`. Export refuses an amount that cannot be rebuilt from that breakdown.

## When the number is a minimum

The card adds `+` and a note when:
- some recorded tokens have no verified price (listed under `estimated_api_cost.unpriced`)
- sessions were active but logged no tokens, or coverage is incomplete
- a model charges for cache writes but the log did not record them (`floor: true`). Those tokens are priced as plain input, which is lower than the write rate.

Past usage priced at today's rates is a current-rate comparison, not a historical bill.
