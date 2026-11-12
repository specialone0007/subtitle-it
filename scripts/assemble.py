# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Assemble the Turkish file, run the checks, build the reviewer's file and
deliver the result next to the video.

    uv run assemble.py check       --work W
    uv run assemble.py sidebyside  --work W
    uv run assemble.py deliver     --work W --dest FILM.tr.srt --backups DIR [--force]
    uv run assemble.py where       --work W --cues 12,340

`check` reads W/out/tr_*.txt, then W/out/fix_*.txt in the order they were
written (later files win; in a polish run fix_polish.txt also wins over
fix_review.txt), writes W/draft.tr.srt when every cue has text, and
writes W/checks.json. When a cue is missing or a file is malformed, no draft is
written and any older draft is removed. Hard fails block delivery; warnings do
not, and nothing without a current draft is ever delivered.

The checks go cue for cue with the timing file. The draft is the file as
it will be delivered: laid out by layout.py (at most two lines of 42
characters, a long two-speaker cue split into one cue per speaker),
without the cues that hold only sounds, and numbered from 1. W/cue_map.json
maps each draft number to the timing file's cue; `deliver` keeps it as
W/delivered_map.json, and `where` answers from it which delivered cues and
times a timing cue became.
"""

from __future__ import annotations

import argparse
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

MAX_LINE = layout.MAX_LINE
MAX_CPS = layout.MAX_CPS
MAP_FILE = "cue_map.json"
DELIVERED_MAP_FILE = "delivered_map.json"
CPS_MARGIN = 1.15
INFINITIVE_RE = re.compile(r"^[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(mak|mek)[.!]$")
CAPS_RE = re.compile(r"\b(TAMAM|HAYIR)\b")
ITALIC_RE = re.compile(r"</?i>", re.I)


def fix_order(out: Path) -> list[Path]:
    """W/out/fix_*.txt in the order they apply. Fix files apply in the order
    they were written, so a fix round after the review wins over
    fix_review.txt whatever the files are called. One exception: in a polish
    run the fixer and the reviewer work at the same time, and the flagged
    cues are the fixer's, so fix_polish.txt applies right after
    fix_review.txt even when it was written first."""
    files = list(out.glob("fix_*.txt"))
    review = out / "fix_review.txt"
    review_at = review.stat().st_mtime_ns if review.exists() else -1

    def key(p: Path) -> tuple[int, int, str]:
        at = p.stat().st_mtime_ns
        if p.name == "fix_polish.txt":
            return (max(at, review_at), 1, p.name)
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
    kept: list[srt.Cue], texts: dict[int, list[str]], parts: dict[int, list[layout.Part]], sound_only: list[int]
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
    return shown, {"cues": where, "sound_only": sound_only}


def read_map(work: Path, delivered: bool = True) -> dict | None:
    """The cue map of the delivered file (or, with delivered=False, of the
    current draft), or None when there is none: a film delivered by an
    older version, whose cues are the timing file's cues one for one."""
    path = work / (DELIVERED_MAP_FILE if delivered else MAP_FILE)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def where(work: Path, cues: list[int]) -> list[dict]:
    """Where cues of the timing file are in the delivered file (or in the
    draft before delivery): delivered numbers and times, or that the cue
    was left out as sound only."""
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
            out.append({"cue": n, "delivered": [], "note": "sound only: not in the delivered file"})
            continue
        ds = sorted(back.get(n, []))
        out.append({"cue": n, "delivered": ds, "at": [shown[d].ts[:12] for d in ds if d in shown]})
    return out


def hi_mode(work: Path) -> str:
    """How `prepare.py build` treated hearing-impaired text: remove or keep."""
    build_file = work / "build.json"
    info = json.loads(build_file.read_text(encoding="utf-8")) if build_file.exists() else {}
    return info.get("hearing_impaired_tags", "keep")


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
    sound_only = {n for n, r in rows.items() if r.get("sound_only")}
    kept = [c for c in timing if c.n not in sound_only]
    valid = {c.n for c in kept}
    for n in sorted(set(texts) - valid - sound_only):
        h(n, "cue count", "cue number not in the timing file")
    # Text for a cue that holds only sounds is left out, never delivered.
    for n in sorted(set(texts) & sound_only):
        w(n, "sound-only cue", "the source has only sound descriptions here; this text is not delivered")
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
        if bool(ITALIC_RE.search("".join(src))) != bool(ITALIC_RE.search("".join(tr))):
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
        if tr_cps > MAX_CPS and tr_cps > ref_cps * CPS_MARGIN:
            w(c.n, "reading speed", f"{tr_cps:.1f} chars/s, source {ref_cps:.1f}")
        if len(tr) == 1 and INFINITIVE_RE.match(srt.strip_tags(tr[0]).strip()):
            w(c.n, "infinitive command", tr[0])
        for ln in tr:
            if CAPS_RE.search(ln):
                w(c.n, "caps", ln)

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

    warn += bible.address_warnings(work, texts, rows)

    shown: list[srt.Cue] = []
    if not missing and not any(x["check"] == "file format" for x in hard):
        shown, cue_map = lay_out(kept, texts, parts, sorted(sound_only))
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
        "sound_only_cues": len(sound_only),
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
    path = work / "sidebyside.tsv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("n\tspeaker\tsource\tturkish\n")
        for r in rows:
            n = r["n"]
            if r.get("sound_only"):
                continue
            if n in joins:
                f.write(f"# --- chunk join before cue {n} ---\n")
            who = prepare.speaker_hint(speakers.get(str(n), {}))
            src = " / ".join(r["source"] or r["timing_lines"])
            tr = " / ".join(texts.get(n, ["<MISSING>"]))
            f.write(f"{n}\t{who}\t{src}\t{tr}\n")
    return path


def deliver(work: Path, dest: Path, backups: Path, force: bool) -> dict:
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
    if dest.exists():
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backed_up = backups / f"{dest.stem}.{stamp}{dest.suffix}"
        # When the old file is this folder's earlier delivery, its cue map
        # goes with it, so the backup's numbers can still be traced to the
        # timing file's cues.
        old_info = work / "delivered.json"
        old_map = work / DELIVERED_MAP_FILE
        if old_info.exists() and old_map.exists():
            sha = json.loads(old_info.read_text(encoding="utf-8")).get("sha256")
            if sha == hashlib.sha256(dest.read_bytes()).hexdigest():
                shutil.copyfile(old_map, backed_up.with_name(backed_up.name + ".map.json"))
        shutil.move(dest, backed_up)
    shutil.copyfile(draft, dest)
    shutil.copyfile(draft, work / "delivered.tr.srt")
    shutil.copyfile(work / MAP_FILE, work / DELIVERED_MAP_FILE)
    info = {
        "delivered_to": str(dest),
        "backup_of_old_file": str(backed_up) if backed_up else None,
        "sha256": hashlib.sha256(draft.read_bytes()).hexdigest(),
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
        "delivered_cues": result["delivered_cues"],
        "split_cues": result["split_cues"],
        "translated": result["translated"],
        "hard_fails": result["hard_fail_count"],
        "warnings": result["warning_count"],
        "by_check": by_check,
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
    wh = sub.add_parser("where")
    wh.add_argument("--work", type=result.path, required=True)
    wh.add_argument("--cues", required=True, help="comma-separated cue numbers of the timing file")
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
    else:
        result.emit(deliver(a.work, a.dest, a.backups, a.force), a.result)


if __name__ == "__main__":
    main()
