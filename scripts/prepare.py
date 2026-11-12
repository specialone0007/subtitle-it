# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Build a film's work folder and cut it into chunks for the translators.

    uv run prepare.py build  --work W --timing T [--source S] [--en E] [--keep-bible-check]
    uv run prepare.py chunks --work W [--target 250]

`build` writes W/timing.srt (UTF-8 copy of the timing file, timestamps kept
character for character), W/cues.json (per cue: timing, source text, English
cross-check, speaker label) and W/speakers.json (labels found in the text).
`chunks` writes W/chunks/chunk_NN.txt, the files translators read. It can
run again while an agent reads them: each file is replaced whole.

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

# "SANDRA:", "- SANDRA:" or "[SANDRA]:" at the start of a line. A bracket
# without a colon ("[DOOR SLAMS]") is a sound, not a speaker, so it is ignored.
LABEL_RE = re.compile(r"^(?:-\s*)?[\[(]?([A-ZÀ-ÝĞİŞ][A-ZÀ-ÝĞİŞ .'\-]{1,30})[\])]?:\s")
NOT_NAMES = {"MAN", "WOMAN", "BOTH", "ALL", "MUSIC", "LAUGHS", "SIGHS", "NARRATOR", "CROWD", "VOICE", "TV", "RADIO"}


def labels_in(lines: list[str]) -> list[str]:
    found = []
    for ln in lines:
        m = LABEL_RE.match(srt.strip_tags(ln).strip())
        if m:
            name = m.group(1).strip()
            if name not in NOT_NAMES:
                found.append(name.title())
    return found


def cue_label(lines: list[str]) -> str | None:
    """The speaker label for a cue. A cue with two or more dash lines
    ("- Who?" / "- IVY: Me.") holds several speakers, so it gets one name
    per dash line, "?" where a line has none: "? / Ivy". A line without a
    dash continues the dash line above it."""
    turns: list[list[str]] = []
    for ln in lines:
        if srt.is_dash_line(ln) or not turns:
            turns.append([])
        turns[-1].append(ln)
    if srt.dash_lines([t[0] for t in turns]) < 2:
        found = labels_in(lines)
        return found[0] if found else None
    names = [(labels_in(t) or ["?"])[0] for t in turns]
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


def build(work: Path, timing_path: Path, source_path: Path | None, en_path: Path | None, keep_bible_check: bool = False) -> dict:
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
    timing, enc = srt.parse(timing_path)
    if not timing:
        raise SystemExit(f"no cues found in {timing_path}")
    srt.write(work / "timing.srt", timing)

    src_pairs = None
    if source_path and source_path.resolve() != timing_path.resolve():
        source, _ = srt.parse(source_path)
        src_pairs = srt.pair(timing, source)
    en_pairs = None
    if en_path and en_path.resolve() != timing_path.resolve():
        en, _ = srt.parse(en_path)
        en_pairs = srt.pair(timing, en)

    speakers: dict[str, dict] = {}

    rows, unpaired = [], 0
    for c in timing:
        src_lines = c.lines if src_pairs is None else [ln for o in src_pairs[c.n] for ln in o.lines]
        if src_pairs is not None and not src_lines:
            unpaired += 1
        en_lines = None
        if en_path is not None:
            en_lines = c.lines if en_pairs is None else [ln for o in en_pairs[c.n] for ln in o.lines]
        label = cue_label(src_lines) or cue_label(en_lines or [])
        if label:
            speakers[str(c.n)] = {"label": label}
        rows.append(
            {
                "n": c.n,
                "ts": c.ts,
                "start": c.start,
                "end": c.end,
                "timing_lines": c.lines,
                "source": src_lines,
                "en": en_lines,
            }
        )

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
    }
    (work / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def _one_line(lines: list[str] | None) -> str:
    return " / ".join(ln.strip() for ln in lines) if lines else ""


def chunks(work: Path, target: int) -> list[dict]:
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    speakers = json.loads((work / "speakers.json").read_text(encoding="utf-8"))
    cues = [srt.Cue(n=r["n"], start=r["start"], end=r["end"], ts=r["ts"], lines=r["timing_lines"]) for r in rows]
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
    c = sub.add_parser("chunks")
    c.add_argument("--work", type=result.path, required=True)
    c.add_argument("--target", type=int, default=250)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "build":
        result.emit(build(a.work, a.timing, a.source, a.en, a.keep_bible_check), a.result)
    else:
        result.emit(chunks(a.work, a.target), a.result)


if __name__ == "__main__":
    main()
