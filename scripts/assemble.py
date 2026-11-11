# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Assemble the Turkish file, run the checks, build the reviewer's file and
deliver the result next to the video.

    uv run assemble.py check       --work W
    uv run assemble.py sidebyside  --work W
    uv run assemble.py deliver     --work W --dest FILM.tr.srt --backups DIR [--force]

`check` reads W/out/tr_*.txt, then W/out/fix_*.txt in name order (later
files win), writes W/draft.tr.srt when every cue has text, and writes
W/checks.json. Hard fails block delivery; warnings do not.
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
import srt  # noqa: E402

MAX_LINE = 42
MAX_CPS = 17.0
CPS_MARGIN = 1.15
INFINITIVE_RE = re.compile(r"^[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(mak|mek)[.!]$")
CAPS_RE = re.compile(r"\b(TAMAM|HAYIR)\b")
ITALIC_RE = re.compile(r"</?i>", re.I)


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
    for f in sorted(out.glob("fix_*.txt")):
        blocks, probs = srt.read_blocks(f)
        problems += probs
        texts.update(blocks)
    return texts, problems


def _dashes(lines: list[str]) -> int:
    return sum(1 for ln in lines if srt.strip_tags(ln).lstrip().startswith("-"))


def _cps(text: str, ms: int) -> float:
    return len(text) / (ms / 1000)


def run_checks(work: Path) -> dict:
    timing, _ = srt.parse(work / "timing.srt")
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts, problems = load_translation(work)
    hard: list[dict] = []
    warn: list[dict] = []

    def h(n, check, detail=""):
        hard.append({"cue": n, "check": check, "detail": detail})

    def w(n, check, detail=""):
        warn.append({"cue": n, "check": check, "detail": detail})

    for p in problems:
        h(None, "file format", p)
    valid = {c.n for c in timing}
    for n in sorted(set(texts) - valid):
        h(n, "cue count", "cue number not in the timing file")
    missing = [c.n for c in timing if c.n not in texts]
    for n in missing:
        h(n, "cue count", "missing")

    for c in timing:
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
        if _dashes(src) != _dashes(tr):
            h(c.n, "dialogue dashes", f"source {_dashes(src)}, Turkish {_dashes(tr)}")
        if len(tr) > max(2, len(src)):
            h(c.n, "lines per cue", f"{len(tr)} lines")
        for ln in tr:
            if len(srt.strip_tags(ln)) > MAX_LINE:
                w(c.n, "line length", f"{len(srt.strip_tags(ln))} chars: {ln}")
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
                rx = re.compile(r"\b" + re.escape(alt.casefold()) + r"\b")
                hits = [n for n, t in texts.items() if rx.search(" ".join(t).casefold())]
                for n in hits:
                    w(n, "term variant", f"'{alt}' used; glossary says '{preferred}'")

    if not missing and not any(x["check"] == "file format" for x in hard):
        full = {c.n: texts[c.n] for c in timing}
        srt.write(work / "draft.tr.srt", timing, full)
        back, _ = srt.parse(work / "draft.tr.srt")
        if len(back) != len(timing):
            h(None, "cue count", f"draft has {len(back)} cues, timing file {len(timing)}")
        for a, b in zip(timing, back):
            if a.ts != b.ts:
                h(a.n, "timestamps", f"{a.ts} became {b.ts}")
        draft = str(work / "draft.tr.srt")
    else:
        draft = None

    result = {
        "draft": draft,
        "cues": len(timing),
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
    chunks = json.loads((work / "chunks.json").read_text(encoding="utf-8"))
    joins = {c["first"] for c in chunks[1:]}
    path = work / "sidebyside.tsv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("n\tspeaker\tsource\tturkish\n")
        for r in rows:
            n = r["n"]
            if n in joins:
                f.write(f"# --- chunk join before cue {n} ---\n")
            sp = speakers.get(str(n), {})
            who = sp.get("name") or sp.get("label") or sp.get("voice") or ""
            src = " / ".join(r["source"] or r["timing_lines"])
            tr = " / ".join(texts.get(n, ["<MISSING>"]))
            f.write(f"{n}\t{who}\t{src}\t{tr}\n")
    return path


def deliver(work: Path, dest: Path, backups: Path, force: bool) -> dict:
    checks = json.loads((work / "checks.json").read_text(encoding="utf-8"))
    draft = work / "draft.tr.srt"
    if not draft.exists():
        raise SystemExit("no draft: run check first")
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
        shutil.move(dest, backed_up)
    shutil.copyfile(draft, dest)
    shutil.copyfile(draft, work / "delivered.tr.srt")
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
        s.add_argument("--work", type=Path, required=True)
    d = sub.add_parser("deliver")
    d.add_argument("--work", type=Path, required=True)
    d.add_argument("--dest", type=Path, required=True)
    d.add_argument("--backups", type=Path, required=True)
    d.add_argument("--force", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "check":
        print(json.dumps(_summary(run_checks(a.work)), ensure_ascii=False, indent=1))
    elif a.cmd == "sidebyside":
        print(sidebyside(a.work))
    else:
        print(json.dumps(deliver(a.work, a.dest, a.backups, a.force), indent=1))


if __name__ == "__main__":
    main()
