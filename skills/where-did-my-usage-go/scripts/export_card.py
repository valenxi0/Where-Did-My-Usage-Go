#!/usr/bin/env python3
"""Export PNG card(s) and an HTML preview from one saved report without an AI call."""

import argparse
import json
from pathlib import Path

import prefs
from card import view
from paths import ensure_parent, private_dir
from pricing import valid_estimate
from render import render as render_html
from render_png import DEFAULT_THEME, FORMATS, STYLES, THEMES, render as render_png
from scan import findings

VISIBILITIES = ("named", "anonymous", "private-projects")


def export(data, output, visibility, theme, formats, allow_flagged=False, style="classic"):
    """Write `<output>.png` (post), `<output>-story.png`, `<output>-og.png`, and `<output>.html`."""
    if data.get("estimated_api_cost") is not None and not valid_estimate(data["estimated_api_cost"]):
        raise ValueError("API equivalent does not match its saved token and rate breakdown")
    flagged = findings(view(data, visibility))
    if flagged and not allow_flagged:
        raise ValueError("The card would show text that looks private: "
                         + "; ".join(f"{kind} ({sample})" for kind, sample in flagged)
                         + ". Edit share.json, or pass --allow-flagged after checking it is safe.")
    ensure_parent(output)
    written = []
    for fmt in formats:
        path = output.with_name(output.name + ("" if fmt == "post" else f"-{fmt}")).with_suffix(".png")
        render_png(data, visibility, theme, fmt, style).save(path, format="PNG", optimize=True)
        written.append(path)
    html_path = output.with_suffix(".html")
    html_path.write_text(render_html(data, visibility, written[0].name), encoding="utf-8")
    for path in (*written, html_path):
        path.chmod(0o600)
    return [*written, html_path]


def main():
    remembered = prefs.load()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=private_dir() / "share.json")
    parser.add_argument("--output", type=Path, default=private_dir() / "player-card", help="Output basename without an extension")
    parser.add_argument("--visibility", choices=VISIBILITIES, default=remembered.get("visibility"),
                        help="Remembered after first use; required the first time")
    parser.add_argument("--theme", choices=[*sorted(THEMES), "all"], default=remembered.get("theme", DEFAULT_THEME),
                        help="'all' writes one preview per theme so the user can choose")
    parser.add_argument("--style", choices=[*STYLES, "all"], default=remembered.get("style", "classic"),
                        help="classic, terminal, or receipt; 'all' writes one preview per style")
    parser.add_argument("--formats", default="post", help=f"Comma-separated: {', '.join(FORMATS)}")
    parser.add_argument("--allow-flagged", action="store_true", help="Export even if the privacy scan flags text")
    args = parser.parse_args()
    formats = [value.strip() for value in args.formats.split(",") if value.strip()]
    if not args.visibility:
        parser.error("Choose --visibility named, private-projects, or anonymous")
    if not formats or any(value not in FORMATS for value in formats):
        parser.error(f"--formats must list some of: {', '.join(FORMATS)}")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        parser.error("Input must be a JSON object")
    if "all" in (args.theme, args.style):
        # Preview mode: one post per style (or per classic theme) so the user can choose.
        options = ([("classic", theme) for theme in sorted(THEMES)] if args.theme == "all"
                   else [(style, args.theme) for style in STYLES])
        previews = []
        for style, theme in options:
            name = f"{args.output.name}-{theme if args.theme == 'all' else style}"
            try:
                previews += export(data, args.output.with_name(name), args.visibility, theme, ["post"],
                                   args.allow_flagged, style)[:1]
            except ValueError as error:
                parser.error(str(error))
        print("Previews: " + ", ".join(str(path) for path in previews) + ". Export again with the chosen option.")
        return
    try:
        written = export(data, args.output, args.visibility, args.theme, formats, args.allow_flagged, args.style)
    except ValueError as error:
        parser.error(str(error))
    prefs.save(visibility=args.visibility, theme=args.theme, style=args.style)
    print("Wrote " + ", ".join(str(path) for path in written) + ". Re-run to export again without an AI call.")


if __name__ == "__main__":
    main()
