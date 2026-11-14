# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Blind comparison of two or three delivered Turkish subtitles of one film.

    uv run compare.py rows    --timing EN.srt --version 071=A.srt --version 072=B.srt
                              --out DIR [--seed N] [--parts N] [--all]
    uv run compare.py unblind --key DIR/key.json --verdicts V.json [--verdicts V2.json]

`rows` pairs each version's cues with the English timing file's cues by
time overlap and writes DIR/rows.tsv (DIR/rows_1.tsv ... with --parts):
`id`, `time`, `english`, then `A`, `B` and `C` for three versions. The
versions are shuffled to the letters again on every row, so a judge cannot
learn which letter is which. Only rows where the versions differ are kept,
unless --all. DIR/key.json says which version each letter is on each row.

`unblind` reads verdict files, each a JSON list of

    {"id": 12, "rank": ["C", "A=B"], "problems": {"A": "none", "B": "meaning", "C": "none"}, "why": "..."}

with `rank` best first and a tie written as "A=B", and turns the letters
back into versions: per version, the rows it was best alone and worst on,
its average rank (0 is best; tied versions share a place), its problems by
kind, and head-to-head wins, losses and ties for each pair of versions.

The rows hold film dialogue: DIR must be outside this repository.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import srt  # noqa: E402

LETTERS = "ABC"
REPO = Path(__file__).resolve().parent.parent


def _cell(lines: list[str]) -> str:
    """One TSV cell: tags gone, lines joined with " / ", no tab or newline."""
    text = " / ".join(srt.strip_tags(x).strip() for x in lines if srt.strip_tags(x).strip())
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _version(text: str) -> tuple[str, Path]:
    label, sep, path = text.partition("=")
    if not sep or not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("--version takes LABEL=PATH")
    return label.strip(), result.path(path.strip())


def _outside_repo(out: Path) -> None:
    out_key, repo_key = srt.path_key(out), srt.path_key(REPO)
    if out_key == repo_key or out_key.startswith(repo_key.rstrip("\\/") + os.sep):
        raise SystemExit(f"--out {out} is inside the repository: film text must never be committed; pick a folder outside it")


def build_rows(timing: list[srt.Cue], versions: dict[str, list[srt.Cue]], keep_same: bool = False) -> list[dict]:
    """One row per English cue that some version has text for: its English
    and each version's Turkish, by time overlap. Rows where every version
    says the same are left out unless `keep_same`."""
    paired = {label: srt.pair(timing, cues) for label, cues in versions.items()}
    rows = []
    for t in timing:
        texts = {label: _cell([line for c in paired[label][t.n] for line in c.lines]) for label in versions}
        if not any(texts.values()):
            continue
        if not keep_same and len(set(texts.values())) == 1:
            continue
        rows.append({"cue": t.n, "time": srt.fmt_ms(t.start), "english": _cell(t.lines), "texts": texts})
    return rows


def write_rows(rows: list[dict], labels: list[str], out: Path, seed: int, parts: int = 1) -> dict:
    """Shuffle the versions to letters on each row and write the TSV files
    and key.json. Row ids run from 1 in film order."""
    _outside_repo(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    letters = LETTERS[: len(labels)]
    key: dict[str, dict] = {}
    lines = []
    for i, row in enumerate(rows, 1):
        order = labels[:]
        rng.shuffle(order)
        key[str(i)] = {"cue": row["cue"], "letters": dict(zip(letters, order))}
        cells = [str(i), row["time"], row["english"]] + [row["texts"][label] for label in order]
        lines.append("\t".join(cells))
    header = "\t".join(["id", "time", "english", *letters])
    parts = max(1, min(parts, len(lines) or 1))
    size, extra = divmod(len(lines), parts)  # the first `extra` parts take one row more, so none is empty
    files = []
    start = 0
    for p in range(parts):
        name = "rows.tsv" if parts == 1 else f"rows_{p + 1}.tsv"
        end = start + size + (1 if p < extra else 0)
        chunk = lines[start:end]
        start = end
        (out / name).write_text("\n".join([header, *chunk]) + "\n", encoding="utf-8")
        files.append(str(out / name))
    key_file = out / "key.json"
    key_file.write_text(json.dumps({"versions": labels, "seed": seed, "rows": key}, indent=1), encoding="utf-8")
    return {"rows": len(lines), "files": files, "key": str(key_file)}


def _places(rank: list[str]) -> dict[str, int]:
    """Letter -> place, 0 best, tied letters sharing a place:
    ["C", "A=B"] gives C 0, A 1, B 1."""
    places = {}
    for place, group in enumerate(rank):
        for letter in str(group).split("="):
            letter = letter.strip().upper()
            if letter:
                places[letter] = place
    return places


def unblind(key: dict, verdicts: list[dict]) -> dict:
    labels = key["versions"]
    stats = {label: {"judged": 0, "best_alone": 0, "worst": 0, "place_sum": 0, "problems": {}} for label in labels}
    pairs = {(a, b): {"a": a, "b": b, "a_wins": 0, "b_wins": 0, "ties": 0} for a, b in itertools.combinations(labels, 2)}
    unknown, incomplete = [], []
    for v in verdicts:
        row = key["rows"].get(str(v.get("id")))
        if row is None:
            unknown.append(v.get("id"))
            continue
        letters = row["letters"]
        places = _places(v.get("rank") or [])
        if set(places) != set(letters):
            incomplete.append(v.get("id"))
            continue
        place_of = {letters[x]: p for x, p in places.items()}
        last = max(place_of.values())
        for label, place in place_of.items():
            s = stats[label]
            s["judged"] += 1
            s["place_sum"] += place
            if place == 0 and list(place_of.values()).count(0) == 1:
                s["best_alone"] += 1
            if last > 0 and place == last:
                s["worst"] += 1
        for letter, kind in (v.get("problems") or {}).items():
            label = letters.get(str(letter).strip().upper())
            kind = str(kind).strip().lower()
            if label and kind and kind != "none":
                stats[label]["problems"][kind] = stats[label]["problems"].get(kind, 0) + 1
        for (a, b), h in pairs.items():
            if place_of[a] < place_of[b]:
                h["a_wins"] += 1
            elif place_of[b] < place_of[a]:
                h["b_wins"] += 1
            else:
                h["ties"] += 1
    versions = {}
    for label, s in stats.items():
        versions[label] = {
            "judged": s["judged"],
            "best_alone": s["best_alone"],
            "worst": s["worst"],
            "average_rank": round(s["place_sum"] / s["judged"], 3) if s["judged"] else None,
            "problems": dict(sorted(s["problems"].items(), key=lambda kv: -kv[1])),
        }
    return {
        "rows_judged": sum(1 for v in verdicts if str(v.get("id")) in key["rows"]) - len(incomplete),
        "unknown_ids": unknown,
        "incomplete_ranks": incomplete,
        "versions": versions,
        "head_to_head": list(pairs.values()),
    }


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rows")
    r.add_argument("--timing", type=result.path, required=True, help="the English timing file")
    r.add_argument("--version", type=_version, action="append", required=True, help="LABEL=PATH, two or three times")
    r.add_argument("--out", type=result.path, required=True)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--parts", type=int, default=1)
    r.add_argument("--all", action="store_true", help="keep rows where every version says the same")
    u = sub.add_parser("unblind")
    u.add_argument("--key", type=result.path, required=True)
    u.add_argument("--verdicts", type=result.path, action="append", required=True)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "rows":
        labels = [label for label, _ in a.version]
        if not 2 <= len(labels) <= 3 or len(set(labels)) != len(labels):
            raise SystemExit("give two or three --version LABEL=PATH, each label once")
        _outside_repo(a.out)
        timing, _ = srt.parse(a.timing)
        versions = {label: srt.parse(path)[0] for label, path in a.version}
        rows = build_rows(timing, versions, a.all)
        result.emit(write_rows(rows, labels, a.out, a.seed, a.parts), a.result)
    else:
        key = json.loads(a.key.read_text(encoding="utf-8"))
        verdicts = []
        for f in a.verdicts:
            verdicts += json.loads(f.read_text(encoding="utf-8"))
        result.emit(unblind(key, verdicts), a.result)


if __name__ == "__main__":
    main()
