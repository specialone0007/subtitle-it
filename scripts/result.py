"""Print a script's result as JSON and, with --result FILE, save the same
JSON to that file.

Some shells and command wrappers shorten what a command prints, down to a
single "ok" for a command that succeeded. The skill passes --result and
reads the file, so it always sees the whole result.

Also the small helpers every script shares: `path` for path arguments and
`write_private` for the credentials file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def path(text: str) -> Path:
    """A path argument with a leading ~ expanded: `--config ~/.config/x`
    arrives unexpanded when the shell quotes it."""
    return Path(text).expanduser()


def write_private(dest: Path, text: str) -> None:
    """Write text to dest through a temporary file that only the owner can
    read from the moment it exists, then move it into place."""
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, dest)


def add_argument(p: argparse.ArgumentParser) -> None:
    p.add_argument("--result", type=path, help="also write the JSON result to this file (read it instead of the output)")


def clear(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def parse(p: argparse.ArgumentParser, argv: list[str] | None) -> argparse.Namespace:
    """Remove an earlier result file, then parse the arguments. The file goes
    first because argparse exits on a usage error, and an old file left
    behind would be read as this run's answer."""
    early = argparse.ArgumentParser(add_help=False)
    add_argument(early)
    clear(early.parse_known_args(argv)[0].result)
    return p.parse_args(argv)


def emit(obj, path: Path | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
