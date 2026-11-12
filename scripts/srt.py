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


def turns(lines: list[str]) -> list[list[str]]:
    """A cue's lines grouped by speaker: a dash line starts a turn, and a
    line without a dash continues the turn above it. A cue with fewer than
    two dash lines is one turn."""
    if dash_lines(lines) < 2:
        return [list(lines)] if lines else []
    out: list[list[str]] = []
    for ln in lines:
        if is_dash_line(ln) or not out:
            out.append([])
        out[-1].append(ln)
    return out


def wrap(text: str, width: int = 42) -> list[str]:
    """One line when it fits in `width` characters, else two. The break goes
    after a sentence end, then after a comma, as long as both lines fit;
    otherwise at the space nearest the middle. Tags do not count towards
    the width, and no break falls inside one."""
    size = len(strip_tags(text))
    inside = {i for m in TAG_RE.finditer(text) for i in range(m.start(), m.end())}
    spaces = [i for i, ch in enumerate(text) if ch == " " and i not in inside]
    if size <= width or not spaces:
        return [text]
    mid = size / 2

    def left(i: int) -> int:
        return len(strip_tags(text[:i]))

    fits = [i for i in spaces if left(i) <= width and size - left(i) - 1 <= width]
    for marks in (".!?…", ",;:"):
        after = [i for i in fits if strip_tags(text[:i]).endswith(tuple(marks))]
        if after:
            cut = min(after, key=lambda i: abs(left(i) - mid))
            break
    else:
        cut = min(spaces, key=lambda i: abs(left(i) - mid))
    return [text[:cut], text[cut + 1 :]]


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


# --- hearing-impaired text: sound descriptions and speaker labels ---------

# A sound description in square brackets: "[door creaks]", "[People
# shouting]". In remove mode it goes from every file.
SQUARE_RE = re.compile(r"\[[^\]]*\]")
# One in parentheses: "(sighs)". Plain files use parentheses for speech too
# ("I said (and I mean it) no."), so these go only from a hearing-impaired
# file, and even there a parenthesis that reads as speech stays: see
# _paren_is_speech.
PAREN_RE = re.compile(r"\([^)]*\)")
# Tags and a dialogue dash in front of a line: "<i>- ".
_LEAD_RE = re.compile(r"^(?P<tags>(?:\s*(?:<[^>]+>|\{\\[^}]*\}))*)\s*(?P<dash>-\s*)?")
# A speaker label with a colon: "SANDRA:", "[SANDRA]:", "(SANDRA):",
# "SANDRA (whispering):" or "[Sandra]:". Without brackets the name must be in
# capitals, so "Rule one: never lie" stays dialogue. Capitals before a colon
# are a label only when they look like a name: see _is_name.
_CAPS_LABEL_RE = re.compile(r"[\[(]?(?P<name>[A-ZÀ-ÝĞİŞ][A-ZÀ-ÝĞİŞ0-9 .'\-]{1,30}?)[\])]?(?:\s*\([^)]*\))?\s*:(?:\s+|$)")
_NAME = r"[A-ZÀ-ÝĞİŞ][\w'.\-]*(?:\s+[A-ZÀ-ÝĞİŞ][\w'.\-]*){0,2}"
# A bracketed name in front of speech, with or without a colon: "[Sandra] Hi.",
# "[1. Man] Hi.", "[Sandra]: Hi.". Each word starts with a capital; a bracket
# in capitals with no colon ("[DOOR SLAMS] Hi.") is a sound.
_BRACKET_LABEL_RE = re.compile(r"\[(?:\d+\.\s*)?(?P<name>" + _NAME + r"(?:\s+\d{1,2})?)\]\s*:?\s*")
# Capitals before a colon that name no speaker: "OK: let's go.", "WARNING:
# HIGH VOLTAGE". Digits rule out "DAY 3:" and "BÖLÜM 1:" on their own.
NOT_LABELS = {
    "ACT",
    "ATTENTION",
    "BREAKING",
    "BÖLÜM",
    "CAUTION",
    "CHAPTER",
    "DANGER",
    "DAY",
    "DİKKAT",
    "EPISODE",
    "EXIT",
    "FYI",
    "GÜN",
    "KISIM",
    "LEVEL",
    "LOCATION",
    "NB",
    "NOT",
    "NOTE",
    "NOTICE",
    "OK",
    "OKAY",
    "P.S",
    "PART",
    "PHASE",
    "PS",
    "RE",
    "ROUND",
    "RULE",
    "SAHNE",
    "SCENE",
    "STEP",
    "SUBJECT",
    "TAMAM",
    "TEHLİKE",
    "TITLE",
    "UPDATE",
    "UYARI",
    "WARNING",
}
# One word of a name: letters, Turkish ones included, with ' . - inside.
_NAME_WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|['.\-])*")
# Words that sound descriptions in title case start with ("[Laughs] Yes.",
# "[Gunshot] Get down!"): such a bracket is a sound, not a speaker. A bracket
# whose first word is not here and that names no one, such as "[Rire] Quoi ?"
# in another language, is still read as a name.
SOUND_WORDS = {
    "applause",
    "background",
    "barking",
    "barks",
    "beep",
    "beeping",
    "beeps",
    "bell",
    "bells",
    "breathes",
    "breathing",
    "buzzing",
    "car",
    "chatter",
    "cheering",
    "cheers",
    "chuckle",
    "chuckles",
    "chuckling",
    "clattering",
    "clears",
    "coughing",
    "coughs",
    "crash",
    "crashes",
    "crowd",
    "crying",
    "distant",
    "dog",
    "dogs",
    "door",
    "engine",
    "exhales",
    "explosion",
    "explosions",
    "faint",
    "footsteps",
    "gasping",
    "gasps",
    "giggles",
    "giggling",
    "glass",
    "groan",
    "groans",
    "growls",
    "grunts",
    "gunfire",
    "gunshot",
    "gunshots",
    "heavy",
    "horn",
    "humming",
    "hums",
    "inaudible",
    "indistinct",
    "inhales",
    "knock",
    "knocking",
    "knocks",
    "laugh",
    "laughing",
    "laughs",
    "laughter",
    "loud",
    "moans",
    "muffled",
    "music",
    "over",
    "panting",
    "phone",
    "quietly",
    "radio",
    "rain",
    "ringing",
    "rings",
    "sarcastically",
    "scoff",
    "scoffs",
    "screaming",
    "screams",
    "shouting",
    "sigh",
    "sighs",
    "silence",
    "singing",
    "siren",
    "sirens",
    "sniffles",
    "sniffs",
    "snoring",
    "sobbing",
    "sobs",
    "softly",
    "static",
    "thud",
    "thunder",
    "tires",
    "whimpers",
    "whispering",
    "whispers",
    "whistles",
    "whistling",
    "wind",
    "yawns",
    "yelling",
}


@dataclass
class Cleaned:
    text: str  # the line without sound descriptions and label; "" when nothing is left
    label: str | None  # the speaker label's name as written, when the line had one
    found: bool  # the line had a sound description or a label


def _is_name(name: str) -> bool:
    """Capitals before a colon read as a speaker's name: letters only, at
    most 3 words, no digits, and not a word such as OK or WARNING."""
    words = name.split()
    return (
        1 <= len(words) <= 3 and all(_NAME_WORD_RE.fullmatch(w) for w in words) and words[0].rstrip(".").upper() not in NOT_LABELS
    )


def _paren_is_speech(rest: str, m: re.Match) -> bool:
    """A parenthesis that is speech, not a sound: it ends in ? or !
    ("(Are you there?)"), or it holds a sentence of 3 words or more with
    words on both sides of it on the line ("I said (and I mean it) no.")."""
    inner = strip_tags(m.group(0)[1:-1]).strip()
    if re.search(r"[?!][\"'”»…]*$", inner):
        return True
    before, after = strip_tags(rest[: m.start()]), strip_tags(rest[m.end() :])
    return len(inner.split()) >= 3 and bool(re.search(r"\w", before)) and bool(re.search(r"\w", after))


def paren_descriptions(line: str) -> list[str]:
    """The descriptions in parentheses that a hearing-impaired file loses."""
    plain = strip_tags(line)
    return [m.group(0) for m in PAREN_RE.finditer(plain) if not _paren_is_speech(plain, m)]


def _bracket_name(m: re.Match) -> str | None:
    words = m.group("name").split()
    # A bracket in capitals with no colon is a sound: "[IN SPANISH] Hola.",
    # "[BANG] Get down!". "[SANDRA]: Hi." with its colon is still a label.
    if ":" not in m.group(0) and not any(ch.islower() for ch in m.group("name")):
        return None
    if words[0].casefold() in SOUND_WORDS or any(w.casefold().endswith("ing") and len(w) > 5 for w in words):
        return None
    return m.group("name")


def undash(line: str) -> str:
    """The line without its dialogue dash; tags in front of it stay."""
    lead = _LEAD_RE.match(line)
    return lead.group("tags") + line[lead.end() :] if lead.group("dash") else line


def clean_line(line: str, hi: bool = True) -> Cleaned:
    """One subtitle line without its hearing-impaired parts. `hi` says
    whether the line's file is a hearing-impaired one.

    In every file: descriptions in square brackets anywhere in the line, a
    bracketed name in front of speech ("[Sandra] Hi.", "[Guard 2] Hi.") and
    music notes with no words. Only in a hearing-impaired file: a speaker
    label in capitals ("- SANDRA: Hi." becomes "- Hi.") and descriptions in
    parentheses that are not speech. In a plain file a label in capitals
    is still returned as the speaker hint, and its text stays. Capitals
    before a colon that do not look like a name ("OK:", "DAY 3:") are text
    in either file. Tags and the dialogue dash stay. A line with no word
    left becomes "". Song lines with words keep their notes."""
    lead = _LEAD_RE.match(line)
    head = lead.group("tags") + (lead.group("dash") or "")
    rest = line[lead.end() :]
    label = None
    found = False
    m = _CAPS_LABEL_RE.match(rest)
    if m and _is_name(m.group("name").strip()):
        label = m.group("name").strip()
        if hi or rest.startswith("["):
            rest, found = rest[m.end() :], True
    else:
        m = _BRACKET_LABEL_RE.match(rest)
        name = _bracket_name(m) if m else None
        if name and (rest[m.end() :].strip() or ":" in m.group(0)):
            label, rest, found = name, rest[m.end() :], True
    # A mark where each description was, so only the space it leaves is
    # tidied: "Yes [laughs]." becomes "Yes.", while French "Quoi ?" keeps
    # its space.
    if SQUARE_RE.search(rest):
        rest, found = SQUARE_RE.sub("\x00", rest), True
    if hi:
        drop = [m for m in PAREN_RE.finditer(rest) if not _paren_is_speech(rest, m)]
        for m in reversed(drop):
            rest, found = rest[: m.start()] + "\x00" + rest[m.end() :], True
    if not re.search(r"\w", strip_tags(rest)) and re.search(r"[♪♫]", rest):
        rest, found = "", True  # music playing, no words: a sound description too
    if not found:
        return Cleaned(line, label, False)
    if lead.group("dash"):
        head = lead.group("tags") + "- "
    text = re.sub(r"(?:\s*\x00)+\s*(?=[.,!?;:…])", "", head + rest.lstrip())
    text = re.sub(r"(?:\s*\x00)+\s*", " ", text)
    text = re.sub(r"<(\w+)[^>]*>\s*</\1>", "", text)
    # No space left between an opening tag or the dash and the words.
    text = re.sub(r"^((?:\s*<[^/>][^>]*>)*\s*(?:-\s)?)\s+", r"\1", text).strip()
    if not re.search(r"\w", strip_tags(text)):
        text = ""
    return Cleaned(text, label, True)


def strip_hi(lines: list[str], hi: bool = True) -> tuple[list[str], list[str], bool]:
    """A cue's lines without sound descriptions and speaker labels, as
    clean_line removes them for a file that is (`hi`) or is not a
    hearing-impaired one. Returns
    (lines, label names in order, whether anything was found). Lines left
    empty are dropped. When a two-speaker cue keeps one speaker's line only,
    that line loses its dialogue dash: one speaker gets none."""
    out, names, found = [], [], False
    for ln in lines:
        c = clean_line(ln, hi)
        found |= c.found
        if c.label:
            names.append(c.label)
        if c.text:
            out.append(c.text)
    if dash_lines(lines) >= 2 and dash_lines(out) == 1:
        out = [undash(ln) for ln in out]
    return out, names, found


def has_hi(lines: list[str]) -> bool:
    """The lines hold a sound description or a speaker label, read the way
    a hearing-impaired file's are."""
    return any(clean_line(ln, hi=True).found for ln in lines)


HI_MIN_SHARE = 0.03


def hearing_impaired(cues: list[Cue]) -> dict:
    """Whether a file is a hearing-impaired one, read from its text: at
    least HI_MIN_SHARE of its cues hold a sound description or a speaker
    label. Plain files have a handful at most (a note in brackets, a sign);
    hearing-impaired ones have them every few cues. 3% is 45 cues in a film
    of 1,500."""
    marked = sum(1 for c in cues if has_hi(c.lines))
    share = marked / max(len(cues), 1)
    return {"hearing_impaired": share >= HI_MIN_SHARE, "cues_with_tags_or_labels": marked, "share": round(share, 3)}


# --- fit: does another file line up with the timing file? -----------------

LYRIC_HASH_RE = re.compile(r"^\s*#|#\s*$", re.M)
FIT_MIN_COVERED = 0.8  # share of the timing file's spoken cues the other file covers
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
    return not strip_hi(cue.lines)[0]


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
        reasons.append(f"covers {covered:.1%} of the spoken cues, needs {FIT_MIN_COVERED:.1%}")
    if on_speech < FIT_MIN_ON_SPEECH:
        reasons.append(f"{on_speech:.1%} of its cues land on speech, needs {FIT_MIN_ON_SPEECH:.1%}")
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
