"""Write the GitHub release notes for one version from CHANGELOG.md.

Used by .github/workflows/release.yml, and by hand to rewrite older releases:

    python .github/scripts/release_notes.py 0.13.5 --previous-tag v0.13.4

Every release has the same shape: the changelog entry's opening plain-words
paragraphs as they are, the technical bullets folded into a "Technical notes"
block, then how to update and links to the changelog entry and the compare view.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = "specialone0007/subtitle-it"
UPDATE = (
    "To update, run `claude plugin marketplace update subtitle-it` and then "
    "`claude plugin update subtitle-it@subtitle-it`, and start a new Claude Code session."
)


def section(changelog: str, version: str) -> tuple[str, list[str]]:
    """Return the heading and body lines of one version's changelog entry."""
    lines = changelog.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^## {re.escape(version)}(\s|$)", line):
            start = i
            break
    if start is None:
        raise SystemExit(f"CHANGELOG.md has no entry for {version}")
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return lines[start][3:].strip(), lines[start + 1 : end]


def anchor(heading: str) -> str:
    """GitHub's anchor for a Markdown heading."""
    text = re.sub(r"[^\w\- ]", "", heading.lower())
    return text.replace(" ", "-")


def unwrap(text: str) -> str:
    """Join hard-wrapped lines, since a release page shows every line break.

    A line that starts a list item ("- ", indented or not) starts a new line;
    any other line continues the one before it. Blank lines stay.
    """
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip() or not out or not out[-1].strip() or re.match(r"^\s*- ", line):
            out.append(line.rstrip())
        else:
            out[-1] += " " + line.strip()
    return "\n".join(out)


def notes(changelog: str, version: str, previous_tag: str | None = None, repo: str = REPO) -> str:
    heading, body = section(changelog, version)
    first_bullet = next((i for i, line in enumerate(body) if line.startswith("- ")), len(body))
    opening = unwrap("\n".join(body[:first_bullet]).strip())
    technical = unwrap("\n".join(body[first_bullet:]).strip())
    tag = f"v{version}"
    parts = []
    if opening:
        parts.append(opening)
    if technical:
        parts.append(f"<details><summary>Technical notes</summary>\n\n{technical}\n\n</details>")
    links = [f"[Changelog](https://github.com/{repo}/blob/{tag}/CHANGELOG.md#{anchor(heading)})"]
    if previous_tag:
        links.append(f"[Changes since {previous_tag}](https://github.com/{repo}/compare/{previous_tag}...{tag})")
    parts.append(f"{UPDATE} {' · '.join(links)}")
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the version, without the leading v (0.13.5)")
    parser.add_argument("--previous-tag", help="the tag to compare against (v0.13.4); no compare link without it")
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args(argv)
    text = Path(args.changelog).read_text(encoding="utf-8")
    # Always UTF-8: a Windows console redirected to a file would use cp1252,
    # which cannot hold Turkish letters or the link separator.
    sys.stdout.buffer.write(notes(text, args.version, args.previous_tag, args.repo).encode("utf-8"))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
