"""Print a script's result as JSON and, with --result FILE, save the same
JSON to that file.

Some shells shorten what a command prints: an output filter can turn
every successful `uv run` into the single word "ok". The skill passes
--result and reads the file, so it always sees the whole result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def add_argument(p: argparse.ArgumentParser) -> None:
    p.add_argument("--result", type=Path, help="also write the JSON result to this file (read it instead of the output)")


def clear(path: Path | None) -> None:
    """Remove an earlier result first, so a run that fails leaves no stale
    file behind to be read as this run's answer."""
    if path is not None:
        path.unlink(missing_ok=True)


def emit(obj, path: Path | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
