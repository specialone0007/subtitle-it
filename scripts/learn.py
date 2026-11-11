# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Find what the user changed in a delivered Turkish file, so the skill can
propose rules.

    uv run learn.py scan --data DATA_DIR
    uv run learn.py diff --work W

`scan` lists films whose delivered .tr.srt has changed since delivery.
`diff` prints every edited cue (before and after) and the word swaps that
repeat, such as "Peki" -> "Tamam" in 6 cues. It never writes rules itself.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import srt  # noqa: E402

WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _changed(work: Path) -> bool | None:
    info_file = work / "delivered.json"
    if not info_file.exists():
        return None
    info = json.loads(info_file.read_text(encoding="utf-8"))
    dest = Path(info["delivered_to"])
    if not dest.exists():
        return None
    if info.get("learned_sha256") == hashlib.sha256(dest.read_bytes()).hexdigest():
        return False
    return hashlib.sha256(dest.read_bytes()).hexdigest() != info["sha256"]


def scan(data: Path) -> list[dict]:
    out = []
    for work in sorted((data / "films").glob("*")):
        if _changed(work):
            info = json.loads((work / "delivered.json").read_text(encoding="utf-8"))
            out.append({"work": str(work), "file": info["delivered_to"]})
    return out


def diff(work: Path) -> dict:
    info = json.loads((work / "delivered.json").read_text(encoding="utf-8"))
    before, _ = srt.parse(work / "delivered.tr.srt")
    after, _ = srt.parse(info["delivered_to"])
    by_ts = {c.ts: c for c in after}
    edits, swaps = [], Counter()
    swap_cues: dict[tuple[str, str], list[int]] = {}
    for c in before:
        d = by_ts.get(c.ts)
        if d is None or d.text == c.text:
            continue
        edits.append({"cue": c.n, "before": c.text, "after": d.text})
        a, b = WORD_RE.findall(c.text), WORD_RE.findall(d.text)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
            if op == "replace" and i2 - i1 <= 3 and j2 - j1 <= 3:
                key = (" ".join(a[i1:i2]), " ".join(b[j1:j2]))
                swaps[key] += 1
                swap_cues.setdefault(key, []).append(c.n)
    repeated = [{"from": k[0], "to": k[1], "count": v, "cues": swap_cues[k][:10]} for k, v in swaps.most_common() if v >= 2]
    return {
        "file": info["delivered_to"],
        "cues_edited": len(edits),
        "cues_missing_in_edited_file": sum(1 for c in before if c.ts not in by_ts),
        "repeated_swaps": repeated,
        "edits": edits[:200],
    }


def mark_learned(work: Path) -> None:
    info_file = work / "delivered.json"
    info = json.loads(info_file.read_text(encoding="utf-8"))
    info["learned_sha256"] = hashlib.sha256(Path(info["delivered_to"]).read_bytes()).hexdigest()
    info_file.write_text(json.dumps(info, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--data", type=Path, required=True)
    for name in ("diff", "done"):
        s = sub.add_parser(name)
        s.add_argument("--work", type=Path, required=True)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "scan":
        result.emit(scan(a.data), a.result)
    elif a.cmd == "diff":
        result.emit(diff(a.work), a.result)
    else:
        mark_learned(a.work)
        result.emit({"marked": "learned"}, a.result)


if __name__ == "__main__":
    main()
