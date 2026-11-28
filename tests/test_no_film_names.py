"""No film is named in the docs, the changelog or a code comment.

The docs talk about "one 2026 film" or "one test film" and keep the
measurement. A title followed by its year in brackets is how a film gets
cited, so that shape fails here, in every Markdown file, every picture
and every comment of the Python files, end-of-line comments included.
The placeholder "Film (2024)" and
invented fixture names inside test strings are not comments and pass.
"""

import io
import re
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITED = re.compile(r"[A-Z][\w'’!]*(?: [\w'’!]+){0,6} \((?:19|20)\d\d\)")
PLACEHOLDER = re.compile(r"^Film \(\d{4}\)$")


def _tracked(*suffixes: str) -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False).stdout
    files = [ROOT / line for line in out.splitlines() if line.endswith(suffixes)]
    return files or [p for s in suffixes for p in ROOT.rglob(f"*{s}") if ".venv" not in p.parts and ".git" not in p.parts]


def _cited(line: str) -> list[str]:
    return [m.group(0) for m in CITED.finditer(line) if not PLACEHOLDER.match(m.group(0))]


def _comments(source: str) -> list[tuple[int, str]]:
    """Every comment of a Python source with its line, end-of-line ones too."""
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [(t.start[0], t.string) for t in tokens if t.type == tokenize.COMMENT]


def test_a_title_with_its_year_is_found():
    assert _cited("Measured on Harbour Lights (2026), 0.65 s late.")
    assert not _cited("Measured on one 2026 film, 0.65 s late.")
    assert not _cited("## 0.13.8 (2026-11-26)")
    assert not _cited("# Film (2024), original language: en")


def test_a_comment_at_the_end_of_a_code_line_is_read():
    source = 'gap = 650  # as on Harbour Lights (2026)\ntitle = "Lantern Song (2019)"\n'
    assert _comments(source) == [(1, "# as on Harbour Lights (2026)")]
    assert [found for _, text in _comments(source) for found in _cited(text)] == ["Harbour Lights (2026)"]


def test_no_markdown_file_or_picture_cites_a_film():
    hits = [
        f"{p.relative_to(ROOT).as_posix()}:{n}: {found}"
        for p in _tracked(".md", ".svg")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        for found in _cited(line)
    ]
    assert not hits, 'say "one 2026 film" instead of naming it:\n' + "\n".join(hits)


def test_no_code_comment_cites_a_film():
    hits = [
        f"{p.relative_to(ROOT).as_posix()}:{n}: {found}"
        for p in _tracked(".py")
        for n, text in _comments(p.read_text(encoding="utf-8"))
        for found in _cited(text)
    ]
    assert not hits, 'say "one 2026 film" instead of naming it:\n' + "\n".join(hits)
