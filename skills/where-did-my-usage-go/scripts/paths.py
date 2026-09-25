"""Private output locations shared by the skill's command-line scripts."""

import os
import sys
from pathlib import Path


def private_dir():
    override = os.environ.get("WDMUG_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/where-did-my-usage-go"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "where-did-my-usage-go"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "where-did-my-usage-go"


def ensure_parent(path):
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)
    return parent
