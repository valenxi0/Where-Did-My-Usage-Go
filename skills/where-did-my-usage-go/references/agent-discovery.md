# Adding an agent the collector doesn't know

The collector looks up only the commands and history folders of agents it knows (`KNOWN_CLIS` in `scripts/collect.py`). It never lists the rest of `PATH`. Use this guide only when the user names an agent it missed.

1. Rerun collection with `--agent-cli COMMAND`. The collector checks that one command and records it in `sources` as `detected, unparsed`. Do this before adding sessions by hand, because collection rewrites `activity.json`.
2. Find that agent's history folder, database, or read-only usage view. Look only in that agent's own home, XDG, or app-support folder.
3. Set its `activity_in_window` in `sources` to `true` only after finding an event inside the window. Set it to `false` after checking enough history to show no activity, and leave it `null` if you can't tell.
4. To add a session by hand, include `agent`, `session_id`, `project`, and `tokens` (`input_tokens`, `output_tokens`, `cached_input_tokens`). Use `tokens: null` if activity is verified but tokens aren't recorded. Check timestamps, cache meaning, and duplicate events first.
5. Never run a prompt, start a session, sign in, install anything, or use up the user's allowance to fill a gap.

The card names only agents with verified activity in the window. If a detected agent couldn't be checked, the card shows a generic coverage note without naming it.
