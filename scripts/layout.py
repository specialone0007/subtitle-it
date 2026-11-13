"""How each checked Turkish cue is shown on screen: at most two lines of at
most 42 characters, and in a cue with two speakers one line per speaker.

Used by `assemble.py check`, which lays out every cue after the other
checks and writes the result as the draft. Translation and the checks stay
cue for cue with the timing file; only this last step may change the
layout:

- A cue whose lines are too long or too many is rewrapped into two lines
  when its text fits in them. So is a two-line cue broken where Turkish
  reads badly (`turkish.bad_break`), when the rewrap breaks better.
- A cue with two speakers whose turns do not each fit on one line is split
  at the speaker change into one cue per speaker. The cue's time is shared
  in proportion to each part's length, with the file's usual gap between
  the parts; a part that would get less than MIN_PART_MS gets the minimum,
  taken from the other parts by their length. The split is allowed only
  when every part stays at or under MAX_CPS.

What cannot be laid out this way is a problem for the fix round, which
shortens the text.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import srt  # noqa: E402
import turkish  # noqa: E402

MAX_LINE = 42
MAX_LINES = 2
MAX_CPS = 17.0
MIN_PART_MS = 1000
# The gap between the two parts of a split cue is the file's usual gap
# between cues, never more than this.
MAX_GAP_MS = 250
ITALIC_LINE_RE = re.compile(r"^\s*<i>(?P<inner>(?:(?!</?i>).)*)</i>\s*$", re.I)


@dataclass
class Part:
    start: int
    end: int
    lines: list[str]


def usual_gap(cues: list[srt.Cue]) -> int:
    """The median gap between one cue's end and the next one's start, over
    gaps under a second; capped at MAX_GAP_MS."""
    gaps = sorted(b.start - a.end for a, b in zip(cues, cues[1:]) if 0 <= b.start - a.end < 1000)
    return min(gaps[len(gaps) // 2], MAX_GAP_MS) if gaps else 80


def _width(line: str) -> int:
    return len(srt.strip_tags(line))


def fits(lines: list[str]) -> bool:
    return len(lines) <= MAX_LINES and all(_width(ln) <= MAX_LINE for ln in lines)


def _rewrap(lines: list[str]) -> list[str] | None:
    """The lines as one text wrapped into at most two lines that fit, or None.
    Italics that cover every line whole cover every new line; other tags
    stay where they are in the text."""
    italic = all(ITALIC_LINE_RE.match(ln) for ln in lines)
    parts = [ITALIC_LINE_RE.match(ln).group("inner").strip() if italic else ln.strip() for ln in lines]
    out = srt.wrap(" ".join(p for p in parts if p), MAX_LINE, lang="tr")
    if italic:
        out = [f"<i>{ln}</i>" for ln in out]
    return out if fits(out) else None


def one_line(turn: list[str]) -> str:
    """A speaker's turn on one line, dash and italics kept."""
    if len(turn) == 1:
        return turn[0]
    italic = all(ITALIC_LINE_RE.match(ln) for ln in turn)
    if italic:
        return "<i>" + " ".join(ITALIC_LINE_RE.match(ln).group("inner").strip() for ln in turn) + "</i>"
    return " ".join(ln.strip() for ln in turn)


def share(room: float, sizes: list[int]) -> list[float]:
    """`room` ms shared in proportion to `sizes`, except that a part under
    MIN_PART_MS gets the minimum and the others share what is left by their
    size. So a one-word reply after a long turn gets a second, and the long
    turn keeps as much of its time as it can. Needs room for every part's
    minimum."""
    fixed: set[int] = set()
    while True:
        free = [i for i in range(len(sizes)) if i not in fixed]
        left = room - MIN_PART_MS * len(fixed)
        size = sum(sizes[i] for i in free)
        out = [MIN_PART_MS if i in fixed else left * sizes[i] / size if size else left / len(free) for i in range(len(sizes))]
        low = [i for i in free if out[i] < MIN_PART_MS]
        if not low:
            return out
        fixed.update(low)


def plan(start: int, end: int, lines: list[str], gap: int) -> tuple[list[Part], str | None]:
    """The parts a cue is shown as, and None; or the cue unchanged as one
    part and the reason it cannot be laid out within the limits."""
    as_is = [Part(start, end, list(lines))]
    speakers = srt.turns(lines)
    if len(speakers) < 2:
        if fits(lines) and not (len(lines) == 2 and turkish.bad_break(*lines)):
            return as_is, None
        wrapped = _rewrap(lines)
        if fits(lines):
            # Two lines broken where Turkish reads badly ("senin" / "gibi
            # biri"): the rewrap replaces them only when it breaks better.
            better = wrapped is not None and (len(wrapped) == 1 or not turkish.bad_break(*wrapped))
            return ([Part(start, end, wrapped)] if better else as_is), None
        if wrapped:
            return [Part(start, end, wrapped)], None
        return as_is, f"needs more than {MAX_LINES} lines of {MAX_LINE} characters: shorten it"
    one_each = [one_line(t) for t in speakers]
    if len(speakers) == MAX_LINES and fits(one_each):
        return [Part(start, end, one_each)], None
    texts = [_rewrap([srt.undash(t[0]), *t[1:]]) for t in speakers]
    if any(t is None for t in texts):
        return as_is, f"one speaker's turn needs more than {MAX_LINES} lines of {MAX_LINE} characters: shorten it"
    sizes = [sum(_width(ln) for ln in t) for t in texts]
    room = end - start - gap * (len(texts) - 1)
    total = sum(sizes)
    if room < MIN_PART_MS * len(texts) or total == 0:
        return as_is, (
            f"too short to split into one cue per speaker: each part needs {MIN_PART_MS} ms; "
            f"shorten so each speaker fits on one line of {MAX_LINE}"
        )
    durations = share(room, sizes)
    parts, used = [], 0.0
    for k, (t, ms) in enumerate(zip(texts, durations)):
        a = start + round(used) + gap * k
        used += ms
        b = end if k == len(texts) - 1 else start + round(used) + gap * k
        parts.append(Part(a, b, t))
    for p, size in zip(parts, sizes):
        ms = p.end - p.start
        if ms < MIN_PART_MS or size / (ms / 1000) > MAX_CPS:
            return as_is, (
                f"two speakers do not fit one line each, and split in two a part would last {ms} ms "
                f"at {size / (ms / 1000):.1f} chars/s (needs {MIN_PART_MS} ms and {MAX_CPS:.0f} chars/s at most): "
                f"shorten so each speaker fits on one line of {MAX_LINE}"
            )
    return parts, None
