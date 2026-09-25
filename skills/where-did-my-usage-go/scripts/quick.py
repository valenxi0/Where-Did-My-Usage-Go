#!/usr/bin/env python3
"""One command: collect, draft, and export a card in a few seconds.

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
    parser.add_argument("--excerpts", action="store_true",
                        help="Keep short transcript excerpts so an agent can upgrade the card afterward")
    parser.add_argument("--through-now", action="store_true", help="Include today")
    parser.add_argument("--agent-cli", action="append", default=[], metavar="COMMAND")
    args, passthrough = parser.parse_known_args()
    collect = ["--days" if args.days else "--hours", str(args.days or args.hours)]
    collect += [] if args.excerpts else ["--counts-only"]
    collect += ["--through-now"] if args.through_now else []
    for command in args.agent_cli:
        collect += ["--agent-cli", command]
    run("collect.py", *collect)
    run("draft.py", *passthrough)
    run("export_card.py", "--visibility", args.visibility, "--formats", args.formats, "--style", args.style)
    print(f"Card: {private_dir() / 'player-card.png'}")


if __name__ == "__main__":
    main()
