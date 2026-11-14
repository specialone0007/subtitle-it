# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Assemble the Turkish file, run the checks, build the reviewer's file and
deliver the result next to the video.

    uv run assemble.py check       --work W
    uv run assemble.py sidebyside  --work W
    uv run assemble.py deliver     --work W --dest FILM.srt --backups DIR [--force] [--video FILM.mkv]
    uv run assemble.py where       --work W --cues 12,340
    uv run assemble.py fixround    --work W --round r1

`check` reads W/out/tr_*.txt, then W/out/fix_*.txt in the order they were
written (later files win; in a polish run fix_review.txt also wins over
fix_polish.txt, as if written later), writes W/draft.tr.srt when every cue
has text, and writes W/checks.json. When a cue is missing or a file is malformed, no draft is
written and any older draft is removed. Hard fails block delivery; warnings do
not, and nothing without a current draft is ever delivered.

The checks go cue for cue with the timing file. The draft is the file as
it will be delivered: laid out by layout.py (at most two lines of 42
characters, a long two-speaker cue split into one cue per speaker),
without the cues that hold only sounds, and numbered from 1. W/cue_map.json
maps each draft number to the timing file's cue; `deliver` keeps it as
W/delivered_map.json, and `where` answers from it which delivered cues and
times a timing cue became.

`fixround` writes, per chunk with a hard fail, W/fixes/<round>_<NN>.txt:
each failing cue with its checks, its source and its current Turkish, so a
fix round edits what is there instead of translating the cue again.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402
import layout  # noqa: E402
import prepare  # noqa: E402
import result  # noqa: E402
import srt  # noqa: E402
import turkish  # noqa: E402

MAX_LINE = layout.MAX_LINE
MAX_CPS = layout.MAX_CPS
MAP_FILE = "cue_map.json"
DELIVERED_MAP_FILE = "delivered_map.json"
INFINITIVE_RE = re.compile(r"^[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(mak|mek)[.!]$")
CAPS_RE = re.compile(r"\b(TAMAM|HAYIR)\b")
ITALIC_RE = re.compile(r"</?i>", re.I)
ITALIC_SPAN_RE = re.compile(r"<i>(.*?)</i>", re.I | re.S)
WORDISH_RE = re.compile(r"\w")


def word_italics(lines: list[str]) -> bool:
    """The cue's italics sit on single words only, with plain words beside
    them: `<i>To</i> all Marc Antony's cavalry`, `We've gotten <i>off</i>
    to a bad start`. That is mostly a slip in the source file, and at best
    stress on one word, which Turkish puts on another word or none. So a
    Turkish cue without them is fine, and one with them only gets a
    warning. Italics on a whole line, or on more than one word, still must
    match the source."""
    text = " ".join(lines)
    spans = ITALIC_SPAN_RE.findall(text)
    if not spans or len(ITALIC_RE.findall(text)) != 2 * len(spans):
        return False
    if not all(WORDISH_RE.search(s) and len(srt.strip_tags(s).split()) == 1 for s in spans):
        return False
    return bool(WORDISH_RE.search(srt.strip_tags(ITALIC_SPAN_RE.sub(" ", text))))


def fix_order(out: Path) -> list[Path]:
    """W/out/fix_*.txt in the order they apply. Fix files apply in the order
    they were written, so a fix round after the review wins over
    fix_review.txt whatever the files are called. One exception: in a polish
    run the fixer and the reviewer work at the same time, and where both
    write a cue the reviewer's version wins, since the reviewer reads the
    whole film and fixes a flagged cue's flags too when it rewrites one. So
    fix_review.txt applies right after fix_polish.txt even when it was
    written first, as if it were the later file."""
    files = list(out.glob("fix_*.txt"))
    polish = out / "fix_polish.txt"
    polish_at = polish.stat().st_mtime_ns if polish.exists() else -1

    def key(p: Path) -> tuple[int, int, str]:
        at = p.stat().st_mtime_ns
        if p.name == "fix_review.txt":
            return (max(at, polish_at), 1, p.name)
        return (at, 0, p.name)

    return sorted(files, key=key)


def load_translation(work: Path) -> tuple[dict[int, list[str]], list[str]]:
    out = work / "out"
    texts: dict[int, list[str]] = {}
    problems: list[str] = []
    seen_in_tr: set[int] = set()
    for f in sorted(out.glob("tr_*.txt")):
        blocks, probs = srt.read_blocks(f)
        problems += probs
        for n in blocks:
            if n in seen_in_tr:
                problems.append(f"cue {n} is in more than one chunk file")
            seen_in_tr.add(n)
        texts.update(blocks)
    for f in fix_order(out):
        blocks, probs = srt.read_blocks(f)
        problems += probs
        texts.update(blocks)
    return texts, problems


def _cps(text: str, ms: int) -> float:
    return len(text) / (ms / 1000)


def lay_out(
    kept: list[srt.Cue],
    texts: dict[int, list[str]],
    parts: dict[int, list[layout.Part]],
    sound_only: list[int],
    why: dict[int, str] | None = None,
) -> tuple[list[srt.Cue], dict]:
    """The cues as delivered, numbered from 1, and the map from each
    delivered number to the timing file's cue. A cue the layout split
    becomes several delivered cues, each with its part number; a cue left
    whole keeps its timestamp line exactly as written."""
    shown: list[srt.Cue] = []
    where: dict[str, dict] = {}
    for c in kept:
        pieces = parts.get(c.n) or [layout.Part(c.start, c.end, texts[c.n])]
        for k, p in enumerate(pieces, 1):
            n = len(shown) + 1
            ts = c.ts if len(pieces) == 1 else f"{srt.fmt_ms(p.start)} --> {srt.fmt_ms(p.end)}"
            shown.append(srt.Cue(n=n, start=p.start, end=p.end, ts=ts, lines=p.lines))
            where[str(n)] = {"cue": c.n} if len(pieces) == 1 else {"cue": c.n, "part": k, "of": len(pieces)}
    # `sound_only` lists every cue left out, whatever the reason; `why`
    # names the reason for the ones that are not sound descriptions.
    return shown, {"cues": where, "sound_only": sound_only, "why": {str(n): w for n, w in (why or {}).items()}}


def read_map(work: Path, delivered: bool = True) -> dict | None:
    """The cue map of the delivered file (or, with delivered=False, of the
    current draft), or None when there is none: a film delivered by an
    older version, whose cues are the timing file's cues one for one."""
    path = work / (DELIVERED_MAP_FILE if delivered else MAP_FILE)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def where(work: Path, cues: list[int]) -> list[dict]:
    """Where cues of the timing file are in the delivered file (or in the
    draft before delivery): delivered numbers and times, or that the cue
    was left out (sound only, a bare sound or a song)."""
    cue_map = read_map(work) or read_map(work, delivered=False)
    path = work / ("delivered.tr.srt" if (work / DELIVERED_MAP_FILE).exists() else "draft.tr.srt")
    shown = {c.n: c for c in srt.parse(path)[0]} if path.exists() else {}
    if cue_map is None:
        cue_map = {"cues": {str(n): {"cue": n} for n in shown}, "sound_only": []}
    back: dict[int, list[int]] = {}
    for d, info in cue_map["cues"].items():
        back.setdefault(info["cue"], []).append(int(d))
    out = []
    for n in cues:
        if n in cue_map["sound_only"]:
            reason = LEFT_OUT_NOTES.get(cue_map.get("why", {}).get(str(n), ""), "sound only")
            out.append({"cue": n, "delivered": [], "note": f"{reason}: not in the delivered file"})
            continue
        ds = sorted(back.get(n, []))
        out.append({"cue": n, "delivered": ds, "at": [shown[d].ts[:12] for d in ds if d in shown]})
    return out


def _build_info(work: Path) -> dict:
    build_file = work / "build.json"
    return json.loads(build_file.read_text(encoding="utf-8")) if build_file.exists() else {}


def hi_mode(work: Path) -> str:
    """How `prepare.py build` treated hearing-impaired text: remove or keep."""
    return _build_info(work).get("hearing_impaired_tags", "keep")


LEFT_OUT_NOTES = {"sound": "a bare sound, left out", "song": "a song left out"}


def left_out_why(rows: dict[int, dict]) -> dict[int, str]:
    """The cues left out for a reason other than sound descriptions: a bare
    sound ("Oh.") or a song not translated, by `prepare.py`."""
    return {n: r["left_out"] for n, r in rows.items() if r.get("left_out") and not r.get("sound_only")}


def sound_only_cues(work: Path, rows: dict[int, dict]) -> set[int]:
    """The cues that get no translation and are not delivered: those whose
    text holds only sound descriptions and labels, and those `prepare.py`
    left out as a bare sound or a song. The build marks them; with `remove`
    the text is cleaned again here, so a cue that an older build kept (a
    description running over two lines) is caught too. Turkish text for
    these cues is never delivered."""
    marked = {n for n, r in rows.items() if r.get("sound_only") or r.get("left_out")}
    info = _build_info(work)
    if info.get("hearing_impaired_tags", "keep") != "remove":
        return marked
    flags = info.get("hearing_impaired", {})
    hi_timing = flags.get("timing", True)
    hi_source = flags.get("source", hi_timing)
    for n, r in rows.items():
        if n in marked:
            continue
        timing_left, _, found_timing = srt.strip_hi(r.get("timing_lines") or [], hi_timing)
        source_left, _, found_source = srt.strip_hi(r.get("source") or [], hi_source)
        if (found_timing or found_source) and not timing_left and not source_left:
            marked.add(n)
    return marked


def hi_problems(lines: list[str], tagged: bool) -> list[tuple[str, str]]:
    """Hearing-impaired text in a Turkish cue. Square brackets are always
    one. A speaker label at the start of a line, or a description in
    parentheses, is one only when the source cue had tags removed
    (`tagged`): elsewhere "BÖLÜM 1: ..." or "(Orada mısın?)" is text. A cue
    left with no words once cleaned is one too."""
    out = []
    for ln in lines:
        plain = srt.strip_tags(ln)
        label = srt.clean_line(ln, hi=True).label
        if label and (tagged or re.match(r"\s*(?:-\s*)?\[", plain)):
            out.append(("speaker label", f"remove the label '{label}': {ln}"))
        elif srt.SQUARE_RE.search(plain):
            out.append(("sound description", f"remove the description in square brackets: {ln}"))
        elif tagged and srt.paren_descriptions(ln):
            out.append(("sound description", f"remove the description in parentheses: {ln}"))
    if not out and lines and not srt.strip_hi(lines, tagged)[0]:
        out.append(("sound description", "the cue is only a sound description"))
    return out


# A sentence that runs over more cues than this is a song or a list, not a
# sentence a translator could have spread wrongly.
MAX_SENTENCE_CUES = 6
SENTENCE_END_RE = re.compile(r"[.?!][\"'”’)\]]*$")
STOP_WORDS = {"bir", "şey", "ile", "çok", "daha", "için", "gibi", "ama", "ben", "sen", "biz", "siz", "onu", "ona", "var",
              "yok", "değil", "kadar", "olan", "her", "hiç", "neden", "nasıl"}  # fmt: skip


def _source_lines(row: dict) -> list[str]:
    return [srt.strip_tags(ln).strip() for ln in (row.get("en") or row.get("source") or row.get("timing_lines") or [])]


def _runs_on(lines: list[str]) -> bool:
    """The cue's sentence goes on in the next cue: a line ends without a
    full stop, a question mark or an exclamation mark ("..." counts as
    going on). In a two-speaker cue any speaker's line may be the one
    that goes on ("- in order to... / - Turn that off.")."""
    ends = [turn[-1] for turn in srt.turns(lines)]
    return any(ln and (ln.endswith(("...", "…")) or not SENTENCE_END_RE.search(ln)) for ln in ends)


def sentence_groups(kept: list[srt.Cue], rows: dict[int, dict]) -> list[list[int]]:
    """Runs of two or more cues that one source sentence spans, in timing
    order. Songs are left out: their lines rarely end in punctuation."""
    groups: list[list[int]] = []
    run: list[int] = []
    for c in kept:
        row = rows.get(c.n, {})
        if row.get("song") or "♪" in " ".join(c.lines):
            run = []
            continue
        run.append(c.n)
        if not _runs_on(_source_lines(row)):
            if 2 <= len(run) <= MAX_SENTENCE_CUES:
                groups.append(run)
            run = []
    if 2 <= len(run) <= MAX_SENTENCE_CUES:
        groups.append(run)
    return groups


def _pairs(text: str) -> set[tuple[str, str]]:
    """Neighbouring word pairs, without the short words any sentence repeats."""
    words = [turkish.lower(w) for w in turkish.WORD_RE.findall(srt.strip_tags(text))]
    return {(a, b) for a, b in zip(words, words[1:]) if len(a) >= 3 and len(b) >= 3 and not {a, b} & STOP_WORDS}


def _content_words(text: str) -> set[str]:
    return {w.casefold() for w in turkish.WORD_RE.findall(text) if len(w) >= 4} - EN_STOP_WORDS


EN_STOP_WORDS = {"that", "this", "what", "with", "have", "your", "from", "they", "them", "there", "about", "just", "like",
                 "would", "could", "been", "were", "when", "then", "than", "into", "some", "will", "know"}  # fmt: skip
# A capitalised source word that is the first word of its line may be any
# word; a name is told apart by appearing in the Turkish as it is.
NAME_RE = re.compile(r"(?<![\w'’])[A-Z][a-z]{2,}")


def split_sentence_problems(group: list[int], texts: dict[int, list[str]], rows: dict[int, dict]) -> list[str]:
    """What goes wrong when a sentence spread over `group` was placed
    badly: a cue whose Turkish says nothing for its source part, the same
    words in two cues (one part written twice) where the source of those
    two cues shares no word, or a name written in another cue than the one
    that says it."""
    problems = []
    src = {n: " ".join(_source_lines(rows.get(n, {}))) for n in group}
    tr = {n: srt.strip_tags(" ".join(texts.get(n, []))) for n in group}
    for n in group:
        tr_words, src_words = turkish.WORD_RE.findall(tr[n]), turkish.WORD_RE.findall(src[n])
        if not tr_words and src_words:
            problems.append(f"cue {n} has no words for its part")
        elif len(tr_words) == 1 and len(src_words) >= 5:
            problems.append(f"cue {n} has one word for {len(src_words)} source words")
    seen: dict[tuple[str, str], int] = {}
    for n in group:
        for pair in sorted(_pairs(tr[n])):
            first = seen.setdefault(pair, n)
            if first != n and not _content_words(src[first]) & _content_words(src[n]):
                problems.append(f'"{" ".join(pair)}" is in cue {first} and cue {n}')
    for name in sorted({m.group() for n in group for m in NAME_RE.finditer(src[n])}):
        said = [n for n in group if re.search(rf"(?<!\w){name}(?!\w)", src[n])]
        written = [n for n in group if re.search(rf"(?<!\w){name}", tr[n])]
        if len(said) == 1 and written and said[0] not in written:
            problems.append(f'"{name}" is said in cue {said[0]} but written in cue {written[0]}')
    return problems


def run_checks(work: Path) -> dict:
    timing, _ = srt.parse(work / "timing.srt")
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts, problems = load_translation(work)
    remove_hi = hi_mode(work) == "remove"
    hard: list[dict] = []
    warn: list[dict] = []

    def h(n, check, detail=""):
        hard.append({"cue": n, "check": check, "detail": detail})

    def w(n, check, detail=""):
        warn.append({"cue": n, "check": check, "detail": detail})

    for p in problems:
        h(None, "file format", p)
    sound_only = sound_only_cues(work, rows)
    kept = [c for c in timing if c.n not in sound_only]
    valid = {c.n for c in kept}
    for n in sorted(set(texts) - valid - sound_only):
        h(n, "cue count", "cue number not in the timing file")
    # Text for a cue that holds only sounds, or that was left out, is
    # rejected: never delivered.
    left_why = left_out_why(rows)
    for n in sorted(set(texts) & sound_only):
        if n in left_why:
            w(n, "left-out cue", f"{LEFT_OUT_NOTES[left_why[n]]}; this text is rejected and not delivered")
        else:
            w(n, "sound-only cue", "the source has only sound descriptions here; this text is rejected and not delivered")
    missing = [c.n for c in kept if c.n not in texts]
    for n in missing:
        h(n, "cue count", "missing")

    gap = layout.usual_gap(kept)
    parts: dict[int, list[layout.Part]] = {}
    for c in kept:
        tr = texts.get(c.n)
        if tr is None:
            continue
        if not any(ln.strip() for ln in tr):
            h(c.n, "cue count", "empty")
            continue
        src = c.lines
        ref = rows[c.n]["en"] or rows[c.n]["source"] or src
        src_italic, tr_italic = bool(ITALIC_RE.search("".join(src))), bool(ITALIC_RE.search("".join(tr)))
        if src_italic and word_italics(src):
            if tr_italic:
                w(
                    c.n,
                    "stray italics",
                    "the source has italics on one word only, mostly a slip in its file: drop them unless that word is stressed",
                )
        elif src_italic != tr_italic:
            h(c.n, "italic tags", "source and Turkish differ")
        if srt.dash_lines(src) != srt.dash_lines(tr):
            h(c.n, "dialogue dashes", f"source {srt.dash_lines(src)}, Turkish {srt.dash_lines(tr)}")
        if remove_hi:
            for check, detail in hi_problems(tr, bool(rows[c.n].get("tags_removed"))):
                h(c.n, check, detail)
        parts[c.n], why = layout.plan(c.start, c.end, tr, gap)
        if why:
            long = [ln for ln in tr if len(srt.strip_tags(ln)) > MAX_LINE]
            check = "lines per cue" if len(tr) > layout.MAX_LINES or not long else "line length"
            h(c.n, check, f"{len(tr)} lines, longest {max(len(srt.strip_tags(ln)) for ln in tr)} chars; {why}")
        tr_plain = srt.strip_tags(" ".join(tr)).strip()
        ref_plain = srt.strip_tags(" ".join(ref)).strip()
        tr_cps, ref_cps = _cps(tr_plain, c.duration), _cps(ref_plain, c.duration)
        # Netflix Turkish style guide I.17: 17 characters a second at most,
        # whatever the source does. The viewer reads Turkish.
        if tr_cps > MAX_CPS:
            w(c.n, "reading speed", f"{tr_cps:.1f} chars/s, source {ref_cps:.1f}")
        if len(tr) == 1 and INFINITIVE_RE.match(srt.strip_tags(tr[0]).strip()):
            w(c.n, "infinitive command", tr[0])
        for ln in tr:
            if CAPS_RE.search(ln):
                w(c.n, "caps", ln)
        for word, meant in turkish.accent_slips(" ".join(tr)):
            w(c.n, "accent", f'"{word}": probably {meant}')
        for word, right in turkish.spelling_slips(" ".join(tr)):
            w(c.n, "spelling", f'"{word}": the TDK writes "{right}"')
        for word, right in turkish.name_suffix_slips(" ".join(tr)):
            w(c.n, "name suffix", f'"{word}": the name ends in another sound when said; write "{right}"')

    glossary_file = work / "glossary.json"
    if glossary_file.exists():
        glossary = json.loads(glossary_file.read_text(encoding="utf-8"))
        for preferred, alts in glossary.items():
            for alt in alts:
                # A variant that differs from the preferred term only by case
                # (TAMAM for Tamam) is matched case-sensitively; otherwise the
                # correct term itself would be flagged.
                if alt.casefold() == preferred.casefold():
                    rx, fold = re.compile(r"\b" + re.escape(alt) + r"\b"), False
                else:
                    rx, fold = re.compile(r"\b" + re.escape(alt.casefold()) + r"\b"), True
                hits = [n for n, t in texts.items() if rx.search(" ".join(t).casefold() if fold else " ".join(t))]
                for n in hits:
                    w(n, "term variant", f"'{alt}' used; glossary says '{preferred}'")

    # One rendering per term across the film: the bible's Turkish for each
    # source term it decided, and one spelling for words that have two.
    drafted = {c.n: texts[c.n] for c in kept if c.n in texts}
    renderings = bible.term_renderings(work)
    for c in kept:
        if c.n not in drafted:
            continue
        said = " ".join(_source_lines(rows[c.n])).casefold()
        for term, answers in sorted(renderings.items()):
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?:s|es|ed|ing|'s)?(?!\w)", said) and not any(
                turkish.has_rendering(" ".join(drafted[c.n]), a) for a in answers
            ):
                w(c.n, "term rendering", f"'{term}' is '{' or '.join(sorted(answers))}' in the bible; this cue has no form of it")
    bible_words = " ".join(a for answers in renderings.values() for a in answers)
    for n, used, usual, count in turkish.family_drift(drafted, bible_words):
        w(n, "term drift", f"'{used}' here, '{usual}' in {count} other cues: use one form for the whole film")

    # A sentence spread over several cues: each part must appear exactly once.
    for group in sentence_groups(kept, rows):
        if not all(n in drafted for n in group):
            continue
        problems = split_sentence_problems(group, drafted, rows)
        if problems:
            detail = (
                f"cues {group[0]}-{group[-1]} are one source sentence: {'; '.join(problems)}. "
                "Translate the whole sentence first, then spread it so each part appears exactly once"
            )
            for n in group:
                w(n, "split sentence", detail)

    warn += bible.address_warnings(work, texts, rows)

    shown: list[srt.Cue] = []
    if not missing and not any(x["check"] == "file format" for x in hard):
        shown, cue_map = lay_out(kept, texts, parts, sorted(sound_only), left_why)
        srt.write(work / "draft.tr.srt", shown)
        (work / MAP_FILE).write_text(json.dumps(cue_map, indent=1), encoding="utf-8")
        back, _ = srt.parse(work / "draft.tr.srt")
        if len(back) != len(shown):
            h(None, "cue count", f"draft has {len(back)} cues, the layout {len(shown)}")
        for a, b in zip(shown, back):
            if a.ts != b.ts:
                h(cue_map["cues"][str(a.n)]["cue"], "timestamps", f"{a.ts} became {b.ts}")
        draft = str(work / "draft.tr.srt")
    else:
        draft = None
        (work / "draft.tr.srt").unlink(missing_ok=True)
        (work / MAP_FILE).unlink(missing_ok=True)

    result = {
        "draft": draft,
        "cues": len(timing),
        "sound_only_cues": len(sound_only) - len(left_why),
        "bare_sounds_left_out": sum(1 for v in left_why.values() if v == "sound"),
        "songs_left_out": sum(1 for v in left_why.values() if v == "song"),
        "delivered_cues": len(shown),
        "split_cues": sum(1 for p in parts.values() if len(p) > 1),
        "translated": len(set(texts) & valid),
        "hard_fail_count": len(hard),
        "warning_count": len(warn),
        "hard": hard,
        "warnings": warn,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    (work / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def sidebyside(work: Path) -> Path:
    """Compact file for the whole-film reviewer: number, speaker, source,
    Turkish, one cue per line, tabs between fields."""
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    speakers = json.loads((work / "speakers.json").read_text(encoding="utf-8"))
    texts, _ = load_translation(work)
    # A run seeded from an existing Turkish file (polish.py writes
    # polish_placement.json) had no translators handing over, so no joins
    # to mark, even when the bible writer's chunks.json exists.
    chunks_file = work / "chunks.json"
    seeded = (work / "polish_placement.json").exists()
    chunks = json.loads(chunks_file.read_text(encoding="utf-8")) if chunks_file.exists() and not seeded else []
    joins = {c["first"] for c in chunks[1:]}
    sound_only = sound_only_cues(work, {r["n"]: r for r in rows})
    path = work / "sidebyside.tsv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("n\tspeaker\tsource\tturkish\n")
        for r in rows:
            n = r["n"]
            if n in sound_only:
                continue
            if n in joins:
                f.write(f"# --- chunk join before cue {n} ---\n")
            who = prepare.speaker_hint(speakers.get(str(n), {}))
            src = " / ".join(r["source"] or r["timing_lines"])
            tr = " / ".join(texts.get(n, ["<MISSING>"]))
            f.write(f"{n}\t{who}\t{src}\t{tr}\n")
    return path


FIX_DIR = "fixes"
ROUND_RE = re.compile(r"^[a-z0-9]+$")
NO_TURKISH = "<none: write this cue>"


def fix_round(work: Path, label: str) -> dict:
    """Hand a fix round its cues: the hard fails of the last `check`,
    grouped by chunk. For each chunk with a failing cue it writes
    W/fixes/<label>_<NN>.txt with each cue's failed checks, its source and
    the Turkish it has now (the chunk output or seed with every fix file
    applied, as `check` reads it), so the translator edits that text
    instead of translating the cue again. The files sit outside W/out:
    `check` reads only W/out, and `deliver` refuses W/out files newer than
    the check."""
    if not ROUND_RE.match(label):
        raise SystemExit("--round takes a short label of lowercase letters and digits, such as r1 or post")
    checks = json.loads((work / "checks.json").read_text(encoding="utf-8"))
    failed: dict[int, list[str]] = {}
    no_cue = []
    for x in checks["hard"]:
        if x["cue"] is None:
            no_cue.append(x["detail"])
        else:
            failed.setdefault(x["cue"], []).append(x["check"] + (f" ({x['detail']})" if x["detail"] else ""))
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts, _ = load_translation(work)
    chunks_file = work / "chunks.json"
    chunks = json.loads(chunks_file.read_text(encoding="utf-8")) if chunks_file.exists() else []
    if not chunks:
        chunks = [{"chunk": 1, "file": None, "first": min(rows, default=1), "last": max(rows, default=1)}]
    fix_dir = work / FIX_DIR
    fix_dir.mkdir(exist_ok=True)
    for old in fix_dir.glob(f"{label}_*.txt"):
        old.unlink()
    groups = []
    for ch in chunks:
        cues = sorted(n for n in failed if ch["first"] <= n <= ch["last"])
        if not cues:
            continue
        nn = f"{ch['chunk']:02d}"
        path = fix_dir / f"{label}_{nn}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# fix round {label}, chunk {nn}: {len(cues)} cues\n")
            f.write("# fail = what the check found; src/en = the source; now = the Turkish this cue has now.\n")
            f.write("# Start from `now`: change only what the failed check needs, keep the rest word for word.\n\n")
            for n in cues:
                row = rows.get(n, {})
                f.write(f"#{n}\n")
                for fail in failed[n]:
                    f.write(f"fail: {fail}\n")
                f.write("src: " + prepare._one_line(row.get("source") or row.get("timing_lines")) + "\n")
                if row.get("en") is not None and row.get("en") != row.get("source"):
                    f.write("en: " + prepare._one_line(row["en"]) + "\n")
                f.write("now:\n" + "\n".join(texts.get(n) or [NO_TURKISH]) + "\n\n")
        groups.append(
            {
                "chunk": nn,
                "chunk_file": ch["file"],
                "fix_file": str(path),
                "write_to": str(work / "out" / f"fix_{label}_{nn}.txt"),
                "flags_to": str(work / "out" / f"flags_{label}_{nn}.txt"),
                "cues": cues,
            }
        )
    # A cue no chunk holds: one the timing file does not have.
    covered = {n for g in groups for n in g["cues"]}
    outside = sorted(set(failed) - covered)
    return {"round": label, "cues": len(failed), "chunks": groups, "outside_chunks": outside, "no_cue": no_cue}


UTF8_BOM = b"\xef\xbb\xbf"


def _old_file_kind(work: Path, dest: Path) -> str:
    """What the file already at the destination is: this work folder's
    earlier delivery, another Turkish file, or a file in another language
    (an English `Film.srt` beside `Film.mkv`, say). Each is moved to the
    backups folder; the last one the run report names. The path alone
    does not make a file the earlier delivery: the user may have put an
    English file there since, so it must also hold Turkish."""
    turkish = srt.looks_turkish(dest)
    if turkish and srt.path_key(dest) in srt.all_delivered_paths(work):
        return "earlier delivery"
    return "Turkish" if turkish else "not Turkish"


def _backup_name(backups: Path, path: Path) -> Path:
    """A new name in the backups folder: the file's stem, the time, a
    counter when two land in the same second, so no backup is written over."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    named = backups / f"{path.stem}.{stamp}{path.suffix}"
    count = 1
    while named.exists() or named.with_name(named.name + ".map.json").exists():
        count += 1
        named = backups / f"{path.stem}.{stamp}-{count}{path.suffix}"
    return named


def earlier_beside(work: Path, dest: Path, video: Path) -> list[Path]:
    """This plugin's earlier deliveries of this video still next to it under
    another name than `dest` (`Film.tr.srt` from before 0.6.2, from this
    work folder, another one or the pre-rename plugin). Only files named
    after the video, in its folder, that still hold Turkish: one the user
    has since replaced with another language is theirs."""
    known = srt.all_delivered_paths(work)
    out = []
    for p in sorted(video.parent.glob(f"{glob.escape(video.stem)}.*")):
        key = srt.path_key(p)
        if key in known and key != srt.path_key(dest) and p.is_file() and srt.looks_turkish(p):
            out.append(p)
    return out


def deliver(work: Path, dest: Path, backups: Path, force: bool, video: Path | None = None) -> dict:
    """Write the draft to `dest`, moving any file already there to
    `backups`. With `video` (the run delivers to the default place, the
    video's own name), this plugin's earlier deliveries of that video under
    another name go to `backups` too and are listed under
    `moved_earlier_deliveries`; without it, files beside `dest` stay put."""
    checks = json.loads((work / "checks.json").read_text(encoding="utf-8"))
    draft = work / "draft.tr.srt"
    if not checks.get("draft") or not draft.exists():
        # Even --force never ships a draft the last check did not write.
        raise SystemExit("the last check wrote no draft (a cue is missing or a file is malformed): fix it and run check again")
    if checks["hard_fail_count"] and not force:
        raise SystemExit(f"{checks['hard_fail_count']} hard fails; deliver with --force only if the user agreed")
    checked = (work / "checks.json").stat().st_mtime
    if any(f.stat().st_mtime > checked for f in (work / "out").glob("*.txt")):
        raise SystemExit("translation files changed after the last check: run check again")
    backed_up = None
    old_file = None
    old_info_file = work / "delivered.json"
    old_info = json.loads(old_info_file.read_text(encoding="utf-8")) if old_info_file.exists() else {}
    earlier = [p for p in srt.delivered_paths(old_info) if srt.path_key(p) != srt.path_key(dest)]
    moved = []
    if video is not None:
        for p in earlier_beside(work, dest, video):
            backups.mkdir(parents=True, exist_ok=True)
            to = _backup_name(backups, p)
            shutil.move(p, to)
            moved.append({"from": str(p), "to": str(to)})
        gone = {srt.path_key(m["from"]) for m in moved}
        earlier = [p for p in earlier if srt.path_key(p) not in gone]
    if dest.exists():
        old_file = _old_file_kind(work, dest)
        backups.mkdir(parents=True, exist_ok=True)
        backed_up = _backup_name(backups, dest)
        # When the old file is this folder's earlier delivery, its cue map
        # goes with it, so the backup's numbers can still be traced to the
        # timing file's cues.
        old_map = work / DELIVERED_MAP_FILE
        if old_info and old_map.exists():
            if old_info.get("sha256") == hashlib.sha256(dest.read_bytes()).hexdigest():
                shutil.copyfile(old_map, backed_up.with_name(backed_up.name + ".map.json"))
        shutil.move(dest, backed_up)
    # With a BOM, TVs that read the file next to the video show ş, ğ and ı
    # instead of guessing a Western code page.
    data = draft.read_bytes()
    if not data.startswith(UTF8_BOM):
        data = UTF8_BOM + data
    dest.write_bytes(data)
    (work / "delivered.tr.srt").write_bytes(data)
    shutil.copyfile(work / MAP_FILE, work / DELIVERED_MAP_FILE)
    info = {
        "delivered_to": str(dest),
        # Paths delivered before under another name, still next to the
        # video: `sources.py local` must not take them as sources either.
        "earlier_deliveries": earlier,
        # Earlier deliveries under another name moved to the backups folder
        # by this delivery: the run report names them.
        "moved_earlier_deliveries": moved,
        "backup_of_old_file": str(backed_up) if backed_up else None,
        "old_file": old_file,
        "sha256": hashlib.sha256(data).hexdigest(),
        "delivered_at": datetime.now().isoformat(timespec="seconds"),
        "hard_fails_at_delivery": checks["hard_fail_count"],
        "warnings_at_delivery": checks["warning_count"],
    }
    (work / "delivered.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    shutil.rmtree(work / "chunks", ignore_errors=True)
    return info


def _summary(result: dict) -> dict:
    by_check: dict[str, int] = {}
    for x in result["hard"] + result["warnings"]:
        by_check[x["check"]] = by_check.get(x["check"], 0) + 1
    return {
        "draft": result["draft"],
        "cues": result["cues"],
        "sound_only_cues": result["sound_only_cues"],
        "bare_sounds_left_out": result["bare_sounds_left_out"],
        "songs_left_out": result["songs_left_out"],
        "delivered_cues": result["delivered_cues"],
        "split_cues": result["split_cues"],
        "translated": result["translated"],
        "hard_fails": result["hard_fail_count"],
        "warnings": result["warning_count"],
        "by_check": by_check,
        # Every cue with no Turkish, by number: first_hard_fails stops at 30.
        "missing_cues": [x["cue"] for x in result["hard"] if x["check"] == "cue count" and x["detail"] == "missing"],
        "first_hard_fails": result["hard"][:30],
    }


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "sidebyside"):
        s = sub.add_parser(name)
        s.add_argument("--work", type=result.path, required=True)
    d = sub.add_parser("deliver")
    d.add_argument("--work", type=result.path, required=True)
    d.add_argument("--dest", type=result.path, required=True)
    d.add_argument("--backups", type=result.path, required=True)
    d.add_argument("--force", action="store_true")
    d.add_argument("--video", type=result.path, help="the film; pass it only when --dest is the default name next to it")
    wh = sub.add_parser("where")
    wh.add_argument("--work", type=result.path, required=True)
    wh.add_argument("--cues", required=True, help="comma-separated cue numbers of the timing file")
    fr = sub.add_parser("fixround")
    fr.add_argument("--work", type=result.path, required=True)
    fr.add_argument("--round", required=True, help="the round's label: r1, r2, r3, post")
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "check":
        result.emit(_summary(run_checks(a.work)), a.result)
    elif a.cmd == "sidebyside":
        result.emit({"sidebyside": str(sidebyside(a.work))}, a.result)
    elif a.cmd == "where":
        try:
            numbers = [int(x) for x in a.cues.split(",") if x.strip()]
        except ValueError as e:
            raise SystemExit("--cues takes cue numbers separated by commas") from e
        result.emit(where(a.work, numbers), a.result)
    elif a.cmd == "fixround":
        result.emit(fix_round(a.work, a.round), a.result)
    else:
        result.emit(deliver(a.work, a.dest, a.backups, a.force, a.video), a.result)


if __name__ == "__main__":
    main()
