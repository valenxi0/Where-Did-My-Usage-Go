#!/usr/bin/env python3
"""Render the local HTML preview: the exported PNG plus a readable, linkable transcript."""

import argparse
import html
import json
from pathlib import Path

from card import REPO_LABEL, REPO_URL, compact, number, plural, view


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def share_detail(row):
    if row["share"] is None:
        return "no token data"
    return f"{compact(row['tokens'])} tokens · {row['share_text']}"


def render(data, visibility, image=None):
    card = view(data, visibility)
    name = esc(card["name"])
    handle = (f' <a href="https://x.com/{card["handle"]}">@{card["handle"]}</a>' if card["handle"] else "")
    agents = "".join(f"<li><b>{esc(row['label'])}</b> <span>{esc(share_detail(row))} · {plural(row['sessions'], 'session')}</span></li>"
                     for row in card["agents"]) or "<li>No tool usage recorded.</li>"
    projects = "".join(f"<li><b>{esc(row['label'])}</b> <span>{esc(share_detail(row))}</span>"
                       + (f"<p>{esc(row['summary'])}</p>" if row["summary"] else "") + "</li>"
                       for row in card["projects"]) or "<li>No projects recorded.</li>"
    facts = [plural(card["sessions"], "recorded session"), card["api_label"]]
    if card["trend"]:
        facts.append(card["trend"])
    if card["plan_multiple"] is not None:
        facts.append(f"{card['plan_multiple']:.1f}x the stated plan prices for this window")
    if card["limit"]:
        facts.append(f"{card['limit']['used_percent']:.0f}% of a {card['limit']['agent']} plan window used")
    if card["per_hour"] is not None:
        facts.insert(1, f"{compact(card['per_hour'])} tokens per hour")
    if card["resets"]:
        facts.append(f"{card['resets']} Codex banked reset{'s' if card['resets'] != 1 else ''} used")
    figure = (f'<img src="{esc(image)}" width="1080" height="1350" alt="Usage card for {name}: '
              f'{esc(compact(card["total"]))} recorded tokens. {esc(card["roast"])}">' if image else "")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Where Did My Usage Go · {name}</title>
<style>
:root {{ color-scheme: dark; --bg: #0e100c; --ink: #eef1e6; --muted: #8d957f; --line: #262b22; --accent: #c6f36b; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 48px 24px; display: grid; grid-template-columns: minmax(0, 540px) minmax(0, 1fr); gap: 56px; align-items: start; }}
img {{ width: 100%; height: auto; border-radius: 12px; border: 1px solid var(--line); }}
h1 {{ font-size: 40px; line-height: 1.1; letter-spacing: -.03em; margin: 0; }}
h1 a, a {{ color: var(--muted); text-decoration: none; }}
h2 {{ font-size: 15px; margin: 32px 0 8px; color: var(--muted); font-weight: 600; }}
.total {{ font-size: 64px; font-weight: 800; letter-spacing: -.04em; margin: 16px 0 0; }}
.total span {{ color: var(--accent); font-size: 28px; font-weight: 500; letter-spacing: 0; }}
.roast {{ border-left: 4px solid var(--accent); padding-left: 16px; font-size: 20px; }}
ul {{ list-style: none; padding: 0; margin: 0; }}
li {{ padding: 10px 0; border-top: 1px solid var(--line); }}
li span, .muted, li p {{ color: var(--muted); }}
li span {{ float: right; font-family: ui-monospace, Menlo, monospace; font-size: 14px; }}
li p {{ margin: 4px 0 0; }}
.notes {{ font-size: 13px; }}
footer {{ margin-top: 32px; display: flex; justify-content: space-between; gap: 16px; font-size: 14px; }}
footer a:first-child {{ color: var(--accent); }}
@media (max-width: 860px) {{ main {{ grid-template-columns: 1fr; gap: 32px; }} }}
</style></head><body><main>
{f"<figure style='margin:0'>{figure}</figure>" if figure else ""}
<article>
<p class="muted">{esc(card["window"])}</p>
<h1>{name}{handle}</h1>
<p class="total">{esc(compact(card["total"]))} <span>tokens</span></p>
<p class="muted">{esc(number(card["total"]))} recorded · {esc(card["tier_label"])} tier</p>
<p class="roast">{esc(card["roast"])}</p>
{f'<h2>Biggest win</h2><p>{esc(card["highlight"])}</p>' if card["highlight"] else ""}
<h2>Tools</h2><ul>{agents}</ul>
<h2>Where it went</h2><ul>{projects}</ul>
<h2>Numbers</h2><ul>{"".join(f"<li>{esc(fact)}</li>" for fact in facts)}</ul>
<ul class="notes muted">{"".join(f"<li>{esc(note)}</li>" for note in card["notes"])}</ul>
<footer><a href="{REPO_URL}">{REPO_LABEL}</a></footer>
</article>
</main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visibility", choices=("named", "anonymous", "private-projects"), required=True)
    parser.add_argument("--image", help="PNG path to embed, relative to the HTML file")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        parser.error("Input must be a JSON object")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data, args.visibility, args.image), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
