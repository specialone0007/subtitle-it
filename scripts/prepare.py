# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Build a film's work folder and cut it into chunks for the translators.

    uv run prepare.py build  --work W --timing T [--source S] [--en E] [--keep-bible-check] [--hi remove|keep]
                             [--track LANG=PATH ...] [--forced-track LANG=PATH ...] [--timing-language L]
                             [--shift-ms N | --screen W/screen/readings.json]
    uv run prepare.py songs  --work W [--mode story|skip|all]
    uv run prepare.py chunks --work W [--target 250]

`build` writes W/timing.srt (UTF-8 copy of the timing file, timestamps kept
character for character), W/cues.json (per cue: timing, source text, English
cross-check, speaker label) and W/speakers.json (labels found in the text).
`chunks` writes W/chunks/chunk_NN.txt, the files translators read. It can
run again while an agent reads them: each file is replaced whole.

Hearing-impaired files describe sounds ("[door slams]") and name speakers
("SANDRA:", "[Sandra] Hi."). With `--hi remove`, the default, `build` takes
both out of every text before any agent sees it: the labels become speaker
hints in speakers.json, and a cue left with no words is marked
`sound_only` in cues.json, gets no chunk line and is not delivered.
`--hi keep` leaves the text as it is.

Two more kinds of cue are left out the same way, following the Netflix
Turkish style guide. A cue that is only a bare sound the audience hears
("Oh.", "Hmm?", "Uh, um...") is marked `left_out: "sound"` by `build`; a
yes or no said as a sound ("Uh-huh") right after a question stays. A cue
whose words are all song lyrics is marked `song`; `songs` then marks the
songs that are not translated `left_out: "song"`, from the bible writer's
songs.json and the preferences' "Songs".

`--keep-bible-check` is for a rebuild that only shifts the times of the same
cues: the bible check's files stay, since its answers cite cue numbers.
`--shift-ms N` is that rebuild: the files given are the earlier build's,
moved by N ms. The on-screen entries are moved by N too rather than found
again, so every cue keeps its number. N always counts from the files of
the build without --shift-ms: each entry keeps the times that build found
(`found`), so running the same rebuild twice moves it once.

On-screen text. A title card, a sign or a dedication is often missing from
the timing file: English tracks tend to leave it to the picture, while a
French or Spanish track subtitles it. `--track LANG=PATH` (any number) names
other subtitle files of the same film; `--forced-track LANG=PATH` names a
forced track of the same video, which holds only on-screen text and
foreign-language lines. `build` lines each `--track` up with the timing file
(srt.fit; one that does not fit is left out) and takes a forced track as it
is. A line that falls where the timing file shows nothing becomes a new cue,
marked `on_screen` in cues.json, when tracks in two languages show it at the
same time, or a forced track shows it. One language alone is recorded, not
added: a French track also subtitles shouts the English one leaves out.
With six or more other languages two are not enough: a line needs three
quarters of them (SHARE), since some tracks also subtitle shop signs in the
background; one shown by fewer is left out as too few languages.
Subtitle credits ("Subtítulos: ...") are never added.

Every text found is a row of W/on_screen.json (empty when no track is
given): its time, its text per language, which tracks show it, and its
state: `cue` (added; `n` is its cue number) or `left_out`, with a reason
(ON_SCREEN_REASONS). A cue that is on-screen text is never marked a song, a
sound or a bare sound. `--timing-language` names the timing file's language,
so build.json can say which other languages the tracks hold
(`other_languages`); `screen.py frames` reads it.

The picture. For a video, `screen.py frames` saves frames from the two ends
of the film and around the entries the tracks leave unsure (one language
alone, or too few languages), a reader agent reads them, and `screen.py
collect` writes W/screen/readings.json. `build --screen` that file is the
same build again, with what the picture showed: an entry a story reading
names (the reader gives its id; time alone never joins them) is added when
it was unsure or left out as one language only, too few languages, a
subtitle credit or a song line; an unsure entry the picture did not show
is left out, `not confirmed by the picture`
when its frames were read, `not checked by the picture` otherwise; a story
text no entry holds is a new entry (`evidence: picture`), added when no
timing cue covers it and there is room. Its `found` is the span the frames
saw; it is shown until the next saved frame (`shown_end`, at least
PICTURE_HOLD_MS long and at most PICTURE_HOLD_MS past its last frame), but
never into the next item it would push out. Every picture entry gets a cue
number, the ones left out (no room, or under a timing line) too: their rows
are left out and not delivered. `--screen` keeps W/screen/. In a
`--shift-ms` rebuild a picture entry keeps its times, which are the video's
(`found`), and its number, and each is judged again against the shifted
cues next to it in time, whatever their numbers: one they cover is left
out, one with room is shown at its own time, even before a cue with a lower
number, and one with no room at its own time is left out (NO_ROOM_SHIFT).
So its number can sit out of time order; whatever is shown or measured in
time reads the cues in `time_order`.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import shutil
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import srt  # noqa: E402

# Labels that name no one in particular: kept out of the hints. The label
# forms themselves ("SANDRA:", "[Sandra] Hi.") are read by srt.clean_line.
NOT_NAMES = {"MAN", "WOMAN", "BOTH", "ALL", "MUSIC", "LAUGHS", "SIGHS", "NARRATOR", "CROWD", "VOICE", "TV", "RADIO"}
HI_MODES = ("remove", "keep")

# --- on-screen text from other tracks ---------------------------------------

# A track's line counts as missing from the timing file when timing cues
# cover less than this share of its time.
GAP_MAX_COVERED = 0.2
# Two tracks' lines show the same thing when they overlap by at least this
# share of the shorter one.
SAME_LINE_SHARE = 0.5
# An added cue squeezed between two timing cues must still last this long.
ON_SCREEN_MIN_MS = 700
# A story text only the picture shows stays up after its last frame until
# the next saved frame, this long at most, and lasts this long at least
# (picture_shown_end): frames are 1.5 s apart at the two ends of the film.
PICTURE_HOLD_MS = 1500
# A subtitler's own credit or a site's advert, in the languages tracks come in.
CREDIT_RE = re.compile(
    r"subt[ií]t|sous-titr|untertitel|sottotitol|legendas|altyaz|napisy|traduc|translat|übersetz|azpititul|ikuskatzaile"
    r"|\bsync|opensubtitles|www\.|https?:|\.(?:com|org|net)\b",
    re.IGNORECASE,
)
# With many other languages, a line counts as story text only when most of
# them show it: text the film wants read is subtitled by nearly every track,
# a shop sign in the background by some. In Love of Your Life (31 other
# languages) the 18 story texts were shown by 27 to 31 of them and the 19
# background signs and credits by 5 to 21, so three quarters splits them.
# Below SHARE_FROM other languages a share says little and two still prove.
SHARE_FROM = 6
SHARE = 0.75
# Every on-screen text found is a row of this file in the work folder.
ON_SCREEN_FILE = "on_screen.json"
# Why an entry is left out, in on_screen.json.
ONE_LANGUAGE = "one language only"
FEW_LANGUAGES = "too few languages"
NO_ROOM = "no room"
CREDIT = "looks like a subtitle credit"
SONG_LINE = "looks like a song line"
DURING_SONG = "shown during a song or a sound"
# Unsure entries (see `screen.py frames`) once the picture was read.
NOT_CONFIRMED = "not confirmed by the picture"
NOT_CHECKED = "not checked by the picture"
# A picture entry a sync rebuild left with no room. Its row in cues.json is
# left out with this reason, so `assemble.py` knows it (LEFT_OUT_NOTES).
NO_ROOM_SHIFT = "no room after the timing shift"
# A story text only the picture shows, under a line of the timing file.
UNDER_TIMING = "under a line of the timing file"
ON_SCREEN_REASONS = (
    ONE_LANGUAGE,
    FEW_LANGUAGES,
    NO_ROOM,
    CREDIT,
    SONG_LINE,
    DURING_SONG,
    NOT_CONFIRMED,
    NOT_CHECKED,
    NO_ROOM_SHIFT,
    UNDER_TIMING,
)
# What the reader agent says a frame shows. A story reading is one the film
# wants read, of a kind that is not credits, a logo or the background.
READER_KINDS = (
    "title card",
    "caption",
    "sign",
    "text message",
    "letter",
    "dedication",
    "closing text",
    "credits",
    "logo",
    "background",
)
NOT_STORY_KINDS = ("credits", "logo", "background")
PICTURE = "picture"
FRAMES_FILE = Path("screen") / "frames.json"
# The speaker hint of a cue that is text on screen, in the chunks and in the
# review and listen part files.
ON_SCREEN_MARK = "on-screen text"


def track_arg(text: str) -> tuple[str, Path]:
    """`fr=path/to/file.srt` for --track and --forced-track."""
    lang, sep, path = text.partition("=")
    lang = lang.strip().lower()
    # OpenSubtitles keeps a region on some codes: pt-BR, zh-CN.
    if not sep or not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,4})?", lang) or not path.strip():
        raise argparse.ArgumentTypeError(f"expected LANG=PATH with a language code like fr or pt-br, got {text!r}")
    return lang, result.path(path.strip())


Found = tuple[int, str, bool, srt.Cue]  # (track order, language, forced, cue)


def _group(found: list[Found]) -> list[list[Found]]:
    """Group the lines that show the same thing: each joins the first group
    whose first line it overlaps enough."""
    found = sorted(found, key=lambda x: (x[3].start, x[0]))
    groups: list[list[Found]] = []
    for item in found:
        c = item[3]
        for g in groups[-3:]:
            a = g[0][3]
            ov = min(a.end, c.end) - max(a.start, c.start)
            if ov >= SAME_LINE_SHARE * min(a.duration, c.duration):
                g.append(item)
                break
        else:
            groups.append([item])
    return groups


def _lead(g: list[Found]) -> Found:
    """The line whose text and times a group takes: a forced track's first,
    then a line that is not a subtitle credit, then the first track given."""
    return min(g, key=lambda x: (not x[2], bool(CREDIT_RE.search(x[3].plain)), x[0]))


def _proved(g: list[Found], need: int = 2, timing_language: str | None = None) -> bool:
    """A forced track shows the line, or `need` languages do. pt and pt-br
    are one language here: two of them prove nothing. With a share to
    meet (need_languages), the timing file's own language does not count."""
    if any(f for _, _, f, _ in g):
        return True
    if need > 2:
        return len(srt.other_languages([lang for _, lang, _, _ in g], timing_language)) >= need
    return len({lang.split("-")[0] for _, lang, _, _ in g if lang != "und"}) >= 2


def need_languages(n: int) -> int:
    """How many languages prove a line when the fitting tracks hold n other
    languages: three quarters of them from SHARE_FROM on, two below."""
    return max(2, math.ceil(SHARE * n)) if n >= SHARE_FROM else 2


def is_story_kind(kind: str | None) -> bool:
    """A kind of text that is story text: not credits, a logo or the
    background."""
    return kind in READER_KINDS and kind not in NOT_STORY_KINDS


def is_story(kind: str | None, wants_read: bool) -> bool:
    """A reading the film wants read, of a kind that is story text."""
    return bool(wants_read) and is_story_kind(kind)


def fold_text(text: str) -> str:
    """Text as compared for sameness: case, punctuation, line breaks and
    spacing folded away, so "Mommy's / home" and "mommy's home" match."""
    return " ".join(re.sub(r"[\W_]", " ", text.casefold()).split())


def _id(g: list[Found]) -> str:
    """The track's place in the list (from 1, tracks before forced tracks)
    and the cue's number in that file, of the first track that shows it."""
    k, _, _, first = min(g, key=lambda x: x[0])
    return f"{k + 1}:{first.n}"


def _entry(g: list[Found], state: str, reason: str | None = None, start: int | None = None, end: int | None = None) -> dict:
    """One row of on_screen.json. `id` names the line in the first track
    that shows it (_id). Text and times come from _lead, a forced track
    first."""
    _, _, _, lead = _lead(g)
    texts: dict[str, list[str]] = {}
    for _k, lang, _, c in sorted(g, key=lambda x: (not x[2], x[0])):
        texts.setdefault(lang, []).extend(c.lines)
    entry = {
        "id": _id(g),
        "n": None,
        "start": lead.start if start is None else start,
        "end": lead.end if end is None else end,
        "lines": list(lead.lines),
        "texts": texts,
        "evidence": [{"track": t + 1, "language": lang, "forced": f, "cue": c.n} for t, lang, f, c in g],
        "state": state,
    }
    if reason:
        entry["reason"] = reason
    return entry


def picture_span(r: dict) -> tuple[int, int]:
    """A reading's time: first seen to last seen, ON_SCREEN_MIN_MS at least.
    Whether timing cues cover it (_under_timing) is judged on this span."""
    return r["first_ms"], max(r["last_ms"], r["first_ms"] + ON_SCREEN_MIN_MS)


def picture_shown_end(r: dict) -> int:
    """Where a reading's cue aims to end: the text stays on screen after its
    last frame until the next saved frame (`next_ms`), PICTURE_HOLD_MS at
    most, and the cue lasts PICTURE_HOLD_MS at least. `next_ms` is null after
    the last saved frame (PICTURE_HOLD_MS then); a reading with no `next_ms`
    key comes from an older work folder and keeps picture_span's end."""
    end = picture_span(r)[1]
    if "next_ms" not in r:
        return end
    nxt = r["next_ms"]
    hold = PICTURE_HOLD_MS if nxt is None else min(max(nxt - r["last_ms"], 0), PICTURE_HOLD_MS)
    return max(end, r["first_ms"] + PICTURE_HOLD_MS, r["last_ms"] + hold)


def _picture_entry(r: dict, state: str, reason: str | None = None, start: int | None = None, end: int | None = None) -> dict:
    """An entry for a story text only the picture shows: the reader's text,
    the reading's times. Its `texts` hold one key, `picture`, equal to its
    lines, so the chunks show no `also:` line for it."""
    a, b = picture_span(r)
    lines = [x.strip() for x in r["text"].split(" / ") if x.strip()]
    entry = {
        "id": f"{PICTURE}:{r['first_ms']}",
        "n": None,
        "start": a if start is None else start,
        "end": b if end is None else end,
        "lines": lines,
        "texts": {PICTURE: list(lines)},
        "evidence": PICTURE,
        "kind": r.get("kind"),
        "frames": list(r.get("frames", [])),
        "state": state,
        # The reading's own time, which a sync rebuild starts from and
        # judges against the timing cues.
        "found": [a, b],
        # Where its cue aims to end (picture_shown_end), which a sync
        # rebuild places it with.
        "shown_end": picture_shown_end(r),
    }
    if reason:
        entry["reason"] = reason
    return entry


def picture_outcome(eid: str, picture: dict) -> str | None:
    """What the picture said of an entry, for the report: `shown` (a story
    reading named it), `shown, not story text`, `not shown` (its frames were
    all read and none named it), `not read` (frames thinned away or not
    read), or None when no frame looked at it."""
    if eid in picture.get("story", ()):
        return "shown"
    if eid in picture.get("named", ()):
        return "shown, not story text"
    if eid in picture.get("checked", ()):
        return "not shown"
    if eid in picture.get("looked", ()) or eid in picture.get("unsure", ()):
        return "not read"
    return None


def on_screen(
    timing: list[srt.Cue],
    tracks: list[tuple[str, Path]],
    forced: list[tuple[str, Path]],
    picture: dict | None = None,
    timing_language: str | None = None,
) -> tuple[list[dict], dict]:
    """Lines the other tracks show where the timing file shows nothing.

    Returns every entry found, in time order, and a summary for
    build.json. An entry in state `cue` is to be added to the timing file
    at its `start` and `end`; one in state `left_out` is only recorded,
    with a `reason` (ON_SCREEN_REASONS). `texts` holds the entry's lines per
    language in the order given. Tracks are given in order of preference:
    the first one with the line gives the entry's text and times.

    A line the timing file covers is the timing file's own line, so it
    stays out and is only counted, except when two languages show it over
    cues that are only songs or sounds: a sign shown during a song is
    recorded, though not added (a track also translates lyrics marked by
    italics alone).

    `picture` (read_picture) is what the frames showed: `unsure` the ids
    the tracks left unsure (one language alone, or too few languages), `story` the ids a story reading named,
    `named` those any reading named, `looked` those a frame listed,
    `checked` those whose frames were all read, and `readings` the story
    readings that named no entry.

    With SHARE_FROM or more other languages among the tracks that fit
    (the timing file's own language and `und` left out), a line needs
    three quarters of them (need_languages); one shown by two or more but
    fewer is left out as too few languages, and the picture can still
    bring it back. With that many languages, a line shown at the same time
    as another track's subtitle credit is left out with it as a credit."""
    sung = srt.italic_songs(timing) | {
        c.n for c in timing if srt.is_sound(c) or srt.is_bare_sound(srt.strip_hi(c.lines, True)[0])
    }
    starts = [c.start for c in timing]
    longest = max((c.duration for c in timing), default=0)
    found: dict[str | None, list[Found]] = {None: [], CREDIT: [], SONG_LINE: [], DURING_SONG: []}
    summary_tracks = []
    covered_lines = 0
    for k, (lang, path, is_forced) in enumerate([(a, b, False) for a, b in tracks] + [(a, b, True) for a, b in forced]):
        cues, _ = srt.parse(path)
        info = {"language": lang, "path": str(path), "forced": is_forced, "cues": len(cues)}
        if not is_forced and cues:
            f = srt.fit(timing, cues)
            info.update(fits=f["fits"], offset_ms=f["offset_ms"], reason=f["reason"])
            if not f["fits"]:
                summary_tracks.append(info)
                continue
            cues = srt.shift(cues, f["offset_ms"])
        summary_tracks.append(info)
        for c, covered in zip(cues, srt._coverage(cues, timing) if cues and timing else []):
            if c.end <= c.start:
                continue
            # Read as a hearing-impaired line: "POLYBUS: Hmm..." is a sound.
            # Sounds, bare sounds and lyrics marked with ♪ are never text
            # on screen.
            said = srt.strip_hi(c.lines, True)[0]
            if "♪" in c.plain or "♫" in c.plain or not said or srt.is_bare_sound(said):
                continue
            kind = CREDIT if CREDIT_RE.search(c.plain) else SONG_LINE if srt.LYRIC_HASH_RE.search(c.plain) else None
            if covered >= GAP_MAX_COVERED:
                i = bisect.bisect_left(starts, c.start - longest)
                under = [t for t in timing[i:] if t.start < c.end and min(t.end, c.end) > max(t.start, c.start)]
                if kind is None and under and all(t.n in sung for t in under):
                    kind = DURING_SONG
                else:
                    covered_lines += 1
                    continue
            found[kind].append((k, lang, is_forced, c))

    used = [t["language"] for t in summary_tracks if not t["forced"] and t.get("fits")]
    others = len(srt.other_languages(used, timing_language))
    need = need_languages(others)
    pic = picture or {}
    story = set(pic.get("story", ()))
    entries = []
    # What is to be placed, in time order: (start, order, group or reading).
    place: list[tuple[int, int, list[Found] | dict]] = []
    for g in _group(found[SONG_LINE]):
        if _id(g) in story:
            place.append((g[0][3].start, len(place), g))
        else:
            entries.append(_entry(g, "left_out", SONG_LINE))
    for g in _group(found[DURING_SONG]):
        if _proved(g):
            entries.append(_entry(g, "left_out", DURING_SONG))
        else:
            covered_lines += len(g)
    # A subtitle credit reads as one in some languages only ("Tekstitys:",
    # "Creative supervisor" do not). With SHARE_FROM or more other
    # languages the lines are grouped together, and a group is a credit
    # when any of its lines reads as one. With fewer, credits are grouped
    # apart, so a card two languages show stays a card when another
    # track's credit overlaps it.
    credit_lines = {(k, c.n) for k, _, _, c in found[CREDIT]}
    if others >= SHARE_FROM:
        groups = _group(found[None] + found[CREDIT])
    else:
        groups = _group(found[CREDIT]) + _group(found[None])
    for g in groups:
        eid = _id(g)
        if any((k, c.n) in credit_lines for k, _, _, c in g):
            if eid in story:
                place.append((g[0][3].start, len(place), g))
            else:
                entries.append(_entry(g, "left_out", CREDIT))
        elif _proved(g, need, timing_language) or eid in story:
            place.append((g[0][3].start, len(place), g))
        elif eid in pic.get("unsure", ()):
            entries.append(_entry(g, "left_out", NOT_CONFIRMED if eid in pic.get("checked", ()) else NOT_CHECKED))
        else:
            entries.append(_entry(g, "left_out", FEW_LANGUAGES if _proved(g) else ONE_LANGUAGE))
    # A story text only the picture shows: speech wins, so one the timing
    # file covers is its own line, as for a track's line. It is kept, left
    # out, so a sync rebuild can look at it again.
    for r in pic.get("readings", ()):
        a, b = picture_span(r)
        if _under_timing(a, b, timing):
            entries.append(_picture_entry(r, "left_out", UNDER_TIMING))
            continue
        place.append((a, len(place), r))
    place.sort(key=lambda x: (x[0], x[1]))
    last_end = 0
    for k, (_, _, item) in enumerate(place):
        if isinstance(item, dict):
            lead_start, seen_end = picture_span(item)
            # It stays up after its last frame, but never past where the
            # next item to place starts, so it pushes none into no room.
            following = place[k + 1][0] if k + 1 < len(place) else None
            aim = picture_shown_end(item)
            lead_end = max(seen_end, min(aim, following)) if following is not None else aim
            make = partial(_picture_entry, item)
        else:
            lead = _lead(item)[3]
            lead_start, lead_end = lead.start, lead.end
            make = partial(_entry, item)
        i = bisect.bisect_left(starts, lead_start)
        start = max(lead_start, timing[i - 1].end if i else 0, last_end)
        end = min(lead_end, timing[i].start if i < len(timing) else lead_end)
        if end - start < ON_SCREEN_MIN_MS:
            entries.append(make("left_out", NO_ROOM))
            continue
        entries.append(make("cue", start=start, end=end))
        last_end = end
    entries.sort(key=lambda e: (e["start"], e["id"]))
    summary = {"tracks": summary_tracks, **on_screen_counts(entries), "covered_lines": covered_lines, "languages_needed": need}
    if picture is not None:
        for e in entries:
            word = "found" if e.get("evidence") == PICTURE else picture_outcome(e["id"], pic)
            if word:
                e["picture"] = word
        summary["picture"] = {
            **pic.get("info", {}),
            **picture_counts(entries),
            "looked_at": sum(1 for e in entries if e.get("picture")),
        }
    return entries, summary


def picture_counts(entries: list[dict]) -> dict:
    """The story texts only the picture shows: `found` those not under a
    timing line, `readings_already_in_timing` those under one."""
    pictures = [e for e in entries if e.get("evidence") == PICTURE]
    under = sum(1 for e in pictures if e.get("reason") == UNDER_TIMING)
    return {"readings_already_in_timing": under, "found": len(pictures) - under}


def _under_timing(start: int, end: int, timing: list[srt.Cue]) -> bool:
    """Timing cues cover at least GAP_MAX_COVERED of this time span."""
    span = srt.Cue(n=0, start=start, end=end, ts="", lines=[])
    return bool(timing) and srt._coverage([span], timing)[0] >= GAP_MAX_COVERED


def on_screen_counts(entries: list[dict]) -> dict:
    """The entries added as cues, and the count per state and per reason."""
    states: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for e in entries:
        states[e["state"]] = states.get(e["state"], 0) + 1
        if e.get("reason"):
            reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
    return {"added": states.get("cue", 0), "states": states, "reasons": reasons}


def read_picture(work: Path, readings_path: Path) -> dict:
    """What the frames showed, for on_screen(): W/screen/frames.json (which
    entries were unsure, which frames listed which entry) and the readings
    `screen.py collect` wrote. A frame named in `missing` was not read."""
    frames_path = work / FRAMES_FILE
    try:
        frames = json.loads(frames_path.read_text(encoding="utf-8"))
        readings = json.loads(readings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"--screen needs {frames_path} and the readings file: {e}") from e
    missing = set(readings.get("missing", []))
    listing: dict[str, list[str]] = {}
    for f in frames.get("frames", []):
        for item in f.get("entries", []):
            listing.setdefault(item["id"], []).append(f["file"])
    story: set[str] = set()
    named: set[str] = set()
    new = []
    for r in readings.get("readings", []):
        ids = set(r.get("shows_entry") or [])
        named |= ids
        if is_story(r.get("kind"), r.get("wants_read")):
            story |= ids
            if not ids:
                new.append(r)
    info = {
        "frames": len(frames.get("frames", [])),
        "frames_not_read": sorted(missing),
        "readings": len(readings.get("readings", [])),
        "unsure": len(frames.get("unsure", [])),
        "notes": list(frames.get("notes", [])),
    }
    return {
        "unsure": set(frames.get("unsure", [])),
        "looked": set(listing),
        "checked": {i for i, files in listing.items() if not missing & set(files)},
        "story": story,
        "named": named,
        "readings": new,
        "info": info,
    }


def labels_in(lines: list[str], hi: bool = True) -> list[str]:
    found = []
    for ln in lines:
        name = srt.clean_line(ln, hi).label
        if name and re.sub(r"[\d#.]+", "", name).strip().upper() not in NOT_NAMES:
            found.append(name.title())
    return found


def cue_label(lines: list[str], hi: bool = True) -> str | None:
    """The speaker label for a cue. A cue with two or more dash lines
    ("- Who?" / "- IVY: Me.") holds several speakers, so it gets one name
    per dash line, "?" where a line has none: "? / Ivy". A line without a
    dash continues the dash line above it. A line that is only a sound
    description ("- [door slams]") is no speaker's turn. `hi` says whether
    the lines come from a hearing-impaired file."""
    said = [ln for ln in lines if (c := srt.clean_line(ln, hi)).text or c.label]
    turns = srt.turns(said)
    if len(turns) < 2:
        found = labels_in(said, hi)
        return found[0] if found else None
    names = [(labels_in(t, hi) or ["?"])[0] for t in turns]
    return None if all(n == "?" for n in names) else " / ".join(names)


def speaker_hint(entry: dict) -> str:
    """What chunks and the review file show for a cue: the name or label,
    and the voice from the audio when there is one: "Ivy · V3"."""
    who = entry.get("name") or entry.get("label")
    return " · ".join(x for x in (who, entry.get("voice")) if x)


BIBLE_CHECK_FILES = (
    "questions.json",
    "second.json",
    "questions.voices.json",
    "second.voices.json",
    "compare.json",
    "judged.json",
    "decisions.writer.json",
)


def build(
    work: Path,
    timing_path: Path,
    source_path: Path | None,
    en_path: Path | None,
    keep_bible_check: bool = False,
    hi: str = "remove",
    tracks: list[tuple[str, Path]] | None = None,
    forced: list[tuple[str, Path]] | None = None,
    shift_ms: int | None = None,
    timing_language: str | None = None,
    screen_path: Path | None = None,
) -> dict:
    """Write the work folder. `shift_ms` is for the sync rebuild: the same
    files moved by that many ms. The on-screen entries of the build before
    are then moved too, not found again, and the timing cues it dropped
    under them are dropped again, so every cue keeps its number. A work
    folder with no on_screen.json finds them again. A picture entry keeps
    its times, which are the video's, and its number, and is shown at its
    own time when it has room there. `screen_path` is the readings file
    of `screen.py collect`: the entries are found again with what the
    picture showed (read_picture)."""
    if hi not in HI_MODES:
        raise SystemExit(f"--hi is one of {', '.join(HI_MODES)}")
    if shift_ms is not None and screen_path is not None:
        raise SystemExit("--screen is for the build of step 2; a --shift-ms rebuild keeps what it found")
    picture = read_picture(work, screen_path) if screen_path is not None else None
    remove = hi == "remove"
    work.mkdir(parents=True, exist_ok=True)
    # Read before anything is deleted: the rebuild repeats this build's
    # on-screen entries.
    before = None
    if shift_ms is not None and (work / ON_SCREEN_FILE).exists():
        old_info = (json.loads((work / "build.json").read_text(encoding="utf-8")) if (work / "build.json").exists() else {}).get(
            "on_screen"
        )
        before = (json.loads((work / ON_SCREEN_FILE).read_text(encoding="utf-8")), old_info)
    # A new build starts a new translation: an earlier run's translations,
    # fixes, draft, checks and speaker labels must never be read into this
    # one: the new timing file may number its cues differently.
    shutil.rmtree(work / "out", ignore_errors=True)
    if shift_ms is None and screen_path is None:
        # W/screen/ holds what is read from the video's picture
        # (`screen.py`), for this build's cues. Clearing it here means no
        # step can read files an earlier run left for other cues. A sync
        # rebuild keeps the numbers, and the folder; `deliver` reads its
        # ends.json only when it still fits the draft's story end. The
        # build with --screen reads the folder.
        shutil.rmtree(work / "screen", ignore_errors=True)
    # The bible check's files belong to the earlier run's bible too, unless
    # this rebuild only shifts the times of the same cues.
    stale = ("draft.tr.srt", "checks.json", "speakers.json") + (() if keep_bible_check else BIBLE_CHECK_FILES)
    for name in stale:
        (work / name).unlink(missing_ok=True)
    # Faults the parser put right in each file read: a cue with no blank line
    # before it, or text cut off from its cue by a stray blank line.
    repairs: dict[str, list[str]] = {"timing": []}
    timing, enc = srt.parse(timing_path, repairs["timing"])
    if not timing:
        raise SystemExit(f"no cues found in {timing_path}")
    hearing_impaired = {"timing": srt.hearing_impaired(timing)["hearing_impaired"]}

    # On-screen text the timing file lacks joins it as cues of its own, so
    # every later step (pairing, chunks, the delivered file) treats them
    # like the rest. Cue numbers follow the merged order.
    screen_summary = None
    screen: dict[int, dict] = {}
    entries: list[dict] = []
    dropped_under: list[int] = []
    # Timing cues that `build` drops as sound only ("[somber music]")
    # leave the screen empty: they neither cover a line nor bound it.
    kept = [c for c in timing if srt.strip_hi(c.lines, hearing_impaired["timing"])[0]] if remove else timing
    if before is not None:
        entries, screen_summary = before
        screen_summary = dict(screen_summary) if screen_summary else None
        # The shift is always from the files of the build without
        # --shift-ms, as `srt.py shift` reads those: running the same
        # rebuild twice moves the entries once.
        was = (screen_summary or {}).get("shift_ms", 0)
        for e in entries:
            if e.get("evidence") == PICTURE:
                # Video times: the shift moves the subtitles onto them.
                e["start"], e["end"] = e.get("found") or (e["start"], e["end"])
                e["found"] = [e["start"], e["end"]]
                # The timing cues moved, so each is judged again from its
                # own times: speech covers it, or its room is looked at
                # again (_fit_picture_entries).
                if _under_timing(e["start"], e["end"], kept):
                    e["state"], e["reason"] = "left_out", UNDER_TIMING
                else:
                    e["state"] = "cue"
                    e.pop("reason", None)
                    # Judged on the seen span, placed by where it aims to
                    # end; an entry from an older work folder has no
                    # `shown_end` and keeps the seen span.
                    e["end"] = max(e["end"], e.get("shown_end", e["end"]))
                continue
            start, end = e.get("found") or (e["start"] - was, e["end"] - was)
            e["found"] = [start, end]
            # Never before 0:00, as `srt.py shift` moves the files.
            e["start"], e["end"] = max(start + shift_ms, 0), max(end + shift_ms, 0)
        if screen_summary is not None:
            screen_summary["shift_ms"] = shift_ms
            dropped_under = list(screen_summary.get("dropped_timing_cues", []))
    elif tracks or forced or picture is not None:
        entries, screen_summary = on_screen(kept, tracks or [], forced or [], picture, timing_language)
        if timing_language:
            # Which other languages the tracks hold, as `sources.py others`
            # counts them: `screen.py frames` reads this.
            screen_summary["timing_language"] = timing_language
            # A track that does not fit was never used, so it does not count.
            used = [t["language"] for t in screen_summary["tracks"] if not t["forced"] and t.get("fits")]
            screen_summary["other_languages"] = srt.other_languages(used, timing_language)
        extra = [e for e in entries if e["state"] == "cue"]
        # A sound-only cue under an added one goes: paired with the source
        # file's copy of the card, it would deliver it twice. The numbers
        # are kept, so a sync rebuild drops the same cues.
        kept_n = {c.n for c in kept}
        dropped_under = [
            c.n for c in timing if c.n not in kept_n and any(min(c.end, e["end"]) > max(c.start, e["start"]) for e in extra)
        ]
        screen_summary["dropped_timing_cues"] = dropped_under
        # Times as the build without --shift-ms found them, so a later
        # sync rebuild moves each entry from there, never twice. A picture
        # entry holds its reading's own time already.
        for e in entries:
            if e.get("evidence") != PICTURE:
                e["found"] = [e["start"] - (shift_ms or 0), e["end"] - (shift_ms or 0)]
        if shift_ms is not None:
            screen_summary["shift_ms"] = shift_ms
    # Every picture entry has a number, left out or not, so a sync rebuild
    # can place it again without moving any other cue's number.
    extra = [e for e in entries if e["state"] == "cue" or e.get("evidence") == PICTURE]
    if extra:
        gone = set(dropped_under)
        rest = [c for c in timing if c.n not in gone]
        at = {e.get("n"): e for e in extra}
        total = len(rest) + len(extra)
        if before is not None and len(at) == len(extra) and all(isinstance(n, int) and 1 <= n <= total for n in at):
            # Each entry goes back to its number and the timing cues fill
            # the rest in their order: the same numbers even where the
            # shift moved a card and a line both to 0:00.
            lines = iter(rest)
            merged = [(None, at[i]) if i in at else (next(lines), None) for i in range(1, total + 1)]
        else:
            merged = [(c, None) for c in rest] + [(None, e) for e in extra]
            merged.sort(key=lambda x: (x[0].start, 0) if x[0] is not None else (x[1]["start"], 1))
        _fit_picture_entries(merged, refit=before is not None, spoken={c.n for c in kept})
        if screen_summary is not None:
            screen_summary.update(on_screen_counts(entries))
            if screen_summary.get("picture") is not None:
                # A sync rebuild judged each picture entry again.
                screen_summary["picture"] = {**screen_summary["picture"], **picture_counts(entries)}
        timing = []
        for i, (c, e) in enumerate(merged, 1):
            if c is not None:
                timing.append(srt.Cue(n=i, start=c.start, end=c.end, ts=c.ts, lines=c.lines))
            else:
                ts = f"{srt.fmt_ms(e['start'])} --> {srt.fmt_ms(e['end'])}"
                timing.append(srt.Cue(n=i, start=e["start"], end=e["end"], ts=ts, lines=e["lines"]))
                e["n"] = i
                screen[i] = e
    if screen_summary is not None:
        screen_summary["file"] = str(work / ON_SCREEN_FILE)
        screen_summary["cues"] = [
            {"n": n, "ts": srt.fmt_ms(e["start"]), "texts": {k: _one_line(v) for k, v in e["texts"].items()}}
            for n, e in screen.items()
            if e["state"] == "cue"
        ]

    src_pairs = None
    if source_path and source_path.resolve() != timing_path.resolve():
        repairs["source"] = []
        source, _ = srt.parse(source_path, repairs["source"])
        src_pairs = srt.pair(by_start(timing), source)
        hearing_impaired["source"] = srt.hearing_impaired(source)["hearing_impaired"]
    # Songs marked only with italics, found in the file the source text
    # comes from (srt.italic_songs). The on-screen cues are not the timing
    # file's: a card between two song lines must not split the song, and
    # italics on another language's track say nothing about songs.
    italic_timing = srt.italic_songs([c for c in timing if c.n not in screen])
    italic_source = srt.italic_songs(source) if src_pairs is not None else set()
    en_pairs = None
    if en_path and en_path.resolve() != timing_path.resolve():
        repairs["en"] = []
        en, _ = srt.parse(en_path, repairs["en"])
        en_pairs = srt.pair(by_start(timing), en)
        hearing_impaired["en"] = srt.hearing_impaired(en)["hearing_impaired"]

    # Each file is cleaned by its own flag: parentheses and labels in
    # capitals go only from a hearing-impaired file.
    hi_timing = hearing_impaired["timing"]
    hi_source = hearing_impaired.get("source", hi_timing)
    hi_en = hearing_impaired.get("en", hi_timing)

    def clean(lines: list[str], hi_file: bool) -> tuple[list[str], bool]:
        if not remove:
            return lines, False
        out, _, found = srt.strip_hi(lines, hi_file)
        return out, found

    speakers: dict[str, dict] = {}
    rows, unpaired, cleaned, dropped, songs, sounds = [], 0, 0, 0, 0, 0
    asked = False  # the last cue with words ended with a question
    shown: dict[int, list[str]] = {}
    for c in timing:
        src_raw = c.lines if src_pairs is None else [ln for o in src_pairs[c.n] for ln in o.lines]
        en_raw = None
        if en_path is not None:
            en_raw = c.lines if en_pairs is None else [ln for o in en_pairs[c.n] for ln in o.lines]
        timing_lines, f1 = clean(c.lines, hi_timing)
        src_lines, f2 = clean(src_raw, hi_source)
        en_lines, f3 = clean(en_raw, hi_en) if en_raw is not None else (None, False)
        cleaned += f1 or f2 or f3
        # A cue whose own text and source text are only sound descriptions
        # and labels has nothing to translate: it is left out of the work
        # and of the delivered file. When the source is another file and
        # held only sounds here, what is left of the timing file's text
        # does not keep the cue if it too reads as a sound once cleaned as
        # a hearing-impaired file's: "(Laughs)" in a timing file too plain
        # to lose its parentheses.
        src_sounds = src_pairs is not None and bool(src_raw) and not src_lines and f2
        timing_said = bool(timing_lines) and not (src_sounds and not srt.strip_hi(timing_lines, True)[0])
        # Text on screen is never a song, a sound or a bare sound, whatever
        # the source file has at its time: it is delivered.
        card = c.n in screen
        sound_only = remove and (f1 or f2) and not timing_said and not src_lines and not card
        shown[c.n] = timing_lines
        said = src_lines or timing_lines
        row = {
            "n": c.n,
            "ts": c.ts,
            "start": c.start,
            "end": c.end,
            "timing_lines": timing_lines,
            "source": src_lines,
            "en": en_lines,
        }
        if card:
            # The other tracks' text stands in where the source file has
            # none here; `chunks` shows the rest of the languages.
            row["on_screen"] = {k: list(v) for k, v in screen[c.n]["texts"].items()}
            if screen[c.n]["state"] == "left_out":
                # A picture entry left out (no room, or under a timing
                # line): it keeps its number and is not delivered.
                row["left_out"] = screen[c.n]["reason"]
            if not src_lines:
                row["source"] = timing_lines
            if not en_lines:
                row["en"] = None
        if f1 or f2 or f3:
            # The check reads this: a label or a description in parentheses
            # in the Turkish is a fail only where the source had tags.
            row["tags_removed"] = True
        if sound_only:
            row["sound_only"] = True
            dropped += 1
        elif not card and (
            srt.is_lyric(said)
            or (
                srt.whole_italic(said)
                and (
                    all(o.n in italic_source for o in src_pairs[c.n])
                    if src_pairs is not None and src_lines
                    else c.n in italic_timing
                )
            )
        ):
            # The source text decides, and the timing text only when the
            # source has none here: speech in the source stays speech even
            # where the timing file shows a lyric. Which songs are
            # translated is decided after the bible, by `songs`.
            row["song"] = True
            songs += 1
        elif (
            not card
            and srt.is_bare_sound(said)
            and (not en_lines or srt.is_bare_sound(en_lines))
            and not (srt.is_answer_sound(said) and asked)
        ):
            # "Oh." or "Hmm?" alone: the audience hears it, so it is not
            # subtitled. The English cross-check must agree, so a word in
            # another language spelled like a sound (German "Er.", "Him.")
            # stays. "Uh-huh" right after a question is an answer and stays.
            row["left_out"] = "sound"
            sounds += 1
        if not sound_only and "left_out" not in row:
            asked = bool(said) and srt.strip_tags(said[-1]).strip().endswith("?")
        if not sound_only:
            if src_pairs is not None and not src_lines and c.n not in screen:
                unpaired += 1
            label = cue_label(src_raw, hi_source) or cue_label(en_raw or [], hi_en)
            if label:
                speakers[str(c.n)] = {"label": label}
        rows.append(row)

    # The timing file's own times, character for character; its text
    # without sound descriptions and labels, unless the user keeps them.
    srt.write(work / "timing.srt", timing, shown)
    (work / "cues.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    (work / "speakers.json").write_text(json.dumps(speakers, ensure_ascii=False, indent=1), encoding="utf-8")
    # Empty when no track was given, so no earlier run's entries survive.
    (work / ON_SCREEN_FILE).write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, p in (("timing", timing_path), ("source", source_path), ("en", en_path)):
        if p:
            dest = work / "sources" / f"{name}{p.suffix}"
            dest.parent.mkdir(exist_ok=True)
            if p.resolve() != dest.resolve():
                shutil.copyfile(p, dest)
    summary = {
        "cues": len(timing),
        "timing_encoding": enc,
        "source_paired_from_other_file": src_pairs is not None,
        "cues_without_source_text": unpaired,
        "has_english": en_path is not None,
        "cues_with_speaker_label": sum(1 for v in speakers.values() if "label" in v),
        "hearing_impaired": hearing_impaired,
        "hearing_impaired_tags": hi,
        "cues_with_tags_or_labels_removed": cleaned,
        "sound_only_cues_dropped": dropped,
        "song_cues": songs,
        "bare_sound_cues_dropped": sounds,
        "on_screen": screen_summary,
        "repairs": {name: len(found) for name, found in repairs.items()},
        "warnings": [
            f"the {name} file is malformed; repairs made while reading it: {len(found)} (first: {found[0]})"
            for name, found in repairs.items()
            if found
        ],
    }
    (work / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def _fit_picture_entries(merged: list[tuple[srt.Cue | None, dict | None]], refit: bool, spoken: set[int]) -> None:
    """In a sync rebuild (`refit`) the cues around a picture entry moved and
    it did not. Each keeps its place in `merged`, its number, but its room
    is looked for at its own time, between the cues shown just before and
    just after it there, whatever their numbers: one left under
    ON_SCREEN_MIN_MS is left out (NO_ROOM_SHIFT). A timing cue not in
    `spoken` holds only sounds and is never shown, so it takes no room, as
    in the first build. A picture entry left out, in any build, has its
    times clipped into its numbered slot; it is never delivered."""

    def span(item: tuple[srt.Cue | None, dict | None]) -> tuple[int, int]:
        c, e = item
        return (c.start, c.end) if c is not None else (e["start"], e["end"])

    def picture(e: dict | None) -> bool:
        return e is not None and e.get("evidence") == PICTURE

    # What is shown whatever the picture entries do: the spoken timing cues
    # and the tracks' entries. Picture entries shown join it one by one, in
    # time.
    shown = [span(x) for x in merged if (x[0] is not None and x[0].n in spoken) or (x[1] is not None and not picture(x[1]))]
    order = sorted((i for i, x in enumerate(merged) if picture(x[1])), key=lambda i: (merged[i][1]["start"], i))
    for k, i in enumerate(order):
        e = merged[i][1]
        if e["state"] == "cue":
            if not refit:
                continue
            lo = max((b for a, b in shown if a <= e["start"]), default=0)
            hi = min((a for a, _ in shown if a > e["start"]), default=max(e["end"], lo))
            # A picture entry still to come is not in `shown` yet: this one
            # stays up after its last frame only until that one starts, so
            # it pushes none into no room (never shorter than it was seen).
            later = [merged[j][1]["start"] for j in order[k + 1 :] if merged[j][1]["state"] == "cue"]
            later = [a for a in later if a > e["start"]]
            if later:
                seen_end = (e.get("found") or (e["start"], e["end"]))[1]
                hi = min(hi, max(seen_end, min(later)))
            start, end = max(e["start"], lo), min(e["end"], hi)
            if end - start >= ON_SCREEN_MIN_MS:
                e["start"], e["end"] = start, end
                shown.append((start, end))
                continue
            e["state"], e["reason"] = "left_out", NO_ROOM_SHIFT
        lo = span(merged[i - 1])[1] if i else 0
        hi = span(merged[i + 1])[0] if i + 1 < len(merged) else max(e["end"], lo)
        if lo > hi:
            e["start"] = e["end"] = hi
        else:
            e["start"] = min(max(e["start"], lo), hi)
            e["end"] = max(min(e["end"], hi), e["start"])


def time_order(cues: list[srt.Cue], loose: set[int]) -> list[srt.Cue]:
    """The cues in the order they are shown. A sync rebuild keeps every
    number and shows a picture entry at its own time (`_fit_picture_entries`),
    so its number can sit out of time order: each cue in `loose` is placed
    by its start among the others, which keep their order."""
    fixed = [c for c in cues if c.n not in loose]
    extra = sorted((c for c in cues if c.n in loose), key=lambda c: (c.start, c.n))
    out: list[srt.Cue] = []
    k = 0
    for c in fixed:
        while k < len(extra) and extra[k].start < c.start:
            out.append(extra[k])
            k += 1
        out.append(c)
    return out + extra[k:]


def by_start(cues: list[srt.Cue]) -> list[srt.Cue]:
    """The cues sorted by start, as `srt.pair` reads them: a picture entry a
    sync rebuild showed at its own time can sit out of time order."""
    return sorted(cues, key=lambda c: (c.start, c.n))


def _one_line(lines: list[str] | None) -> str:
    return " / ".join(ln.strip() for ln in lines) if lines else ""


def left_out(row: dict) -> bool:
    """The cue gets no translation and is not delivered: only sounds
    described, a bare sound ("Oh."), or a song left out."""
    return bool(row.get("sound_only") or row.get("left_out"))


SONG_MODES = ("story", "skip", "all")
SONGS_FILE = "songs.json"


def read_song_choice(work: Path) -> list[tuple[int, int]]:
    """The cue ranges of the songs the bible writer kept, from songs.json:
    {"keep": [{"first": 520, "last": 526, "why": "..."}]}."""
    path = work / SONGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"{SONGS_FILE} cannot be read: {e}") from e
    keep = data.get("keep") if isinstance(data, dict) else None
    if not isinstance(keep, list):
        raise SystemExit(f'{SONGS_FILE} needs a "keep" list, empty when no song is kept')
    out = []
    for k, item in enumerate(keep):
        first = item.get("first") if isinstance(item, dict) else None
        last = item.get("last") if isinstance(item, dict) else None
        if not (isinstance(first, int) and isinstance(last, int) and 0 < first <= last):
            raise SystemExit(f'{SONGS_FILE}: keep[{k}] needs whole cue numbers "first" <= "last"')
        out.append((first, last))
    return out


def is_musical(work: Path) -> bool:
    """The bible writer marked the film a musical in songs.json
    ({"musical": true, "keep": [...]}): its characters sing the story."""
    path = work / SONGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("musical") is True


def songs(work: Path, mode: str) -> dict:
    """Mark which song cues are left out, by the preferences' "Songs":
    `story` keeps only the songs listed in songs.json, `skip` leaves every
    song out and `all` keeps them all. Run it after the bible and before
    `chunks`; running it again recomputes the choice."""
    if mode not in SONG_MODES:
        raise SystemExit(f"--mode is one of {', '.join(SONG_MODES)}")
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    note = None
    keep: list[tuple[int, int]] = []
    song_rows = [r for r in rows if r.get("song")]
    if mode == "story":
        if (work / SONGS_FILE).exists():
            keep = read_song_choice(work)
        elif song_rows:
            # A film with no songs needs no list, so no note either.
            note = f"no {SONGS_FILE}: every song is left out"
    for r in song_rows:
        kept = mode == "all" or any(a <= r["n"] <= b for a, b in keep)
        if kept:
            r.pop("left_out", None)
        else:
            r["left_out"] = "song"
    tmp = work / "cues.json.tmp"
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    _swap(tmp, work / "cues.json")
    left = [r["n"] for r in song_rows if r.get("left_out")]
    return {
        "mode": mode,
        "song_cues": len(song_rows),
        "kept": len(song_rows) - len(left),
        "left_out": len(left),
        "note": note,
    }


def chunks(work: Path, target: int) -> list[dict]:
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    speakers = json.loads((work / "speakers.json").read_text(encoding="utf-8"))
    cues = [
        srt.Cue(n=r["n"], start=r["start"], end=r["end"], ts=r["ts"], lines=r["timing_lines"]) for r in rows if not left_out(r)
    ]
    bounds = srt.chunk(cues, target=target)
    out_dir = work / "chunks"
    out_dir.mkdir(exist_ok=True)
    (work / "out").mkdir(exist_ok=True)
    info = []
    total = len(bounds)
    names = {f"chunk_{k:02d}.txt" for k in range(1, total + 1)}
    for old in out_dir.iterdir():
        if old.name not in names:
            old.unlink()
    for k, (first, last) in enumerate(bounds, 1):
        path = out_dir / f"chunk_{k:02d}.txt"
        # An agent may be reading the old file: write a new one and swap it
        # in, so a reader sees the old text or the new, never half of one.
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f"# chunk {k:02d} of {total:02d}, cues {first}-{last}\n")
            f.write("# src = text to translate; en = English cross-check; [..] = speaker hint\n")
            f.write("# ' / ' separates the source's own lines\n")
            f.write("# [on-screen text] = text on screen the timing file lacks, from other tracks or the picture;")
            f.write(" 'also' = the same line in other tracks\n\n")
            for r in rows[first - 1 : last]:
                if left_out(r):
                    continue
                hint = ON_SCREEN_MARK if r.get("on_screen") else speaker_hint(speakers.get(str(r["n"]), {}))
                head = f"#{r['n']} {r['ts'][:8]}" + (f" [{hint}]" if hint else "")
                f.write(head + "\n")
                f.write("src: " + _one_line(r["source"]) + "\n")
                if r["en"] is not None and r["en"] != r["source"]:
                    f.write("en: " + _one_line(r["en"]) + "\n")
                for lang, lines in (r.get("on_screen") or {}).items():
                    if lines != r["source"]:
                        f.write(f"also: {lang}: " + _one_line(lines) + "\n")
                f.write("\n")
        _swap(tmp, path)
        info.append({"chunk": k, "file": str(path), "first": first, "last": last, "out": str(work / "out" / f"tr_{k:02d}.txt")})
    (work / "chunks.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def _swap(tmp: Path, path: Path, tries: int = 20) -> None:
    """Replace path with tmp. Windows refuses while another program has the
    file open, so try again for about two seconds."""
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--work", type=result.path, required=True)
    b.add_argument("--timing", type=result.path, required=True)
    b.add_argument("--source", type=result.path, help="original-language file, if the timing file is in another language")
    b.add_argument("--en", type=result.path, help="English file for cross-check and speaker labels")
    b.add_argument(
        "--keep-bible-check",
        action="store_true",
        help="keep the bible check's files: the rebuild only shifts the times of the same cues",
    )
    b.add_argument(
        "--hi",
        choices=HI_MODES,
        default="remove",
        help="hearing-impaired sound descriptions and speaker labels: remove them (default) or keep them",
    )
    b.add_argument(
        "--track",
        type=track_arg,
        action="append",
        default=[],
        help="LANG=PATH: another subtitle file of this film, to find on-screen text the timing file lacks (repeatable)",
    )
    b.add_argument(
        "--forced-track",
        type=track_arg,
        action="append",
        default=[],
        help="LANG=PATH: a forced track of the same video as the timing file, taken without a shift (repeatable)",
    )
    b.add_argument(
        "--shift-ms",
        type=int,
        help="the sync rebuild: the files are the earlier build's moved by N ms; on-screen entries move with them",
    )
    b.add_argument("--timing-language", help="the timing file's language, to count the other languages the tracks hold")
    b.add_argument(
        "--screen",
        type=result.path,
        help="W/screen/readings.json from `screen.py collect`: build again with what the picture showed",
    )
    g = sub.add_parser("songs")
    g.add_argument("--work", type=result.path, required=True)
    g.add_argument("--mode", choices=SONG_MODES, default="story")
    c = sub.add_parser("chunks")
    c.add_argument("--work", type=result.path, required=True)
    c.add_argument("--target", type=int, default=250)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "build":
        summary = build(
            a.work,
            a.timing,
            a.source,
            a.en,
            a.keep_bible_check,
            a.hi,
            a.track,
            a.forced_track,
            a.shift_ms,
            a.timing_language,
            a.screen,
        )
        result.emit(summary, a.result)
    elif a.cmd == "songs":
        result.emit(songs(a.work, a.mode), a.result)
    else:
        result.emit(chunks(a.work, a.target), a.result)


if __name__ == "__main__":
    main()
