# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Subtitle file handling: read with encoding detection, parse, write,
pair cues by time overlap, and cut a film into chunks at pauses.

Used as a library by the other scripts and as a small command-line tool:

    uv run srt.py info FILE
    uv run srt.py compare A B
    uv run srt.py fit TIMING OTHER
    uv run srt.py shift IN OUT --ms N
"""

from __future__ import annotations

import argparse
import bisect
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


def is_dash_line(line: str) -> bool:
    """A line that opens a speaker's turn with a dialogue dash ("- Who?")."""
    return strip_tags(line).lstrip().startswith("-")


def dash_lines(lines: list[str]) -> int:
    return sum(1 for ln in lines if is_dash_line(ln))


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


# --- fit: does another file line up with the timing file? -----------------

SOUND_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|^\s*-?\s*[A-Z][A-Z0-9 .'-]*:|[♪♫#*\-]", re.M)
LYRIC_HASH_RE = re.compile(r"^\s*#|#\s*$", re.M)
FIT_MIN_COVERED = 0.9  # share of the timing file's spoken cues the other file covers
FIT_MIN_ON_SPEECH = 0.9  # share of the other file's spoken cues that land on timing cues
FIT_MIN_WINDOW = 0.7  # the worst 10-minute window; a lower one means a different cut or drift
FIT_MAX_MEDIAN_MS = 500
FIT_WINDOW_MS = 600_000


def is_sound(cue: Cue) -> bool:
    """A cue with no dialogue in it: only sound descriptions ("[door
    creaks]") or a speaker label, or a song lyric (marked with ♪ or ♫, or
    in older files with a # opening or closing a line). Hearing-impaired
    files are full of the first kind and translations often leave songs
    out, so neither counts when judging whether two files fit."""
    if "♪" in cue.plain or "♫" in cue.plain or LYRIC_HASH_RE.search(cue.plain):
        return True
    return not re.search(r"\w", SOUND_RE.sub("", cue.plain))


def _coverage(a: list[Cue], b: list[Cue]) -> list[float]:
    """For each cue of `a`, the share of its time covered by cues of `b`.
    Both lists sorted by start time."""
    starts = [c.start for c in b]
    longest = max((c.duration for c in b), default=0)
    out = []
    for c in a:
        i = bisect.bisect_left(starts, c.start - longest)
        covered = 0
        while i < len(b) and b[i].start < c.end:
            covered += max(0, min(c.end, b[i].end) - max(c.start, b[i].start))
            i += 1
        out.append(min(covered / c.duration, 1.0))
    return out


def _covered_share(a: list[Cue], b: list[Cue]) -> float:
    cov = _coverage(a, b)
    return sum(x >= 0.5 for x in cov) / max(len(cov), 1)


def _median_start_diff(a: list[Cue], b: list[Cue]) -> int | None:
    """Median of (start of b's partner - start of a) over a's paired cues.
    Only one-to-one pairs of similar length count: when a translation merges
    two lines into one cue, its start says nothing about the second line."""
    pairs = [(c, v) for c, v in zip(a, pair(a, b).values()) if v]
    alike = [(c, v) for c, v in pairs if len(v) == 1 and 0.7 <= v[0].duration / c.duration <= 1.4]
    diffs = sorted(v[0].start - c.start for c, v in (alike if len(alike) >= 20 else pairs))
    return diffs[len(diffs) // 2] if diffs else None


def fit(timing: list[Cue], other: list[Cue], search_ms: int = 60_000) -> dict:
    """Whether `other` (a translation, another edition's subtitles) lines up
    with `timing` once moved by one constant offset.

    Editions of the same film often differ by a fixed lead-in (a studio logo,
    a recap), so the offset is searched over ±search_ms: every 500 ms, then
    every 50 ms around the best. Sound-only cues are left out on both sides,
    and so are differences in how lines are split into cues, which is why
    this measures time covered instead of one-to-one pairs.

    `fits` needs: at least FIT_MIN_COVERED of the timing file's spoken cues
    covered by `other`, at least FIT_MIN_ON_SPEECH of `other`'s spoken cues
    landing on timing cues, no 10-minute window below FIT_MIN_WINDOW (a
    different cut or a frame-rate drift), and a median start difference
    within FIT_MAX_MEDIAN_MS after the shift."""
    t = [c for c in timing if not is_sound(c)]
    o = [c for c in other if not is_sound(c)]
    if not t or not o:
        return {"fits": False, "offset_ms": 0, "reason": "no spoken cues in one of the files"}

    def score(ms: int) -> float:
        return _covered_share(t, shift(o, ms))

    def best_of(candidates) -> int:
        # ties go to the smallest shift, so a file that already fits stays put
        return max(candidates, key=lambda ms: (round(score(ms), 3), -abs(ms)))

    coarse = best_of(range(-search_ms, search_ms + 1, 500))
    offset = best_of(range(coarse - 450, coarse + 451, 50))
    # Coverage is flat across a few hundred ms; centre the shift on the
    # median start difference when that covers as much.
    centred = offset - (_median_start_diff(t, shift(o, offset)) or 0)
    if score(centred) >= score(offset):
        offset = centred
    moved = shift(o, offset)

    cov = _coverage(t, moved)
    covered = sum(x >= 0.5 for x in cov) / len(t)
    on_speech = _covered_share(moved, t)
    windows = []
    for k in range(t[-1].start // FIT_WINDOW_MS + 1):
        idx = [i for i, c in enumerate(t) if k * FIT_WINDOW_MS <= c.start < (k + 1) * FIT_WINDOW_MS]
        if len(idx) >= 20:
            windows.append(round(sum(cov[i] >= 0.5 for i in idx) / len(idx), 3))
    median = _median_start_diff(t, moved)

    reasons = []
    if covered < FIT_MIN_COVERED:
        reasons.append(f"covers {covered:.0%} of the spoken cues (needs {FIT_MIN_COVERED:.0%})")
    if on_speech < FIT_MIN_ON_SPEECH:
        reasons.append(f"{on_speech:.0%} of its cues land on speech (needs {FIT_MIN_ON_SPEECH:.0%})")
    if windows and min(windows) < FIT_MIN_WINDOW:
        reasons.append(f"a 10-minute window covers only {min(windows):.0%}: different cut or drift")
    if median is None:
        reasons.append("no cue pairs to measure the start difference")
    elif abs(median) > FIT_MAX_MEDIAN_MS:
        reasons.append(f"median start difference {median} ms after the shift")
    return {
        "fits": not reasons,
        "offset_ms": offset,
        "covered": round(covered, 3),
        "on_speech": round(on_speech, 3),
        "worst_window": min(windows) if windows else None,
        "median_start_diff_ms": median,
        "spoken_cues": [len(t), len(o)],
        "sound_cues": [len(timing) - len(t), len(other) - len(o)],
        "reason": "; ".join(reasons) or None,
    }


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


def shift(cues: list[Cue], ms: int) -> list[Cue]:
    """The same cues moved by ms (negative is earlier), never before 0:00.
    Timestamps are rewritten in the standard form."""
    out = []
    for c in cues:
        start, end = max(c.start + ms, 0), max(c.end + ms, 0)
        out.append(Cue(n=c.n, start=start, end=end, ts=f"{fmt_ms(start)} --> {fmt_ms(end)}", lines=list(c.lines)))
    return out


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


def _cmd_fit(a) -> None:
    timing, _ = parse(a.timing)
    other, _ = parse(a.other)
    result.emit({"timing": str(a.timing), "other": str(a.other), **fit(timing, other)}, a.result)


def _cmd_shift(a) -> None:
    cues, _ = parse(a.src)
    if not cues:
        raise SystemExit(f"no cues found in {a.src}")
    write(a.dest, shift(cues, a.ms))
    result.emit({"file": str(a.dest), "cues": len(cues), "shifted_ms": a.ms}, a.result)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info", help="encoding, cue count, length and a text sample")
    s.add_argument("file", type=result.path)
    s.set_defaults(func=_cmd_info)
    s = sub.add_parser("compare", help="timestamp match and time offset between two files")
    s.add_argument("a", type=result.path)
    s.add_argument("b", type=result.path)
    s.set_defaults(func=_cmd_compare)
    s = sub.add_parser("fit", help="whether OTHER lines up with TIMING after one constant shift")
    s.add_argument("timing", type=result.path)
    s.add_argument("other", type=result.path)
    s.set_defaults(func=_cmd_fit)
    s = sub.add_parser("shift", help="move every cue by the same number of ms")
    s.add_argument("src", type=result.path)
    s.add_argument("dest", type=result.path)
    s.add_argument("--ms", type=int, required=True, help="negative moves the cues earlier")
    s.set_defaults(func=_cmd_shift)
    result.add_argument(p)
    a = result.parse(p, argv)
    a.func(a)


if __name__ == "__main__":
    main()
