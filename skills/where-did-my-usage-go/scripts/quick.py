#!/usr/bin/env python3
"""One command, no agent, no tokens: collect, draft, and export a card.

Uses the automatic roast and bundled prices, and leaves project summaries empty
(the card then shows session counts). Remembered answers from earlier runs fill
in the name, handle, plans, visibility, and theme. Run the full skill when you
want verified summaries and a hand-written roast.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import prefs
from paths import private_dir

HERE = Path(__file__).resolve().parent


def run(script, *arguments):
    subprocess.run([sys.executable, str(HERE / script), *arguments], check=True)


def main():
    remembered = prefs.load()
    parser = argparse.ArgumentParser(description=__doc__)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument("--hours", type=float)
    window.add_argument("--days", type=float)
    parser.add_argument("--visibility", choices=("named", "private-projects", "anonymous"),
                        default=remembered.get("visibility", "anonymous"))
    parser.add_argument("--formats", default="post")
    parser.add_argument("--style", choices=("classic", "terminal", "receipt"), default=remembered.get("style", "classic"))
    args, passthrough = parser.parse_known_args()
    run("collect.py", "--days" if args.days else "--hours", str(args.days or args.hours))
    run("draft.py", *passthrough)
    run("export_card.py", "--visibility", args.visibility, "--formats", args.formats, "--style", args.style)
    print(f"Card ready in {private_dir()}. Project summaries are blank in quick mode; the full skill fills them in.")


if __name__ == "__main__":
    main()
