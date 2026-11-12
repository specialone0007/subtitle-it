# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Find the user's settings folder, and move the old one into place once.

    uv run settings.py folder

The settings folder is ~/.config/subtitle-it: preferences.md,
credentials.json and backups/. Before 0.6.0 the plugin was called
turkish-subtitles and kept them in ~/.config/turkish-subtitles. When the new
folder does not exist and the old one does, the old folder is renamed to the
new name, with everything in it. Nothing inside is opened or read.

`folder` prints {"folder": ..., "moved_from": ...}. `folder` is the one to
use; when the move fails, it is the old folder, and `error` says why. The
OpenSubtitles and audio-hint scripts do the same before they use the
default folder.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402

NAME = "subtitle-it"
OLD_NAME = "turkish-subtitles"


def default_folder() -> Path:
    return Path.home() / ".config" / NAME


def ensure(home: Path) -> dict:
    new = home / ".config" / NAME
    old = home / ".config" / OLD_NAME
    out = {"folder": str(new), "moved_from": None}
    if new.exists() or new.is_symlink() or not old.is_dir():
        return out
    try:
        old.rename(new)
    except OSError as e:
        return {"folder": str(old), "moved_from": None, "error": f"could not rename {old} to {new}: {e.strerror or e}"}
    out["moved_from"] = str(old)
    return out


def ensure_for(config: Path) -> Path:
    """Before a script uses the default settings folder, move the old one
    into place, so a setup command run before any translate run does not
    leave the old folder behind. Returns the folder to use: the old one
    when the move failed, with the reason on stderr, so nothing is written
    into a new folder that would then stop the move for good."""
    if config.expanduser().resolve() != default_folder().resolve():
        return config
    out = ensure(Path.home())
    if "error" in out:
        print(f"{out['error']}; using {out['folder']}", file=sys.stderr)
    return Path(out["folder"])


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("folder")
    result.add_argument(p)
    a = result.parse(p, argv)
    result.emit(ensure(Path.home()), a.result)


if __name__ == "__main__":
    main()
