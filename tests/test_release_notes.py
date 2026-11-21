"""The release notes helper in .github/scripts, which the release workflow runs."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_notes", ROOT / ".github" / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## 1.2.0 (2026-11-21)

Plain words
first.

A second plain paragraph.

- `tool.py run` does the technical thing,
  over two lines.
- Another bullet.

## 1.1.0 (2026-11-20)

- Only bullets here.
"""


def test_opening_then_folded_bullets_then_links():
    text = release_notes.notes(CHANGELOG, "1.2.0", "v1.1.0", repo="o/r")
    opening = text.split("\n\n<details>")[0]
    details = text[text.index("<details>") : text.index("</details>")]
    footer = text[text.index("</details>") :]
    assert opening == "Plain words first.\n\nA second plain paragraph."
    assert "<summary>Technical notes</summary>" in details
    assert "- `tool.py run` does the technical thing, over two lines.\n- Another bullet." in details
    assert "## 1.1.0" not in text
    assert "claude plugin update subtitle-it@subtitle-it" in footer
    assert "https://github.com/o/r/blob/v1.2.0/CHANGELOG.md#120-2026-11-21" in footer
    assert "https://github.com/o/r/compare/v1.1.0...v1.2.0" in footer
    assert text.endswith(")\n")


def test_unwrap_keeps_nested_items_and_blank_lines():
    text = "- one\n  more\n  - nested\n    tail\n\nPara\ngraph"
    assert release_notes.unwrap(text) == "- one more\n  - nested tail\n\nPara graph"


def test_no_compare_link_without_previous_tag_and_no_empty_parts():
    text = release_notes.notes(CHANGELOG, "1.1.0", repo="o/r")
    assert text.startswith("<details><summary>Technical notes</summary>\n\n- Only bullets here.")
    assert "/compare/" not in text


def test_missing_version_fails():
    try:
        release_notes.notes(CHANGELOG, "9.9.9")
    except SystemExit as e:
        assert "9.9.9" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_every_released_changelog_entry_opens_with_plain_words():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Every version from 0.10.0, the first with a GitHub release, has one.
    versions = re.findall(r"^## (\d+)\.(\d+)\.(\d+)", changelog, re.M)
    released = [".".join(v) for v in versions if tuple(map(int, v)) >= (0, 10, 0)]
    assert "0.10.0" in released
    for version in released:
        text = release_notes.notes(changelog, version)
        assert not text.startswith("<details>"), version
