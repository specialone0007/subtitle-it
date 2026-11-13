# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Build a film's work folder and cut it into chunks for the translators.

    uv run prepare.py build  --work W --timing T [--source S] [--en E] [--keep-bible-check] [--hi remove|keep]
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
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import srt  # noqa: E402

# Labels that name no one in particular: kept out of the hints. The label
# forms themselves ("SANDRA:", "[Sandra] Hi.") are read by srt.clean_line.
NOT_NAMES = {"MAN", "WOMAN", "BOTH", "ALL", "MUSIC", "LAUGHS", "SIGHS", "NARRATOR", "CROWD", "VOICE", "TV", "RADIO"}
HI_MODES = ("remove", "keep")


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
) -> dict:
    if hi not in HI_MODES:
        raise SystemExit(f"--hi is one of {', '.join(HI_MODES)}")
    remove = hi == "remove"
    work.mkdir(parents=True, exist_ok=True)
    # A new build starts a new translation: an earlier run's translations,
    # fixes, draft, checks and speaker labels must never be read into this
    # one: the new timing file may number its cues differently.
    shutil.rmtree(work / "out", ignore_errors=True)
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

    src_pairs = None
    if source_path and source_path.resolve() != timing_path.resolve():
        repairs["source"] = []
        source, _ = srt.parse(source_path, repairs["source"])
        src_pairs = srt.pair(timing, source)
        hearing_impaired["source"] = srt.hearing_impaired(source)["hearing_impaired"]
    en_pairs = None
    if en_path and en_path.resolve() != timing_path.resolve():
        repairs["en"] = []
        en, _ = srt.parse(en_path, repairs["en"])
        en_pairs = srt.pair(timing, en)
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
        sound_only = remove and (f1 or f2) and not timing_said and not src_lines
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
        if f1 or f2 or f3:
            # The check reads this: a label or a description in parentheses
            # in the Turkish is a fail only where the source had tags.
            row["tags_removed"] = True
        if sound_only:
            row["sound_only"] = True
            dropped += 1
        elif srt.is_lyric(said):
            # The source text decides, and the timing text only when the
            # source has none here: speech in the source stays speech even
            # where the timing file shows a lyric. Which songs are
            # translated is decided after the bible, by `songs`.
            row["song"] = True
            songs += 1
        elif (
            srt.is_bare_sound(said)
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
            if src_pairs is not None and not src_lines:
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
        "repairs": {name: len(found) for name, found in repairs.items()},
        "warnings": [
            f"the {name} file is malformed; repairs made while reading it: {len(found)} (first: {found[0]})"
            for name, found in repairs.items()
            if found
        ],
    }
    (work / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


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
            f.write("# ' / ' separates the source's own lines\n\n")
            for r in rows[first - 1 : last]:
                if left_out(r):
                    continue
                hint = speaker_hint(speakers.get(str(r["n"]), {}))
                head = f"#{r['n']} {r['ts'][:8]}" + (f" [{hint}]" if hint else "")
                f.write(head + "\n")
                f.write("src: " + _one_line(r["source"]) + "\n")
                if r["en"] is not None and r["en"] != r["source"]:
                    f.write("en: " + _one_line(r["en"]) + "\n")
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
    g = sub.add_parser("songs")
    g.add_argument("--work", type=result.path, required=True)
    g.add_argument("--mode", choices=SONG_MODES, default="story")
    c = sub.add_parser("chunks")
    c.add_argument("--work", type=result.path, required=True)
    c.add_argument("--target", type=int, default=250)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "build":
        result.emit(build(a.work, a.timing, a.source, a.en, a.keep_bible_check, a.hi), a.result)
    elif a.cmd == "songs":
        result.emit(songs(a.work, a.mode), a.result)
    else:
        result.emit(chunks(a.work, a.target), a.result)


if __name__ == "__main__":
    main()
