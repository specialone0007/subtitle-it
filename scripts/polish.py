# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Start from a Turkish subtitle that already exists, instead of translating
every line.

    uv run polish.py seed  --work W --tr TURKISH.srt
    uv run polish.py flags --work W
    uv run polish.py soft  --work W

Run after `prepare.py build`, with a Turkish file that `srt.py fit` accepted
(shifted first when its offset was not 0). The film keeps its own timing
file, so the bible, the voices and the checks work on the same cue numbers
as in a full run.

`seed` puts the Turkish text on the timing file's cues by time and writes it
to W/out/tr_00.txt, as if a translator had written it. A cue no Turkish line
lands on gets no text, so `check` reports it as missing. Two Turkish cues on
one timing cue are joined and, when that makes more than two lines, rewrapped.

`flags` runs the same checks as `assemble.py check` and lists the cues that
need a fix, with their English and Turkish text, in W/polish_flags.txt for
the fixer, who writes W/out/fix_polish.txt. Reading speed is left to the
reviewer, as in a full run, since a professional file exceeds it often.
Where a cue has the wrong sen or siz, the cues of the same scene that use
that form are listed too, when the bible cannot say whom they address.

`soft` runs after the reviewer and lists the cues whose Turkish is still
softer than the source's swearing, in W/polish_soft.txt, for one more
fixer pass and for the report.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble  # noqa: E402
import bible  # noqa: E402
import layout  # noqa: E402
import prepare  # noqa: E402
import result  # noqa: E402
import srt  # noqa: E402

SEED_FILE = "tr_00.txt"
FLAG_FILE = "polish_flags.txt"
FIX_FILE = "fix_polish.txt"
PLACEMENT_FILE = "polish_placement.json"
SOFT_FILE = "polish_soft.txt"
SOFT_FIX_FILE = "fix_soft.txt"
# Warnings the fixer leaves to the reviewer, as a full run does.
REVIEWER_ONLY = {"reading speed"}
# Text for a sound-only cue is never delivered: nothing for the fixer to do.
NOT_FOR_FIXER = REVIEWER_ONLY | {"sound-only cue"}
# A cue with no Turkish at all. Its flag and its tr: line say so in words a
# fixer cannot read past: a skipped one is a hard fail and a fix round.
MISSING_FLAG = "cue count: missing: this cue has no Turkish yet; write it, translated from en: or src:"
NO_TURKISH = "<none: write this cue>"
# A pause longer than this between two cues starts a new scene. A
# professional file keeps one form through a scene, so where the address
# check finds the wrong form on one cue, the same form on the cues around it
# is likely wrong too, though the check could not tell who speaks them.
SCENE_GAP_MS = 6000
WORD_RE = re.compile(r"[^\W\d_]+")
# Professional Turkish files often tone down crude and sexual lines, which
# breaks "swearing at the same strength as the source". Two strengths: an
# English word from the strong list needs a strong Turkish word, so "fuck"
# is not matched by "lanet olsun"; a word from the mild list needs a word
# from either Turkish list. A cue that falls short goes to the fixer. Short
# on purpose: the reviewer still reads the whole film. Word starts only, so
# "cocktail", "götürmek", "boks" and "kahraman" do not match.
EN_STRONG_RE = re.compile(
    r"(?<![^\W\d_])(?:fuck|motherfuck|cunt|cocks?(?![^\W\d_])|cocksucker|pussy|twat|dickhead|"
    r"whore|slut|blowjob|handjob|jerk(?:ing)? off|wanker)",
    re.I,
)
EN_MILD_RE = re.compile(
    r"(?<![^\W\d_])(?:shit|bullshit|bitch|bastard|asshole|dumbass|jackass|goddamn|damn|crap|piss|"
    r"prick(?!l)|penis|vagina|dildo|porn|tits|boobs|masturbat|horny|orgasm|sex)",
    re.I,
)
TR_STRONG_RE = re.compile(
    r"(?<![^\W\d_])(?:sik(?![iı]nt)|s[i*.]ktir|hassiktir|amk|amın|amcık|yarra|taşak|orospu|"
    r"piç|göt(?!ür)|sürtük|kaltak|puşt|sakso|otuzbir)",
    re.I,
)
TR_MILD_RE = re.compile(
    r"(?<![^\W\d_])(?:bok(?!s)|kahr(?:et|ol)|lanet|şerefsiz|fahişe|penis|vajina|seks|porno|meme|"
    r"mastürbasyon|azgın|orgazm|pipi|çük|yatmak|yatt|işe(?:mek|yece|di))",
    re.I,
)


def _all_italic(lines: list[str]) -> bool:
    return bool(lines) and all(re.fullmatch(r"\s*<i>.*</i>\s*", ln, re.I) and ln.lower().count("<i>") == 1 for ln in lines)


def match_form(src: list[str], tr: list[str]) -> tuple[list[str], bool]:
    """Give the Turkish lines the source cue's italics and dialogue dashes
    when that is a mechanical change: italics on the same whole lines,
    dashes on two lines where the source has two speakers, or no dashes
    where the source has none. Professional files differ from the timing
    file in these marks often, and they are not a translation question.
    Anything mixed is left for the checks to flag. Returns the lines and
    whether they changed."""
    out = list(tr)
    src_italic = bool(assemble.ITALIC_RE.search("".join(src)))
    tr_italic = bool(assemble.ITALIC_RE.search("".join(out)))
    if src_italic and not tr_italic:
        if _all_italic(src):
            out = [f"<i>{ln.strip()}</i>" for ln in out]
        elif len(src) == len(out):
            out = [f"<i>{t.strip()}</i>" if _all_italic([s]) else t for s, t in zip(src, out)]
    elif tr_italic and not src_italic:
        out = [assemble.ITALIC_RE.sub("", ln).strip() for ln in out]
    if srt.dash_lines(src) == 2 and len(out) == 2 and srt.dash_lines(out) == 0:
        out = [re.sub(r"^(<i>)?", lambda m: (m.group(1) or "") + "- ", ln, count=1) for ln in out]
    elif srt.dash_lines(src) == 0 and srt.dash_lines(out):
        out = [re.sub(r"^(<i>)?\s*-\s*", lambda m: m.group(1) or "", ln, count=1) for ln in out]
    return out, out != tr


def one_part_per_speaker(src: list[str], parts: list[srt.Cue]) -> bool:
    """The timing cue has two or more speakers and the Turkish cues on it
    are one per speaker, none with a dash of its own."""
    turns = srt.turns(src)
    return len(turns) >= 2 and len(parts) == len(turns) and not any(srt.dash_lines(o.lines) for o in parts)


def _dashed(line: str) -> str:
    return re.sub(r"^(\s*(?:<i>)?)\s*", lambda m: m.group(1).strip() + "- ", line, count=1)


def seed(work: Path, tr_path: Path) -> dict:
    timing, _ = srt.parse(work / "timing.srt")
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    # Cues that hold only sounds get no Turkish: a Turkish line there goes
    # to a spoken neighbour or is listed as placed nowhere.
    sound_only = assemble.sound_only_cues(work, rows)
    timing = [c for c in timing if c.n not in sound_only]
    turkish, enc = srt.parse(tr_path)
    if not turkish:
        raise SystemExit(f"no cues found in {tr_path}")
    tags_removed = 0
    if assemble.hi_mode(work) == "remove":
        # Parentheses and labels in capitals go only when the Turkish file
        # itself is a hearing-impaired one.
        tr_hi = srt.hearing_impaired(turkish)["hearing_impaired"]
        for o in turkish:
            o.lines, _, found = srt.strip_hi(o.lines, tr_hi)
            tags_removed += found
        turkish = [o for o in turkish if o.lines]
    pairs = srt.pair(timing, turkish)
    used = {id(o) for v in pairs.values() for o in v}
    placement = {"joined": [], "unplaced": []}
    starts = [c.start for c in timing]
    for o in turkish:
        if id(o) in used:
            continue
        # The timing cues just before and after a Turkish line that landed
        # nowhere: songs and on-screen text often end up there.
        k = bisect.bisect_left(starts, o.start)
        near = [timing[i].n for i in (k - 1, k) if 0 <= i < len(timing)]
        placement["unplaced"].append({"near": near, "text": prepare._one_line(o.lines)})
    out = work / "out"
    out.mkdir(exist_ok=True)
    seeded = joined = rewrapped = reformed = 0
    with open(out / SEED_FILE, "w", encoding="utf-8") as f:
        for c in timing:
            parts = pairs[c.n]
            if not parts:
                continue
            lines = [ln for o in parts for ln in o.lines if ln.strip()]
            if len(parts) > 1:
                joined += 1
                placement["joined"].append(c.n)
                if one_part_per_speaker(c.lines, parts):
                    # A two-speaker cue a delivery split at the speaker
                    # change: each part is one speaker's turn again.
                    lines = [_dashed(layout.one_line(o.lines)) for o in parts]
                elif len(lines) > 2:
                    lines = srt.wrap(" ".join(ln.strip() for ln in lines), assemble.MAX_LINE)
                    rewrapped += 1
            lines, changed = match_form(c.lines, lines)
            reformed += changed
            seeded += 1
            f.write(f"{c.n}\n" + "\n".join(lines) + "\n\n")
    (work / PLACEMENT_FILE).write_text(json.dumps(placement, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "file": str(out / SEED_FILE),
        "turkish_encoding": enc,
        "cues": len(timing),
        "seeded": seeded,
        "without_turkish": len(timing) - seeded,
        "turkish_cues_with_tags_or_labels_removed": tags_removed,
        "joined": joined,
        "rewrapped": rewrapped,
        "form_matched": reformed,
        "turkish_cues_unused": sum(1 for o in turkish if id(o) not in used),
    }


def _words(lines: list[str] | None) -> list[str]:
    return [w.casefold() for w in WORD_RE.findall(srt.strip_tags(" ".join(lines or [])))]


def untranslated(tr: list[str], en: list[str] | None) -> bool:
    """The Turkish line repeats the English one word for word. Two words at
    least, so a name or an "OK" on its own is not flagged."""
    a, b = _words(tr), _words(en)
    return len(a) >= 2 and a == b


def toned_down(tr: list[str], en: list[str] | None) -> str | None:
    """The English word that has no counterpart as strong in the Turkish
    line, or None."""
    en_text = srt.strip_tags(" ".join(en or []))
    tr_text = srt.strip_tags(" ".join(tr))
    strong = bool(TR_STRONG_RE.search(tr_text))
    m = EN_STRONG_RE.search(en_text)
    if m and not strong:
        return m.group(0).lower()
    m = EN_MILD_RE.search(en_text)
    if m and not strong and not TR_MILD_RE.search(tr_text):
        return m.group(0).lower()
    return None


def _toned_down_label(word: str) -> str:
    return f'toned down: the English says "{word}", the Turkish has nothing as strong'


def _write_flags(path: Path, header: str, reasons: dict[int, list[str]], rows: dict, texts: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n\n")
        for n in sorted(reasons):
            r = rows[n]
            f.write(f"#{n} {r['ts'][:8]}\n")
            f.write("src: " + prepare._one_line(r["source"]) + "\n")
            if r["en"] is not None and r["en"] != r["source"]:
                f.write("en: " + prepare._one_line(r["en"]) + "\n")
            f.write("tr: " + (prepare._one_line(texts.get(n)) if n in texts else NO_TURKISH) + "\n")
            for label in reasons[n]:
                f.write(f"flag: {label}\n")
            f.write("\n")


def scenes(rows: dict[int, dict]) -> dict[int, int]:
    """Scene number for each cue: a new scene starts after a pause of more
    than SCENE_GAP_MS."""
    out: dict[int, int] = {}
    scene, last_end = 0, None
    for r in sorted(rows.values(), key=lambda r: (r["start"], r["n"])):
        if last_end is not None and r["start"] - last_end > SCENE_GAP_MS:
            scene += 1
        out[r["n"]] = scene
        last_end = r["end"] if last_end is None else max(last_end, r["end"])
    return out


def scene_address(readings: list[dict], rows: dict[int, dict]) -> dict[int, str]:
    """Cues in the same scene as a wrong address form that use the same
    form, where the bible gives no form to check them against. Cues the
    address check flags itself, and cues whose form matches the bible, are
    left out. Returns a label for each cue."""
    scene_of = scenes(rows)
    wrong: dict[tuple[int, str], dict] = {}
    for r in readings:
        if bible.address_off(r) and r["cue"] in scene_of:
            wrong.setdefault((scene_of[r["cue"]], r["got"]), r)
    out: dict[int, str] = {}
    for r in readings:
        hit = wrong.get((scene_of.get(r["cue"]), r["got"]))
        if hit is None or r["expected"] is not None:
            continue
        out[r["cue"]] = (
            f"address form, same scene: cue {hit['cue']} ({hit['speaker']} → {hit['listener'] or 'anyone here'}) "
            f"uses {hit['got']} where the bible says "
            f"{hit['expected']}; check who is spoken to here"
        )
    return out


def flags(work: Path) -> dict:
    checks = assemble.run_checks(work)
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts, _ = assemble.load_translation(work)
    reasons: dict[int, list[str]] = {}
    missing: list[int] = []
    # A sound-only cue's Turkish is rejected and not delivered, so nothing
    # about it goes to the fixer: no glossary or address-form warning either.
    sound_only = assemble.sound_only_cues(work, rows)
    for item in checks["hard"] + [w for w in checks["warnings"] if w["check"] not in NOT_FOR_FIXER]:
        # A fix file can name a cue the timing file does not have; check
        # already reports that as a hard fail, and there is no cue to list.
        if item["cue"] is not None and item["cue"] in rows and item["cue"] not in sound_only:
            label = item["check"] + (f": {item['detail']}" if item["detail"] else "")
            if item["check"] == "cue count" and item["detail"] == "missing":
                label = MISSING_FLAG
                missing.append(item["cue"])
            reasons.setdefault(item["cue"], []).append(label)
    for n, tr in texts.items():
        if n not in rows or n in sound_only:
            continue
        en = rows[n]["en"] or rows[n]["source"]
        if untranslated(tr, en):
            reasons.setdefault(n, []).append("untranslated: same words as the English")
        word = toned_down(tr, en)
        if word:
            reasons.setdefault(n, []).append(_toned_down_label(word))
    for n, label in scene_address(bible.address_readings(work, texts, rows), rows).items():
        if n not in sound_only:
            reasons.setdefault(n, []).append(label)
    placement_file = work / PLACEMENT_FILE
    if placement_file.exists():
        placement = json.loads(placement_file.read_text(encoding="utf-8"))
        for n in placement["joined"]:
            if n in rows:
                reasons.setdefault(n, []).append(
                    "placement: two Turkish cues were joined here; check none belongs to a neighbour"
                )
        for item in placement["unplaced"]:
            for n in item["near"]:
                if n in rows:
                    reasons.setdefault(n, []).append(f"placement: a Turkish line nearby landed on no cue: {item['text']}")
    by_check: dict[str, int] = {}
    for labels in reasons.values():
        for label in {lab.split(":")[0] for lab in labels}:
            by_check[label] = by_check.get(label, 0) + 1
    header = f"# {len(reasons)} cues to fix. Write each fixed cue to out/{FIX_FILE} as: number, then its lines."
    if missing:
        verb = "has" if len(missing) == 1 else "have"
        header += (
            f"\n# {len(missing)} of them {verb} no Turkish yet (tr: {NO_TURKISH}). Every one must be in"
            f" your file, or the check fails: {', '.join(map(str, sorted(missing)))}"
        )
    _write_flags(work / FLAG_FILE, header, reasons, rows, texts)
    return {
        "file": str(work / FLAG_FILE),
        "cues": checks["cues"],
        "flagged": len(reasons),
        "missing": len(missing),
        "missing_cues": sorted(missing),
        "by_check": dict(sorted(by_check.items(), key=lambda kv: -kv[1])),
        "reading_speed_left_to_reviewer": sum(1 for w in checks["warnings"] if w["check"] == "reading speed"),
    }


def soft(work: Path) -> dict:
    """The cues still softer than the source after every fix so far,
    written to W/polish_soft.txt in the flags format, for one more fixer
    pass and for the report."""
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts, _ = assemble.load_translation(work)
    reasons: dict[int, list[str]] = {}
    for n, tr in texts.items():
        if n in rows:
            word = toned_down(tr, rows[n]["en"] or rows[n]["source"])
            if word:
                reasons[n] = [_toned_down_label(word)]
    header = f"# {len(reasons)} cues still softer than the source. Write each fixed cue to out/{SOFT_FIX_FILE}."
    _write_flags(work / SOFT_FILE, header, reasons, rows, texts)
    return {"file": str(work / SOFT_FILE), "left": len(reasons), "cue_numbers": sorted(reasons)}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="put the Turkish text on the timing file's cues")
    s.add_argument("--work", type=result.path, required=True)
    s.add_argument("--tr", type=result.path, required=True)
    f = sub.add_parser("flags", help="list the cues the fixer must change")
    f.add_argument("--work", type=result.path, required=True)
    t = sub.add_parser("soft", help="list the cues still softer than the source after the fixes")
    t.add_argument("--work", type=result.path, required=True)
    result.add_argument(p)
    a = result.parse(p, argv)
    commands = {"seed": lambda: seed(a.work, a.tr), "flags": lambda: flags(a.work), "soft": lambda: soft(a.work)}
    out = commands[a.cmd]()
    result.emit(out, a.result)


if __name__ == "__main__":
    main()
