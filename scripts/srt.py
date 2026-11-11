# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Subtitle file handling: read with encoding detection, parse, write,
pair cues by time overlap, and cut a film into chunks at pauses.

Used as a library by the other scripts and as a small command-line tool:

    uv run srt.py info FILE
    uv run srt.py compare A B
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import result

TS_RE = re.compile(
    r"^\s*(\d{1,3}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,3}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")
BOM = "﻿"


@dataclass
class Cue:
    n: int  # 1-based position in the file, not the number written in it
    start: int  # milliseconds
    end: int
    ts: str  # the timestamp line exactly as written, stripped
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def plain(self) -> str:
        """Text without tags or line breaks, for length and speed checks."""
        return strip_tags(" ".join(self.lines)).strip()

    @property
    def duration(self) -> int:
        return max(self.end - self.start, 1)


def strip_tags(s: str) -> str:
    return TAG_RE.sub("", s)


def _ms(h: str, m: str, s: str, frac: str) -> int:
    frac = (frac + "00")[:3]
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac)


def fmt_ms(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# --- reading -------------------------------------------------------------


def decode(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding name). BOMs first, then strict UTF-8, then
    charset-normalizer, then cp1252 as a last resort that never fails."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best), best.encoding
    except ImportError:  # running without uv; fall through
        pass
    return raw.decode("cp1252", errors="replace"), "cp1252"


def parse_text(text: str) -> list[Cue]:
    text = text.replace(BOM, "").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n[ \t]*\n", text.strip()):
        lines = [ln.rstrip() for ln in block.split("\n")]
        # The timestamp line is the anchor; the number line above it is optional.
        for k, ln in enumerate(lines[:3]):
            m = TS_RE.match(ln)
            if m:
                g = m.groups()
                body = [x for x in lines[k + 1 :] if x.strip()]
                cues.append(
                    Cue(
                        n=len(cues) + 1,
                        start=_ms(*g[:4]),
                        end=_ms(*g[4:]),
                        ts=ln.strip(),
                        lines=body,
                    )
                )
                break
    return cues


def parse(path: str | Path) -> tuple[list[Cue], str]:
    """Parse a subtitle file. Returns (cues, detected encoding)."""
    text, enc = decode(Path(path).read_bytes())
    return parse_text(text), enc


# --- writing -------------------------------------------------------------


def render(cues: list[Cue], texts: dict[int, list[str]] | None = None) -> str:
    out = []
    for c in cues:
        lines = texts[c.n] if texts is not None else c.lines
        out.append(f"{c.n}\n{c.ts}\n" + "\n".join(lines) + "\n")
    return "\n".join(out)


def write(path: str | Path, cues: list[Cue], texts: dict[int, list[str]] | None = None) -> None:
    """Write UTF-8 without BOM, CRLF line endings."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(render(cues, texts))


# --- block files (what translators read and write) -----------------------


def read_blocks(path: str | Path) -> tuple[dict[int, list[str]], list[str]]:
    """Read a 'number, then lines' file. Returns ({n: lines}, problems)."""
    text = Path(path).read_text(encoding="utf-8-sig").replace(BOM, "")
    text = text.replace("\r\n", "\n")
    out: dict[int, list[str]] = {}
    problems: list[str] = []
    name = Path(path).name
    for block in re.split(r"\n[ \t]*\n", text.strip()):
        lines = [ln.rstrip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        head = lines[0].strip().lstrip("#")
        if not head.isdigit():
            problems.append(f"{name}: block without a cue number: {lines[0][:40]!r}")
            continue
        n = int(head)
        if n in out:
            problems.append(f"{name}: cue {n} appears twice")
        out[n] = lines[1:]
    return out, problems


# --- pairing by time -----------------------------------------------------


def pair(timing: list[Cue], other: list[Cue], min_share: float = 0.3) -> dict[int, list[Cue]]:
    """For each timing cue, the cues of `other` that overlap it in time.

    A cue of `other` counts when the overlap covers at least `min_share` of
    either cue. Each `other` cue goes to the timing cue it overlaps most, so
    no text is used twice. Both lists must be sorted by start time."""
    result: dict[int, list[Cue]] = {c.n: [] for c in timing}
    j0 = 0
    for o in other:
        best, best_ov = None, 0
        while j0 < len(timing) and timing[j0].end <= o.start:
            j0 += 1
        j = max(j0 - 1, 0)
        while j < len(timing) and timing[j].start < o.end:
            t = timing[j]
            ov = min(t.end, o.end) - max(t.start, o.start)
            if ov > best_ov:
                best, best_ov = t, ov
            j += 1
        if best and (best_ov >= min_share * o.duration or best_ov >= min_share * best.duration):
            result[best.n].append(o)
    return result


def offset_check(timing: list[Cue], other: list[Cue]) -> dict:
    """How well two files line up: share of timing cues with a partner and
    the median start difference in ms. A large median means a shifted file."""
    paired = pair(timing, other)
    diffs = sorted(v[0].start - timing[n - 1].start for n, v in paired.items() if v)
    share = len(diffs) / max(len(timing), 1)
    median = diffs[len(diffs) // 2] if diffs else None
    return {"paired_share": round(share, 3), "median_start_diff_ms": median}


# --- chunking ------------------------------------------------------------


def chunk(cues: list[Cue], target: int = 250, window: int = 40) -> list[tuple[int, int]]:
    """Cut into chunks of about `target` cues. Each cut moves to the longest
    gap between cues within `window` cues of the nominal point, which is
    usually a pause of several seconds at a scene change; ties go to the
    point nearest the nominal one. Returns (first n, last n), inclusive."""
    total = len(cues)
    if total == 0:
        return []
    parts = max(1, round(total / target))
    size = total / parts
    cuts = []
    for k in range(1, parts):
        nominal = round(k * size)
        lo = max(nominal - window, (cuts[-1] if cuts else 0) + 20, 1)
        hi = min(nominal + window, total - 20)
        if lo >= hi:
            cuts.append(nominal)
            continue
        # gap before index i (0-based) = cues[i].start - cues[i-1].end; the next chunk starts at i
        best = max(range(lo, hi), key=lambda i: (cues[i].start - cues[i - 1].end, -abs(i - nominal)))
        cuts.append(best)
    bounds = [0, *cuts, total]
    return [(cues[a].n, cues[b - 1].n) for a, b in zip(bounds, bounds[1:])]


# --- command line --------------------------------------------------------


def _cmd_info(a) -> None:
    cues, enc = parse(a.file)
    sample = [c.text for c in cues[len(cues) // 3 : len(cues) // 3 + 5]]
    result.emit(
        {
            "file": str(a.file),
            "encoding": enc,
            "cues": len(cues),
            "first_start": fmt_ms(cues[0].start) if cues else None,
            "last_end": fmt_ms(cues[-1].end) if cues else None,
            "last_end_ms": cues[-1].end if cues else None,
            "sample": sample,
        },
        a.result,
    )


def _cmd_compare(a) -> None:
    x, _ = parse(a.a)
    y, _ = parse(a.b)
    mism = [(c.n, c.ts, d.ts) for c, d in zip(x, y) if c.ts != d.ts]
    result.emit({"cues": [len(x), len(y)], "timestamp_mismatches": len(mism), "first": mism[:5], **offset_check(x, y)}, a.result)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info", help="encoding, cue count, length and a text sample")
    s.add_argument("file", type=Path)
    s.set_defaults(func=_cmd_info)
    s = sub.add_parser("compare", help="timestamp match and time offset between two files")
    s.add_argument("a", type=Path)
    s.add_argument("b", type=Path)
    s.set_defaults(func=_cmd_compare)
    result.add_argument(p)
    a = result.parse(p, argv)
    a.func(a)


if __name__ == "__main__":
    main()
