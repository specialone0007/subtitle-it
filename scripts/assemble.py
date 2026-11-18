# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Assemble the Turkish file, run the checks, build the reviewers' files and
deliver the result next to the video.

    uv run assemble.py check       --work W
    uv run assemble.py reviewparts --work W [--size 250]
    uv run assemble.py reviews     --work W
    uv run assemble.py deliver     --work W --dest FILM.srt --backups DIR [--force] [--video FILM.mkv]
                                   [--no-credit] [--credit-name NAME]
    uv run assemble.py where       --work W --cues 12,340
    uv run assemble.py fixround    --work W --round r1
    uv run assemble.py listenparts --work W [--size 480]
    uv run assemble.py listengate  --work W
    uv run assemble.py listencheck --work W
    uv run assemble.py listendrop  --work W --cues 12,340

`check` reads W/out/tr_*.txt, then W/out/fix_*.txt in the order they were
written (later files win; in a polish run fix_review.txt also wins over
fix_polish.txt, as if written later), writes W/draft.tr.srt when every cue
has text, and writes W/checks.json. When a cue is missing or a file is malformed, no draft is
written and any older draft is removed. Hard fails block delivery; warnings do
not, and nothing without a current draft is ever delivered.

The checks go cue for cue with the timing file. The draft is the film's
lines as they will be delivered: laid out by layout.py (at most two lines
of 42 characters, a long two-speaker cue split into one cue per speaker),
without the cues that hold only sounds, and numbered from 1. The delivered
file is the draft plus, unless --no-credit, one credit cue before the
first line (when the silence allows it) and one after the story's last
line, before any end title shown as on-screen text (inside the video's
length when --video gives a video ffprobe can read).
W/cue_map.json maps each draft number to the timing file's cue; `deliver`
writes it as W/delivered_map.json, numbered around the credit cues,
which are listed under "credits", and `where` answers
from it which delivered cues and times a timing cue became.

`reviewparts` cuts the film into parts of about 250 cues for the review,
each in W/review/part_<NN>.tsv with a few cues of context on each side and
each cue's automatic notes; `reviews` joins the parts' notes into
W/review.md.

In a polish run, `check` also lists every cue whose sen or siz differs
from the human file's line, with the reason its fix file gave on an
`#address:` line; a change with no reason is a warning.

`listenparts` cuts the spoken cues into parts for the listeners, who read
the final Turkish alone, as a viewer would, and fix lines that do not
sound like the character speaking Turkish. `listengate` drops each edit
that breaks a check or its cue's budget, `listencheck` lists the kept
edits for a meaning check, and `listendrop` drops edits on cues the last
check fails. In a polish run the listener reads the whole film but changes
only the lines the run wrote: a cue that still says the human file's line
is marked `human` and an edit to it is dropped.

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
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402
import layout  # noqa: E402
import prepare  # noqa: E402
import result  # noqa: E402
import sources  # noqa: E402
import srt  # noqa: E402
import turkish  # noqa: E402

MAX_LINE = layout.MAX_LINE
MAX_CPS = layout.MAX_CPS
MAP_FILE = "cue_map.json"
TURKISH_ONLY_FAST = "only the Turkish is fast"
DELIVERED_MAP_FILE = "delivered_map.json"
INFINITIVE_RE = re.compile(r"^[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(mak|mek)[.!]$")
CAPS_RE = re.compile(r"\b(TAMAM|HAYIR)\b")
ITALIC_RE = re.compile(r"</?i>", re.I)
ITALIC_SPAN_RE = re.compile(r"<i>(.*?)</i>", re.I | re.S)
WORDISH_RE = re.compile(r"\w")
# A spoken line that starts with "Ve", as an English "And" does: Turkish
# drops it or says "Hadi", "Bir de", "-da/-de".
VE_OPENING_RE = re.compile(r"^\s*(?:<i>)?\s*(?:-\s*)?(?:<i>)?Ve\s")


def word_italics(lines: list[str]) -> bool:
    """The cue's italics sit on single words only, with plain words beside
    them: `<i>To</i> all Marc Antony's cavalry`, `We've gotten <i>off</i>
    to a bad start`. That is mostly a slip in the source file, and at best
    stress on one word, which Turkish puts on another word or none. So a
    Turkish cue without them is fine, and one with them only gets a
    warning. Italics on a whole line, or on more than one word, still must
    match the source: a line whose words are all in italics, such as one
    speaker's off-screen `- <i>Hello?</i>` beside a plain second line, is
    a whole italic line, not a stray word."""
    text = " ".join(lines)
    spans = ITALIC_SPAN_RE.findall(text)
    if not spans or len(ITALIC_RE.findall(text)) != 2 * len(spans):
        return False
    if not all(WORDISH_RE.search(s) and len(srt.strip_tags(s).split()) == 1 for s in spans):
        return False
    for ln in lines:
        if ITALIC_SPAN_RE.search(ln) and not WORDISH_RE.search(srt.strip_tags(ITALIC_SPAN_RE.sub(" ", ln))):
            return False
    return bool(WORDISH_RE.search(srt.strip_tags(ITALIC_SPAN_RE.sub(" ", text))))


REVIEW_FIX_RE = re.compile(r"^fix_review(?:_\d+)?\.txt$")
LISTEN_FIX_RE = re.compile(r"^fix_listen_\d+\.txt$")
LISTEN_CHECK_FIX = "fix_listencheck.txt"
LISTEN_BEFORE = "listen_before.json"


def fix_order(out: Path) -> list[Path]:
    """W/out/fix_*.txt in the order they apply. Fix files apply in the order
    they were written, so a fix round after the review wins over
    fix_review.txt whatever the files are called. One exception: in a polish
    run the fixer and the reviewer work at the same time, and where both
    write a cue the reviewer's version wins, since a part's reviewer reads
    every line of its part and fixes a flagged cue's flags too when it
    rewrites one. So fix_review.txt applies right after fix_polish.txt even
    when it was written first, as if it were the later file. The review's parts
    (fix_review_<NN>.txt) count as fix_review.txt; they hold different
    cues.

    The listener's files (fix_listen_<NN>.txt, then fix_listencheck.txt)
    apply after every fix file `listenparts` recorded in
    W/out/listen_before.json, by name, whatever their file times: the
    listener edited the Turkish those files make. A fix file written after
    `listenparts` and not recorded there still wins by time, after them."""
    files = list(out.glob("fix_*.txt"))
    polish = out / "fix_polish.txt"
    polish_at = polish.stat().st_mtime_ns if polish.exists() else -1
    before = out / LISTEN_BEFORE
    recorded = set(json.loads(before.read_text(encoding="utf-8"))["fix_files"]) if before.exists() else None
    listened_at = before.stat().st_mtime_ns if before.exists() else 0

    def key(p: Path) -> tuple[int, int, int, str]:
        at = p.stat().st_mtime_ns
        base = (max(at, polish_at), 1, p.name) if REVIEW_FIX_RE.match(p.name) else (at, 0, p.name)
        if recorded is None or p.name in recorded:
            return (0, *base)
        if LISTEN_FIX_RE.match(p.name):
            return (1, 0, 0, p.name)
        if p.name == LISTEN_CHECK_FIX:
            return (1, 1, 0, p.name)
        return (2, *base) if at > listened_at else (0, *base)

    return sorted(files, key=key)


def load_translation(work: Path) -> tuple[dict[int, list[str]], list[str]]:
    """The Turkish now: the chunk files (or the polish seed), then every fix
    file in the order they apply."""
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


def polish_seed(work: Path) -> dict[int, list[str]] | None:
    """In a polish run, the human file's lines as they were placed on the
    timing file (W/out/tr_00.txt); None in any other run."""
    seed_file = work / "out" / "tr_00.txt"
    if not (work / "polish_placement.json").exists() or not seed_file.exists():
        return None
    return srt.read_blocks(seed_file)[0]


def address_changes(work: Path, texts: dict[int, list[str]]) -> list[dict]:
    """In a polish run, every cue whose sen or siz now differs from the
    human file's line it was seeded with, with the fix file that changed it
    last and the latest reason any fix file gave for that cue (`#address:`
    lines), or None. A later file that keeps the new form, such as the soft
    pass, writes no reason and must not hide the one given before."""
    out = work / "out"
    seed = polish_seed(work)
    if seed is None:
        return []
    by: dict[int, tuple[str, str | None]] = {}
    for f in fix_order(out):
        blocks, _ = srt.read_blocks(f)
        reasons = srt.read_reasons(f)
        for n in blocks:
            by[n] = (f.name, reasons.get(n) or (by[n][1] if n in by else None))
    found = []
    for n in sorted(texts):
        if n not in seed or n not in by:
            continue
        was, now = bible.detect_form(" ".join(seed[n])), bible.detect_form(" ".join(texts[n]))
        if was and now and was != now:
            found.append({"cue": n, "human": was, "now": now, "file": by[n][0], "reason": by[n][1]})
    return found


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
    whole keeps its timestamp line exactly as written, unless it stays on
    screen longer (`layout.available_end`): then its start stays as written
    and its end is the new one."""
    shown: list[srt.Cue] = []
    where: dict[str, dict] = {}
    for c in kept:
        pieces = parts.get(c.n) or [layout.Part(c.start, c.end, texts[c.n])]
        for k, p in enumerate(pieces, 1):
            n = len(shown) + 1
            if len(pieces) > 1:
                ts = f"{srt.fmt_ms(p.start)} --> {srt.fmt_ms(p.end)}"
            elif p.end != c.end:
                ts = f"{c.ts.split('-->')[0].strip()} --> {srt.fmt_ms(p.end)}"
            else:
                ts = c.ts
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
ON_SCREEN_MARK = prepare.ON_SCREEN_MARK


def on_screen_entries(work: Path) -> list[dict]:
    """The rows of W/on_screen.json, or none for a work folder built before
    it existed."""
    path = work / prepare.ON_SCREEN_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


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
    these cues is never delivered. A cue that is on-screen text is never
    taken for a sound by the cleaning."""
    marked = {n for n, r in rows.items() if r.get("sound_only") or r.get("left_out")}
    info = _build_info(work)
    if info.get("hearing_impaired_tags", "keep") != "remove":
        return marked
    flags = info.get("hearing_impaired", {})
    hi_timing = flags.get("timing", True)
    hi_source = flags.get("source", hi_timing)
    for n, r in rows.items():
        if n in marked or r.get("on_screen"):
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


def _says_term(said: str, term: str) -> bool:
    """The casefolded source text says the term, in any common English form."""
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?:s|es|ed|ing|'s)?(?!\w)", said))


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


# A source line of one word ("No, no, no.", "Go!") is said again with
# another meaning too often to ask for one wording. Two words already
# carry a chant ("...a thought...") or a callback ("A gift.").
REPEAT_MIN_WORDS = 2


def _distinct(words: list[str]) -> tuple[str, ...]:
    """Each word once, in the order said: "No, no, no" and "No!" say the same."""
    return tuple(dict.fromkeys(words))


def _repeat_key(row: dict) -> tuple | None:
    """The source line as its words, casefolded and each once, and whether
    it runs on into the next cue, when it has enough words to be a line the
    film says again on purpose (a chant, a saying, a callback). The text
    the agents translate, not the English cross-check: a hearing-impaired
    file may keep a label there ("BARD:<i>...")."""
    lines = [srt.strip_tags(ln).strip() for ln in (row.get("source") or row.get("en") or row.get("timing_lines") or [])]
    words = _distinct([w.casefold() for w in turkish.WORD_RE.findall(" ".join(lines))])
    return (words, _runs_on(lines)) if len(words) >= REPEAT_MIN_WORDS else None


def _wording(lines: list[str]) -> tuple[str, ...]:
    """The Turkish words of a cue, each once, without tags, case or punctuation."""
    return _distinct([turkish.lower(w) for w in turkish.WORD_RE.findall(srt.strip_tags(" ".join(lines)))])


def repeat_drift(texts: dict[int, list[str]], rows: dict[int, dict], order: list[int]) -> list[tuple[int, int]]:
    """Cues whose source line comes back elsewhere in the film in the same
    words while the Turkish says it another way: (cue, the cue to match).
    Each line has one wording to match, the one most of its cues use (the
    earliest on a tie), and only the cues that say it otherwise are named:
    two reviewers told to match each other could each copy the other and
    still differ. Songs are left out: a chorus is translated as the song
    needs."""
    seen: dict[tuple, list[int]] = {}
    for n in order:
        row = rows.get(n, {})
        key = None if row.get("song") else _repeat_key(row)
        if key:
            seen.setdefault(key, []).append(n)
    out = []
    for cues in seen.values():
        forms = {n: _wording(texts[n]) for n in cues}
        if len(set(forms.values())) < 2:
            continue
        counts = Counter(forms.values())
        ref = max(cues, key=lambda m: (counts[forms[m]], -cues.index(m)))
        out.extend((n, ref) for n in cues if forms[n] != forms[ref])
    return sorted(out)


def run_checks(work: Path, texts: dict[int, list[str]] | None = None, write: bool = True) -> dict:
    """Run every check on the Turkish now (`load_translation`), or on
    `texts` when given. With `write` it writes the draft, the cue map and
    W/checks.json; without, it only returns what it found, so the listener
    gate can check a text before and after its edits."""
    timing, _ = srt.parse(work / "timing.srt")
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    if texts is None:
        texts, problems = load_translation(work)
    else:
        problems = []
    remove_hi = hi_mode(work) == "remove"
    hard: list[dict] = []
    warn: list[dict] = []

    def h(n, check, detail=""):
        hard.append({"cue": n, "check": check, "detail": detail})

    def w(n, check, detail="", **extra):
        warn.append({"cue": n, "check": check, "detail": detail, **extra})

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
    # On-screen text `build` added is never lost on the way: each entry it
    # placed has a cue that is delivered.
    for e in on_screen_entries(work):
        if e.get("state") == "cue" and (e.get("n") not in rows or e["n"] in sound_only):
            h(e.get("n"), "on-screen text", f"entry {e.get('id')} has no cue that is delivered")

    gap = layout.usual_gap(kept)
    by_start = sorted(kept, key=lambda c: (c.start, c.n))
    next_start = {a.n: b.start for a, b in zip(by_start, by_start[1:])}
    parts: dict[int, list[layout.Part]] = {}
    extended = 0
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
        tr_plain = srt.strip_tags(" ".join(tr)).strip()
        ref_plain = srt.strip_tags(" ".join(ref)).strip()
        # A fast cue stays on screen into the silence after it; its speed,
        # and the source's, are measured over the time it is shown.
        end = layout.available_end(c.start, c.end, next_start.get(c.n), gap, len(tr_plain))
        extended += end > c.end
        parts[c.n], why = layout.plan(c.start, c.end, tr, gap, end)
        if why:
            long = [ln for ln in tr if len(srt.strip_tags(ln)) > MAX_LINE]
            check = "lines per cue" if len(tr) > layout.MAX_LINES or not long else "line length"
            h(c.n, check, f"{len(tr)} lines, longest {max(len(srt.strip_tags(ln)) for ln in tr)} chars; {why}")
        shown_ms = max(end - c.start, 1)
        tr_cps, ref_cps = _cps(tr_plain, shown_ms), _cps(ref_plain, shown_ms)
        # Netflix Turkish style guide I.17: 17 characters a second at most,
        # whatever the source does. The viewer reads Turkish.
        if tr_cps > MAX_CPS:
            # The source reads at the limit or under it: only the Turkish
            # is fast, so a shorter wording that keeps the meaning exists
            # more often than not.
            only = f"; {TURKISH_ONLY_FAST}" if ref_cps <= MAX_CPS else ""
            w(c.n, "reading speed", f"{tr_cps:.1f} chars/s, source {ref_cps:.1f}{only}", cps=round(tr_cps, 1))
        if not rows[c.n].get("song") and "♪" not in " ".join(tr) and VE_OPENING_RE.match(tr[0]):
            w(c.n, "ve opening", f"{tr[0]}: an English 'And' opening; drop it or say 'Hadi', 'Bir de', '-da/-de'")
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
        # A family word a pair's decision gives ("abi") is never a wrong
        # variant, even when a generic glossary entry lists it as one.
        family = bible.work_family_words(work)
        for preferred, alts in glossary.items():
            for alt in alts:
                if bible.tr_lower(alt) in family:
                    continue
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
    rules = bible.term_rules(work)
    order = [c.n for c in kept if c.n in drafted]
    for i, n in enumerate(order):
        said = " ".join(_source_lines(rows[n])).casefold()
        heard = [r for r in rules if _says_term(said, r["term"])]
        if not heard:
            continue
        # Turkish puts the verb last, so a term said in one cue of a sentence
        # that runs on may be written in the cue next to it.
        near = [n]
        if i > 0 and _runs_on(_source_lines(rows[order[i - 1]])):
            near.append(order[i - 1])
        if i + 1 < len(order) and _runs_on(_source_lines(rows[n])):
            near.append(order[i + 1])
        text = " ".join(" ".join(drafted[m]) for m in near)
        # A decision that cites this cue for a term said here settles it:
        # "Hold your hats, brothers" has its own decision on that cue.
        cited = set().union(*(r["renderings"] for r in heard if n in r["evidence"]))
        for term in sorted({r["term"] for r in heard}):
            applies = [r for r in heard if r["term"] == term and (r["cues"] is None or n in r["cues"]) and n not in r["except"]]
            if not applies:
                continue
            answers = set().union(*(r["renderings"] for r in applies))
            if not any(turkish.has_rendering(text, a) for a in answers | cited):
                w(n, "term rendering", f"'{term}' is '{' or '.join(sorted(answers))}' in the bible; this cue has no form of it")
    bible_words = " ".join(a for answers in renderings.values() for a in answers)
    for n, used, usual, count in turkish.family_drift(drafted, bible_words):
        w(n, "term drift", f"'{used}' here, '{usual}' in {count} other cues: use one form for the whole film")

    # A line the film says again (a chant, a saying, a callback) is said
    # the same way each time. The note quotes the wording to match first:
    # the reviewer of this cue may not have that part.
    for n, ref in repeat_drift(drafted, rows, order):
        w(n, "repeat drift", f'"{" / ".join(drafted[ref])}" at cue {ref}: same source line, say it this way here too')

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
    # A polish run keeps the human file's sen or siz unless a fix gives its
    # reason; a change with none is a warning.
    changes = address_changes(work, texts)
    for x in changes:
        if not x["reason"]:
            w(x["cue"], "address changed", f"the human file says {x['human']}, now {x['now']}, no reason given ({x['file']})")

    shown: list[srt.Cue] = []
    if not write:
        if not missing and not any(x["check"] == "file format" for x in hard):
            shown, _ = lay_out(kept, texts, parts, sorted(sound_only), left_why)
        draft = None
    elif not missing and not any(x["check"] == "file format" for x in hard):
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
        "extended_cues": extended,
        "translated": len(set(texts) & valid),
        "hard_fail_count": len(hard),
        "warning_count": len(warn),
        "hard": hard,
        "warnings": warn,
        "address_changes": changes,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    if write:
        (work / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


REVIEW_DIR = "review"
# A review part: about this many cues, and this many cues of context on
# each side that the part's reviewer reads but does not change.
PART_CUES = 250
PART_CONTEXT = 20
# A part ends at the longest pause within this many cues of the even cut.
PART_SLACK = 20
# A note in a part file is cut to this many characters: the reviewer
# needs the kind of problem and its key words, not the whole detail.
NOTE_CHARS = 100
FLAG_LINE_RE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?\s*:\s*(.+)$")


def _part_cuts(rows: list[dict], size: int) -> list[int]:
    """Indexes where each part after the first starts: near an even cut,
    at the longest pause between two cues, so a part seldom splits a
    scene or a sentence."""
    k = max(1, -(-len(rows) // size))
    cuts: list[int] = []
    for i in range(1, k):
        even = round(i * len(rows) / k)
        # Start after the previous cut, so no part is empty or out of order.
        lo = max(1, even - PART_SLACK, cuts[-1] + 1 if cuts else 1)
        hi = min(len(rows) - 1, max(lo, even + PART_SLACK))
        cuts.append(max(range(lo, hi + 1), key=lambda j: (rows[j]["start"] - rows[j - 1]["end"], -abs(j - even))))
    return cuts


def _translator_flags(work: Path) -> dict[int, list[str]]:
    """Translator flags by cue, from W/out/flags_*.txt: `n: note` or
    `first-last: note` lines."""
    out: dict[int, list[str]] = {}
    for f in sorted((work / "out").glob("flags_*.txt")):
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = FLAG_LINE_RE.match(ln.strip())
            if not m:
                continue
            a = int(m.group(1))
            b = int(m.group(2) or a)
            for n in range(a, min(b, a + 20) + 1):
                out.setdefault(n, []).append(m.group(3).strip())
    return out


def _fixer_flags(work: Path) -> dict[int, list[str]]:
    """The polish fixer's flags by cue, from W/polish_flags.txt."""
    path = work / "polish_flags.txt"
    out: dict[int, list[str]] = {}
    if not path.exists():
        return out
    n = None
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("#") and ln[1:2].isdigit():
            n = int(ln[1:].split()[0])
        elif n is not None and ln.startswith("flag: "):
            out.setdefault(n, []).append(ln[6:].strip())
    return out


def _note(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= NOTE_CHARS else text[: NOTE_CHARS - 1] + "…"


def _who(row: dict, speakers: dict) -> str:
    """The speaker column of the review and listen part files: `on-screen
    text` for a cue that is text on screen (no one says it), else the
    speaker hint."""
    return ON_SCREEN_MARK if row.get("on_screen") else prepare.speaker_hint(speakers.get(str(row["n"]), {}))


def review_parts(work: Path, size: int = PART_CUES) -> dict:
    """Cut the film into review parts. Each part file lists its cues as
    the side-by-side file does, plus the English when the source is another
    language, and a `notes` field: the check's hard fails and warnings for
    the cue, the polish fixer's flags (the fixer handles those) and the
    translators' flags. PART_CONTEXT cues on each side come first and last,
    marked as context.

    The file is all the film its reviewer reads, so it stays small: a
    reading speed note only where the Turkish alone is fast (the one kind
    the reviewer can fix without losing meaning), no fixer note that a cue
    has no Turkish yet (the Turkish field says `<MISSING>` until the fixer
    writes it), each note once and cut to NOTE_CHARS."""
    if size < 50:
        raise SystemExit("--size takes 50 cues or more")
    all_rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    speakers = json.loads((work / "speakers.json").read_text(encoding="utf-8"))
    texts, _ = load_translation(work)
    by_n = {r["n"]: r for r in all_rows}
    sound_only = sound_only_cues(work, by_n)
    rows = sorted((r for r in all_rows if r["n"] not in sound_only), key=lambda r: (r["start"], r["n"]))
    if not rows:
        raise SystemExit("no spoken cues to review")
    notes: dict[int, list[str]] = {}
    seeded = (work / "polish_placement.json").exists()
    checks_file = work / "checks.json"
    if checks_file.exists():
        checks = json.loads(checks_file.read_text(encoding="utf-8"))
        for hard, items in ((True, checks.get("hard", [])), (False, checks.get("warnings", []))):
            for x in items:
                if x.get("cue") is not None:
                    if x["check"] == "reading speed" and TURKISH_ONLY_FAST not in (x.get("detail") or ""):
                        continue
                    # In a polish run the human file's sen or siz is the
                    # evidence, not the bible: a note against the bible
                    # would only push a reviewer to change it.
                    if seeded and x["check"] == "address form":
                        continue
                    label = x["check"] + (f": {x['detail']}" if x.get("detail") else "")
                    notes.setdefault(x["cue"], []).append(("HARD " if hard else "") + label)
    for n, fl in _fixer_flags(work).items():
        notes.setdefault(n, []).extend(f"fixer: {f}" for f in fl if not f.startswith("cue count: missing"))
    for n, fl in _translator_flags(work).items():
        notes.setdefault(n, []).extend(f"translator: {f}" for f in fl)
    chunks_file = work / "chunks.json"
    chunks = json.loads(chunks_file.read_text(encoding="utf-8")) if chunks_file.exists() and not seeded else []
    joins = {c["first"] for c in chunks[1:]}

    def line(r: dict) -> str:
        n = r["n"]
        who = _who(r, speakers)
        src = prepare._one_line(r["source"] or r["timing_lines"])
        en = prepare._one_line(r["en"]) if r.get("en") and r["en"] != r["source"] else ""
        tr = " / ".join(texts.get(n, ["<MISSING>"]))
        note = " | ".join(dict.fromkeys(_note(x) for x in notes.get(n, [])))
        return f"{n}\t{who}\t{src}\t{en}\t{tr}\t{note}\n"

    def join(r: dict) -> str:
        # Every chunk join is marked, a part's first cue and the context
        # included: parts and chunks both cut at long pauses, so they often
        # start on the same cue.
        return f"# --- chunk join before cue {r['n']} ---\n" if r["n"] in joins else ""

    folder = work / REVIEW_DIR
    folder.mkdir(exist_ok=True)
    for old in folder.glob("part_*"):
        old.unlink()
    for old in (work / "out").glob("fix_review_*.txt"):
        old.unlink()
    bounds = [0, *_part_cuts(rows, size), len(rows)]
    parts = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
        nn = f"{i:02d}"
        path = folder / f"part_{nn}.tsv"
        own = rows[a:b]
        with open(path, "w", encoding="utf-8") as f:
            f.write("n\tspeaker\tsource\ten\tturkish\tnotes\n")
            if a > 0:
                f.write("# --- context before your part: read it, never change it ---\n")
                for r in rows[max(0, a - PART_CONTEXT) : a]:
                    f.write(join(r) + line(r))
            f.write(f"# --- your part: cues {own[0]['n']}-{own[-1]['n']} ---\n")
            for r in own:
                f.write(join(r) + line(r))
            if b < len(rows):
                f.write("# --- context after your part: read it, never change it ---\n")
                for r in rows[b : b + PART_CONTEXT]:
                    f.write(join(r) + line(r))
        parts.append(
            {
                "part": nn,
                "first": own[0]["n"],
                "last": own[-1]["n"],
                "cues": len(own),
                "file": str(path),
                "write_to": str(work / "out" / f"fix_review_{nn}.txt"),
                "notes_to": str(folder / f"part_{nn}.md"),
            }
        )
    fast = sum(1 for v in notes.values() if any(x.startswith("reading speed") and TURKISH_ONLY_FAST in x for x in v))
    return {"parts": parts, "cues": len(rows), "turkish_only_fast": fast}


def join_reviews(work: Path) -> dict:
    """Join the review parts' notes (W/review/part_<NN>.md) into
    W/review.md, in part order, and say which parts wrote none. Once the
    listener ran, a last section says how many of its edits were kept,
    dropped by the gate (by reason) and written back by the meaning check."""
    folder = work / REVIEW_DIR
    tables = sorted(folder.glob("part_*.tsv"))
    out, missing = ["# Review", ""], []
    for t in tables:
        md = t.with_suffix(".md")
        nn = t.stem.split("_")[1]
        if not md.exists():
            missing.append(nn)
            continue
        out += [f"## Part {nn}", "", md.read_text(encoding="utf-8").strip(), ""]
    out += listen_summary(work)
    (work / "review.md").write_text("\n".join(out), encoding="utf-8")
    fixes = sorted(p.name for p in (work / "out").glob("fix_review_*.txt"))
    return {"review": str(work / "review.md"), "parts": len(tables), "notes_missing": missing, "fix_files": fixes}


# --- the listener: a last read of the Turkish alone, as a viewer hears it ---

LISTEN_DIR = "listen"
# A listen part: about this many spoken cues, ending at a long pause.
LISTEN_PART_CUES = 480
GATE_FILE = "gate.json"
# New warnings of these kinds, on an edited cue, its sentence group or its
# repeat pair, drop the edit. Reading speed is held by the budget instead.
GATE_WARNINGS = {"repeat drift", "split sentence", "address form", "term rendering", "term variant", "term drift"}
# Kinds a change on one cue can raise on another cue anywhere in the film.
FILM_WIDE = {"term drift", "term variant"}
QUOTE_RE = re.compile(r"'([^']+)'")
NO_ROOM = 10**6


def _plain(lines: list[str]) -> str:
    """A cue's text as the reading speed check counts it: tags stripped,
    lines joined by a space."""
    return srt.strip_tags(" ".join(lines)).strip()


def _listen_frame(work: Path) -> dict:
    """What every listen command needs: the rows, the spoken cues by time,
    the most time each cue can be shown (`layout.available_end`), the
    sentence groups and the repeat pairs ("echo") across the whole film."""
    timing, _ = srt.parse(work / "timing.srt")
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    sound_only = sound_only_cues(work, rows)
    kept = [c for c in timing if c.n not in sound_only]
    by_start = sorted(kept, key=lambda c: (c.start, c.n))
    gap = layout.usual_gap(kept)
    next_start = {a.n: b.start for a, b in zip(by_start, by_start[1:])}
    room = {c.n: layout.available_end(c.start, c.end, next_start.get(c.n), gap, NO_ROOM) - c.start for c in kept}
    group: dict[int, list[int]] = {}
    for g in sentence_groups(kept, rows):
        for n in g:
            group[n] = g
    by_key: dict[tuple, list[int]] = {}
    for c in kept:
        row = rows.get(c.n, {})
        key = None if row.get("song") else _repeat_key(row)
        if key:
            by_key.setdefault(key, []).append(c.n)
    echo = {n: [m for m in cues if m != n] for cues in by_key.values() if len(cues) > 1 for n in cues}
    return {"rows": rows, "by_start": by_start, "room": room, "group": group, "echo": echo}


def _listen_saved(work: Path) -> dict:
    path = work / "out" / LISTEN_BEFORE
    if not path.exists():
        raise SystemExit("no listen_before.json: run listenparts first")
    return json.loads(path.read_text(encoding="utf-8"))


def _listen_before(work: Path) -> dict[int, list[str]]:
    return {int(n): t for n, t in _listen_saved(work)["texts"].items()}


def _listen_human(work: Path) -> set[int]:
    return set(_listen_saved(work).get("human", []))


def _human_cues(work: Path, texts: dict[int, list[str]], frame: dict) -> set[int]:
    """In a polish run, the cues that still say the human file's line word
    for word, in a sentence group none of whose cues changed. The human
    translator heard the scene, so the listener reads these lines for the
    scene and leaves them; it listens to the lines the run wrote. Empty in
    any other run."""
    seed = polish_seed(work)
    if seed is None:
        return set()
    same = {n for n, t in texts.items() if seed.get(n) == t}
    return {n for n in same if all(m in same for m in frame["group"].get(n, [n]))}


def _write_blocks(path: Path, blocks: dict[int, list[str]]) -> None:
    path.write_text("".join(f"{n}\n" + "\n".join(lines) + "\n\n" for n, lines in sorted(blocks.items())), encoding="utf-8")


def listen_parts(work: Path, size: int = LISTEN_PART_CUES) -> dict:
    """Cut the spoken cues into parts for the listeners. Starts afresh:
    deletes the listener's fix files, the meaning check's and
    W/out/listen_before.json, then saves the Turkish now and the fix files
    it came from as listen_before.json. Each part gets
    W/listen/listen_<NN>.txt (`n`, `time`, `speaker`, `budget`, `group`,
    `echo`, `human`, `turkish`), the file the listener reads, and
    listen_<NN>_en.txt (`n`, `source`, `en`), read only for lines that
    sound wrong.

    `budget` is the most characters the cue may hold, counted as the check
    counts them: 17 a second over the most time the cue can be shown, its
    length now, or the translator's first draft's length, whichever is
    largest, so a line a review shortened into stiff Turkish can always go
    back. `group` names the cues that hold one source sentence, `echo` the
    cues that say the same source line elsewhere in the film.

    In a polish run, `human` is `yes` on a cue that still says the human
    file's line (`_human_cues`): the listener leaves it, and `listengate`
    drops an edit to it. A part with nothing else gets no listener; the
    result counts those parts in `parts_all_human`."""
    if size < 50:
        raise SystemExit("--size takes 50 cues or more")
    out = work / "out"
    for old in [*out.glob("fix_listen_*.txt"), out / LISTEN_CHECK_FIX, out / LISTEN_BEFORE]:
        old.unlink(missing_ok=True)
    texts, problems = load_translation(work)
    if problems:
        raise SystemExit(f"the Turkish files are malformed ({problems[0]}): run check and fix them first")
    frame = _listen_frame(work)
    human = _human_cues(work, texts, frame)
    (out / LISTEN_BEFORE).write_text(
        json.dumps(
            {
                "fix_files": [f.name for f in fix_order(out)],
                "texts": {str(n): t for n, t in sorted(texts.items())},
                "human": sorted(human),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    draft: dict[int, list[str]] = {}
    for f in sorted(out.glob("tr_*.txt")):
        draft.update(srt.read_blocks(f)[0])
    speakers_file = work / "speakers.json"
    speakers = json.loads(speakers_file.read_text(encoding="utf-8")) if speakers_file.exists() else {}
    spoken = [{"n": c.n, "start": c.start, "end": c.end} for c in frame["by_start"] if texts.get(c.n)]
    if not spoken:
        raise SystemExit("no spoken cues to listen to")
    folder = work / LISTEN_DIR
    folder.mkdir(exist_ok=True)
    for old in folder.glob("listen_*.txt"):
        old.unlink()
    budgets = {
        r["n"]: max(
            int(MAX_CPS * frame["room"][r["n"]] / 1000),
            len(_plain(texts[r["n"]])),
            len(_plain(draft.get(r["n"], []))),
        )
        for r in spoken
    }
    bounds = [0, *_part_cuts(spoken, size), len(spoken)]
    parts = []
    all_human = 0
    for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
        nn = f"{i:02d}"
        own = spoken[a:b]
        if human and all(r["n"] in human for r in own):
            all_human += 1
            continue
        path, en_path = folder / f"listen_{nn}.txt", folder / f"listen_{nn}_en.txt"
        with open(path, "w", encoding="utf-8") as f, open(en_path, "w", encoding="utf-8") as e:
            f.write("n\ttime\tspeaker\tbudget\tgroup\techo\thuman\tturkish\n")
            e.write("n\tsource\ten\n")
            for r in own:
                n, row = r["n"], frame["rows"][r["n"]]
                g = frame["group"].get(n)
                group = f"{g[0]}-{g[-1]}" if g else ""
                echo = ",".join(str(m) for m in frame["echo"].get(n, []))
                who = _who(row, speakers)
                mark = "yes" if n in human else ""
                tr = " / ".join(texts[n])
                f.write(f"{n}\t{srt.fmt_ms(r['start'])[:8]}\t{who}\t{budgets[n]}\t{group}\t{echo}\t{mark}\t{tr}\n")
                src = prepare._one_line(row.get("source") or row.get("timing_lines"))
                en = prepare._one_line(row["en"]) if row.get("en") and row["en"] != row.get("source") else ""
                e.write(f"{n}\t{src}\t{en}\n")
        parts.append(
            {
                "part": nn,
                "first": own[0]["n"],
                "last": own[-1]["n"],
                "cues": len(own),
                "file": str(path),
                "en_file": str(en_path),
                "write_to": str(out / f"fix_listen_{nn}.txt"),
            }
        )
    (folder / "budgets.json").write_text(json.dumps({str(n): v for n, v in budgets.items()}), encoding="utf-8")
    return {
        "parts": parts,
        "cues": len(spoken),
        "human_cues": sum(1 for r in spoken if r["n"] in human),
        "parts_all_human": all_human,
    }


def _issues(found: list[dict], kinds: set[str] | None) -> dict[tuple, dict]:
    """The problems a check found, by (cue, kind), never by the message:
    drift notes carry counts and quotes that change with any edit."""
    counts: dict[tuple, int] = {}
    first: dict[tuple, dict] = {}
    for x in found:
        if kinds is not None and x["check"] not in kinds:
            continue
        k = (x["cue"], x["check"])
        counts[k] = counts.get(k, 0) + 1
        first.setdefault(k, x)
    return {k: {**first[k], "count": v} for k, v in counts.items()}


def _new_issues(before: list[dict], after: list[dict], kinds: set[str] | None) -> list[dict]:
    old, new = _issues(before, kinds), _issues(after, kinds)
    return [x for k, x in new.items() if x["count"] > old.get(k, {}).get("count", 0)]


def _blame(x: dict, edits: dict[int, list[str]], before: dict[int, list[str]], frame: dict) -> set[int]:
    """The edits a new problem is laid on: an edit on its cue, its sentence
    group or its repeat pair; for a film-wide kind with none there, the
    edits that changed one of the words its note quotes; for a problem
    with no cue, every edit."""
    n = x["cue"]
    if n is None:
        return set(edits)
    near = {n, *frame["group"].get(n, []), *frame["echo"].get(n, [])}
    hit = near & set(edits)
    if hit or x["check"] not in FILM_WIDE:
        return hit
    # The note quotes a base form ("abi"); the line holds it with endings
    # ("abim"), so count the form inside the text before and after.
    quoted = {turkish.lower(q) for q in QUOTE_RE.findall(x.get("detail") or "")}

    def counts(lines: list[str]) -> list[int]:
        text = turkish.lower(_plain(lines))
        return [text.count(q) for q in sorted(quoted)]

    return {m for m, lines in edits.items() if counts(lines) != counts(before.get(m, []))}


def listen_gate(work: Path) -> dict:
    """Hold the listeners' edits to the checks. An edit is dropped when it
    is not on a cue of a listen part, when it changes a human line of a
    polish run, when the cue goes over its budget,
    or when its cue, its sentence group or its repeat pair gains a hard
    fail or a new warning of a kind in GATE_WARNINGS. The checks then run
    again on what is left, and an edit still causing a new problem is
    dropped too. The fix files are rewritten with the edits that pass;
    W/listen/gate.json keeps the result for `reviews`."""
    out = work / "out"
    before = _listen_before(work)
    human = _listen_human(work)
    budgets_file = work / LISTEN_DIR / "budgets.json"
    budgets = {int(n): v for n, v in json.loads(budgets_file.read_text(encoding="utf-8")).items()}
    frame = _listen_frame(work)
    files = sorted(out.glob("fix_listen_*.txt"))
    edits: dict[int, list[str]] = {}
    home: dict[int, Path] = {}
    file_problems: list[str] = []
    dropped: dict[int, str] = {}
    for f in files:
        blocks, probs = srt.read_blocks(f)
        file_problems += [f"{f.name}: {p}" for p in probs]
        for n, lines in blocks.items():
            if lines == before.get(n):
                continue
            edits[n], home[n] = lines, f
            if n not in budgets:
                dropped[n] = "not a listen cue"
            elif n in human:
                dropped[n] = "human line"
            elif len(_plain(lines)) > budgets[n]:
                dropped[n] = "over budget"
    base = run_checks(work, before, write=False)
    res = base
    passes = 0
    for _ in range(3):
        live = {n: t for n, t in edits.items() if n not in dropped}
        res = run_checks(work, {**before, **live}, write=False)
        passes += 1
        blamed: dict[int, str] = {}
        for x in _new_issues(base["hard"], res["hard"], None):
            for m in _blame(x, live, before, frame):
                blamed.setdefault(m, f"hard fail: {x['check']}")
        for x in _new_issues(base["warnings"], res["warnings"], GATE_WARNINGS):
            for m in _blame(x, live, before, frame):
                blamed.setdefault(m, x["check"])
        if not blamed:
            break
        dropped.update(blamed)
    live = {n: t for n, t in edits.items() if n not in dropped}
    for f in files:
        _write_blocks(f, {n: t for n, t in live.items() if home[n] == f})
    by_reason: dict[str, list[int]] = {}
    for n, why in sorted(dropped.items()):
        by_reason.setdefault(why, []).append(n)

    def over_20(r: dict) -> int:
        return sum(1 for x in r["warnings"] if x["check"] == "reading speed" and x.get("cps", 0) > 20)

    left = _new_issues(base["hard"], res["hard"], None) + _new_issues(base["warnings"], res["warnings"], GATE_WARNINGS)
    gate = {
        "edits": len(edits),
        "kept": len(live),
        "kept_cues": sorted(live),
        "spoken_cues": len(budgets),
        "human_cues": len(human & set(budgets)),
        "dropped": by_reason,
        "passes": passes,
        "left_unblamed": [{"cue": x["cue"], "check": x["check"]} for x in left],
        "over_20_before": over_20(base),
        "over_20_after": over_20(res),
        "file_problems": file_problems,
    }
    (work / LISTEN_DIR / GATE_FILE).write_text(json.dumps(gate, indent=1), encoding="utf-8")
    return gate


def _listen_edits(work: Path) -> dict[int, list[str]]:
    edits: dict[int, list[str]] = {}
    for f in sorted((work / "out").glob("fix_listen_*.txt")):
        edits.update(srt.read_blocks(f)[0])
    return edits


def listen_check(work: Path) -> dict:
    """Write W/review/listencheck.txt for the meaning check: each edit the
    gate kept, with its speaker, source, English, the line before and
    after, the cues around it as they are now, and the other edited cues
    of its sentence group or repeat pair (a write-back covers them all)."""
    before = _listen_before(work)
    edits = _listen_edits(work)
    frame = _listen_frame(work)
    speakers_file = work / "speakers.json"
    speakers = json.loads(speakers_file.read_text(encoding="utf-8")) if speakers_file.exists() else {}
    now = {**before, **edits}
    order = [c.n for c in frame["by_start"] if c.n in now]
    at = {n: i for i, n in enumerate(order)}
    folder = work / REVIEW_DIR
    folder.mkdir(exist_ok=True)
    path = folder / "listencheck.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# listener check: {len(edits)} edits\n")
        f.write("# before = the line before the listener; after = the listener's line; prev/next = the cues around it now.\n\n")
        for n in sorted(edits, key=lambda m: at.get(m, 0)):
            row = frame["rows"].get(n, {})
            i = at.get(n)
            prev = order[i - 1] if i else None
            nxt = order[i + 1] if i is not None and i + 1 < len(order) else None
            tied = sorted(({*frame["group"].get(n, []), *frame["echo"].get(n, [])} - {n}) & set(edits))
            f.write(f"#{n}\n")
            f.write(f"speaker: {prepare.speaker_hint(speakers.get(str(n), {}))}\n")
            f.write("src: " + prepare._one_line(row.get("source") or row.get("timing_lines")) + "\n")
            if row.get("en") and row["en"] != row.get("source"):
                f.write("en: " + prepare._one_line(row["en"]) + "\n")
            f.write("before: " + " / ".join(before.get(n, [])) + "\n")
            f.write("after: " + " / ".join(edits[n]) + "\n")
            if prev is not None:
                f.write(f"prev: {prev}: " + " / ".join(now[prev]) + "\n")
            if nxt is not None:
                f.write(f"next: {nxt}: " + " / ".join(now[nxt]) + "\n")
            if tied:
                f.write("with: " + ", ".join(map(str, tied)) + "\n")
            f.write("\n")
    return {"file": str(path), "edits": len(edits), "write_to": str(work / "out" / LISTEN_CHECK_FIX)}


def listen_drop(work: Path, cues: list[int]) -> dict:
    """Drop the listener's edits of these cues, and any meaning-check line
    for them: the last check found a hard fail there."""
    out = work / "out"
    gone: set[int] = set()
    for f in [*sorted(out.glob("fix_listen_*.txt")), out / LISTEN_CHECK_FIX]:
        if not f.exists():
            continue
        blocks, _ = srt.read_blocks(f)
        hit = set(blocks) & set(cues)
        if hit:
            gone |= hit
            _write_blocks(f, {n: t for n, t in blocks.items() if n not in hit})
    gate_file = work / LISTEN_DIR / GATE_FILE
    if gate_file.exists() and gone:
        gate = json.loads(gate_file.read_text(encoding="utf-8"))
        gate["kept_cues"] = [n for n in gate["kept_cues"] if n not in gone]
        gate["kept"] = len(gate["kept_cues"])
        late = set(gate["dropped"].get("hard fail at the last check", []))
        gate["dropped"]["hard fail at the last check"] = sorted(late | gone)
        gate_file.write_text(json.dumps(gate, indent=1), encoding="utf-8")
    return {"dropped": sorted(gone)}


def listen_summary(work: Path) -> list[str]:
    """The listener's lines for review.md, or none when it did not run."""
    gate_file = work / LISTEN_DIR / GATE_FILE
    if not gate_file.exists():
        return []
    gate = json.loads(gate_file.read_text(encoding="utf-8"))
    before = _listen_before(work) if (work / "out" / LISTEN_BEFORE).exists() else {}
    check_file = work / "out" / LISTEN_CHECK_FIX
    back = srt.read_blocks(check_file)[0] if check_file.exists() else {}
    written_back = sorted(n for n, t in back.items() if t == before.get(n))

    def cues(ns: list[int]) -> str:
        return ", ".join(map(str, ns[:30])) + (", ..." if len(ns) > 30 else "")

    lines = ["## Listener", ""]
    lines.append(f"- Edits kept: {gate['kept']} of {gate['spoken_cues']} spoken cues ({cues(gate['kept_cues'])})")
    if gate.get("human_cues"):
        lines.append(f"- Human lines read for the scene and left as they are: {gate['human_cues']}")
    for why, ns in gate["dropped"].items():
        lines.append(f"- Dropped by the gate, {why}: {len(ns)} ({cues(ns)})")
    lines.append(f"- Written back by the meaning check: {len(written_back)} ({cues(written_back)})")
    lines.append(f"- Cues above 20 characters a second: {gate['over_20_before']} before, {gate['over_20_after']} after")
    return [*lines, ""]


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


CREDIT_HELLO = "İyi seyirler."
CREDIT_BYE = "Görüşmek üzere."
CREDIT_NAME_MAX = layout.MAX_LINE
# Each end shows one screen for 4 s: the greeting over the translator's
# name. The opening starts at 3 s and ends at least half a second before
# the first line: with a first line before 7.5 s it is cut short, but kept
# for 3 s at least (a first line from 6.5 s); with less room, nothing. The
# closing screen starts 3 s after the story's last line, so it does not
# run into it, in the first free 2 s from there on, and ends 0.1 s before
# the next cue (an end title). When the video's end is known, the closing
# screen stays inside it: it moves earlier, to half a second after the cue
# before it at most, to keep its 4 s; with less room it ends with the
# video, kept for 3 s at least; with under 3.5 s, nothing.
CREDIT_START_AT = 3000
CREDIT_GAP = 500
CREDIT_END_AFTER = 3000
CREDIT_MS = 4000
CREDIT_MIN_MS = 3000
CREDIT_FREE_MS = 2000
CREDIT_BEFORE_NEXT = 100


def credit_lines(greeting: str, translator: str = "") -> list[str]:
    """One credit screen: the greeting over the translator's name, or the
    greeting alone when no name is given."""
    translator = " ".join(translator.split())
    if len(translator) > CREDIT_NAME_MAX:
        raise SystemExit(f"the credit name is longer than {CREDIT_NAME_MAX} characters: {translator!r}")
    return [greeting, translator] if translator else [greeting]


def goodbye_at(cues: list[srt.Cue], on_screen: set[int], video_end: int | None = None) -> tuple[int, int] | None:
    """Start and end of the closing credit, or None when the video leaves
    no room for it. It follows the story, not an end title shown after the
    credits roll: from 3 s after the last cue that is not on-screen text (a
    kept song counts as story), it takes the first free 2 s, skipping any
    cue in its way, and ends 0.1 s before the next cue. With no such free
    time, or no story cue at all, it starts 3 s after the last cue.
    `video_end` (ms), when known, keeps it inside the video."""
    last = max(c.end for c in cues)
    story = [c.end for c in cues if c.n not in on_screen]
    at, end = last + CREDIT_END_AFTER, None
    if story:
        at = max(story) + CREDIT_END_AFTER
        for c in sorted(cues, key=lambda c: c.start):
            if c.end <= at:
                continue
            if c.start - at >= CREDIT_FREE_MS:
                end = min(at + CREDIT_MS, c.start - CREDIT_BEFORE_NEXT)
                break
            at = max(at, c.end)
        if end is None and at == last:
            # Cues in the way up to the end of the file: after the last one.
            at = last + CREDIT_END_AFTER
    end = at + CREDIT_MS if end is None else end
    if video_end is not None and end > video_end:
        before = max((c.end for c in cues if c.end <= at), default=0)
        end = video_end
        at = max(before + CREDIT_GAP, end - CREDIT_MS)
        if end - at < CREDIT_MIN_MS:
            return None
    return at, end


def with_credit(
    cues: list[srt.Cue], translator: str = "", video_end: int | None = None, on_screen: set[int] | None = None
) -> tuple[list[srt.Cue], int, list[int]]:
    """The delivered cues with the credit added, renumbered from 1; how many
    cues were put before the film's own (0 or 1), and the numbers of the
    credit cues, which are no translation. `video_end` (ms), when known,
    keeps the closing credit inside the video; `on_screen` holds the numbers
    of the cues that are on-screen text, not the story's lines
    (`goodbye_at`)."""
    if not cues:
        return cues, 0, []

    def cue(start: int, end: int, lines: list[str]) -> srt.Cue:
        return srt.Cue(n=0, start=start, end=end, ts=f"{srt.fmt_ms(start)} --> {srt.fmt_ms(end)}", lines=lines)

    head: list[srt.Cue] = []
    room = cues[0].start - CREDIT_GAP
    at = CREDIT_START_AT
    if room >= at + CREDIT_MIN_MS:
        head = [cue(at, min(room, at + CREDIT_MS), credit_lines(CREDIT_HELLO, translator))]
    bye = goodbye_at(cues, on_screen or set(), video_end)
    if bye is None:
        tail, before = [], len(cues)
    else:
        tail, before = [cue(*bye, credit_lines(CREDIT_BYE, translator))], sum(1 for c in cues if c.start < bye[0])
    body = head + cues[:before] + tail + cues[before:]
    out = [srt.Cue(n=i, start=c.start, end=c.end, ts=c.ts, lines=c.lines) for i, c in enumerate(body, 1)]
    credits = list(range(1, len(head) + 1)) + ([len(head) + before + 1] if tail else [])
    return out, len(head), credits


def video_end_ms(video: Path) -> int | None:
    """The video's length in ms from ffprobe, or None when it cannot be
    read (no ffprobe, not a video): the closing credit is then not held to
    it."""
    try:
        ms = sources.probe(video)["duration_ms"]
    except (SystemExit, OSError, ValueError, subprocess.SubprocessError):
        return None
    return ms or None


def credit_map(cue_map: dict, credits: list[int]) -> dict:
    """The draft's cue map renumbered around the credit cues, which are
    listed apart: they lead back to no timing cue. The draft's cues keep
    their order; each takes the next delivered number that is no credit."""
    taken = set(credits)
    free = (n for n in range(1, len(cue_map["cues"]) + len(credits) + 1) if n not in taken)
    moved = {str(d): cue_map["cues"][str(o)] for o, d in zip(sorted(int(n) for n in cue_map["cues"]), free)}
    return {**cue_map, "cues": moved, "credits": credits}


def on_screen_draft_cues(work: Path) -> set[int]:
    """The draft numbers whose cue is on-screen text (`prepare.py build`
    marks the row `on_screen`), every part of a split cue included."""
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    screen = {r["n"] for r in rows if r.get("on_screen")}
    if not screen:
        return set()
    cue_map = json.loads((work / MAP_FILE).read_text(encoding="utf-8"))
    return {int(d) for d, info in cue_map["cues"].items() if info["cue"] in screen}


# The two kinds of on-screen text no run finds, said in every report.
ON_SCREEN_LIMITS = (
    "Text shown while someone is speaking is not found: nothing in the subtitle tracks tells it from a translated line.",
    "Text in the middle of the film that no subtitle track shows is not found.",
)


def on_screen_report(work: Path) -> dict | None:
    """The run report's on-screen section, read once the file is delivered.

    `delivered`: every entry delivered, with its delivered numbers, time,
    source text and Turkish. `left_out_at_ends`: every entry left out that
    starts before the first spoken cue or at or after story end (the end of
    the last cue that is not on-screen text), with its reason. `left_out`:
    the count per reason of the other entries left out; `file` holds them
    all. `unplaced_human_lines`, in a polish run: the human Turkish lines
    that landed on no cue and lie under no entry delivered. `limits`: what
    no run finds. None for a work folder with no on_screen.json, outside a
    polish run."""
    entries_file = work / prepare.ON_SCREEN_FILE
    polish = polish_seed(work) is not None
    if not entries_file.exists() and not polish:
        return None
    entries = on_screen_entries(work)
    screen = on_screen_draft_cues(work)
    spoken = [c for c in srt.parse(work / "draft.tr.srt")[0] if c.n not in screen]
    first = min((c.start for c in spoken), default=None)
    story_end = max((c.end for c in spoken), default=None)
    shown = {c.n: c for c in srt.parse(work / "delivered.tr.srt")[0]}
    back: dict[int, list[int]] = {}
    for d, info in (read_map(work) or {"cues": {}})["cues"].items():
        back.setdefault(info["cue"], []).append(int(d))
    delivered, at_ends, rest = [], [], Counter()
    for e in entries:
        text = srt.strip_tags(prepare._one_line(e["lines"]))
        if e["state"] == "cue":
            ds = sorted(back.get(e["n"], []))
            at = shown[ds[0]].ts[:12] if ds else None
            turkish = " / ".join(ln for d in ds for ln in shown[d].lines)
            delivered.append({"cue": ds, "at": at, "text": text, "turkish": turkish})
        elif first is None or e["start"] < first or e["start"] >= story_end:
            at_ends.append({"at": srt.fmt_ms(e["start"]), "text": text, "reason": e.get("reason", e["state"])})
        else:
            rest[e.get("reason", e["state"])] += 1
    unplaced = []
    if polish:
        cards = [(e["start"], e["end"]) for e in entries if e["state"] == "cue"]
        for item in json.loads((work / "polish_placement.json").read_text(encoding="utf-8")).get("unplaced", []):
            a, b = item.get("start"), item.get("end")
            if a is not None and any(min(b, y) > max(a, x) for x, y in cards):
                continue
            unplaced.append({"at": srt.fmt_ms(a) if a is not None else None, "text": item["text"]})
    return {
        "delivered": delivered,
        "left_out_at_ends": at_ends,
        "left_out": dict(rest),
        "file": str(entries_file) if entries_file.exists() else None,
        "unplaced_human_lines": unplaced,
        "limits": list(ON_SCREEN_LIMITS),
    }


def deliver(
    work: Path,
    dest: Path,
    backups: Path,
    force: bool,
    video: Path | None = None,
    credit: bool = True,
    translator: str = "",
) -> dict:
    """Write the draft to `dest`, moving any file already there to
    `backups`. With `video` (the run delivers to the default place, the
    video's own name), this plugin's earlier deliveries of that video under
    another name go to `backups` too and are listed under
    `moved_earlier_deliveries`; without it, files beside `dest` stay put.
    `credit` adds the opening and closing credit cues (`with_credit`),
    naming `translator` when given; only the delivered file has them, never
    the draft. `on_screen` is the report's on-screen section
    (`on_screen_report`)."""
    if credit:
        credit_lines(CREDIT_HELLO, translator)  # a name too long stops before any file moves
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
    # The report reads on_screen.json after the file is delivered: one it
    # cannot read stops here, before any file moves.
    if any(not isinstance(e, dict) or not {"state", "start", "end", "lines"} <= e.keys() for e in on_screen_entries(work)):
        raise SystemExit(f"{work / prepare.ON_SCREEN_FILE} is malformed: run prepare.py build again")
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
    credits: list[int] = []
    if credit:
        shown, _, credits = with_credit(
            srt.parse_text(srt.decode(data)[0]),
            translator,
            video_end_ms(video) if video is not None else None,
            on_screen_draft_cues(work),
        )
        data = srt.render(shown).replace("\n", "\r\n").encode("utf-8")
    if not data.startswith(UTF8_BOM):
        data = UTF8_BOM + data
    dest.write_bytes(data)
    (work / "delivered.tr.srt").write_bytes(data)
    if credits:
        cue_map = json.loads((work / MAP_FILE).read_text(encoding="utf-8"))
        (work / DELIVERED_MAP_FILE).write_text(json.dumps(credit_map(cue_map, credits), indent=1), encoding="utf-8")
    else:
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
        "credit": credit,
        "credit_name": translator if credit else "",
        "credit_cues": credits,
        "on_screen": on_screen_report(work),
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
        "extended_cues": result["extended_cues"],
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
    ck = sub.add_parser("check")
    ck.add_argument("--work", type=result.path, required=True)
    d = sub.add_parser("deliver")
    d.add_argument("--work", type=result.path, required=True)
    d.add_argument("--dest", type=result.path, required=True)
    d.add_argument("--backups", type=result.path, required=True)
    d.add_argument("--force", action="store_true")
    d.add_argument("--video", type=result.path, help="the film; pass it only when --dest is the default name next to it")
    d.add_argument("--no-credit", dest="credit", action="store_false", help="add no opening and closing credit")
    d.add_argument(
        "--credit-name", default="", help="the translator the credit names under its greeting; none: the greeting alone"
    )
    wh = sub.add_parser("where")
    wh.add_argument("--work", type=result.path, required=True)
    wh.add_argument("--cues", required=True, help="comma-separated cue numbers of the timing file")
    rp = sub.add_parser("reviewparts")
    rp.add_argument("--work", type=result.path, required=True)
    rp.add_argument("--size", type=int, default=PART_CUES, help="cues per part, about")
    rv = sub.add_parser("reviews")
    rv.add_argument("--work", type=result.path, required=True)
    lp = sub.add_parser("listenparts")
    lp.add_argument("--work", type=result.path, required=True)
    lp.add_argument("--size", type=int, default=LISTEN_PART_CUES, help="cues per part, about")
    for name in ("listengate", "listencheck"):
        sub.add_parser(name).add_argument("--work", type=result.path, required=True)
    ld = sub.add_parser("listendrop")
    ld.add_argument("--work", type=result.path, required=True)
    ld.add_argument("--cues", required=True, help="comma-separated cue numbers of the timing file")
    fr = sub.add_parser("fixround")
    fr.add_argument("--work", type=result.path, required=True)
    fr.add_argument("--round", required=True, help="the round's label: r1, r2, r3, post")
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "check":
        result.emit(_summary(run_checks(a.work)), a.result)
    elif a.cmd == "reviewparts":
        result.emit(review_parts(a.work, a.size), a.result)
    elif a.cmd == "reviews":
        result.emit(join_reviews(a.work), a.result)
    elif a.cmd in ("where", "listendrop"):
        try:
            numbers = [int(x) for x in a.cues.split(",") if x.strip()]
        except ValueError as e:
            raise SystemExit("--cues takes cue numbers separated by commas") from e
        result.emit((where if a.cmd == "where" else listen_drop)(a.work, numbers), a.result)
    elif a.cmd == "listenparts":
        result.emit(listen_parts(a.work, a.size), a.result)
    elif a.cmd == "listengate":
        result.emit(listen_gate(a.work), a.result)
    elif a.cmd == "listencheck":
        result.emit(listen_check(a.work), a.result)
    elif a.cmd == "fixround":
        result.emit(fix_round(a.work, a.round), a.result)
    else:
        result.emit(deliver(a.work, a.dest, a.backups, a.force, a.video, a.credit, a.credit_name), a.result)


if __name__ == "__main__":
    main()
