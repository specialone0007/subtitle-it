# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Record how long a run took and what its subagents used, for the report.

    uv run usage.py step    --work W --name NAME [--new] [--at-file F] [--agent KIND:TOKENS:MS ...]
    uv run usage.py agent   --work W --agent KIND:TOKENS:MS [--agent ...]
    uv run usage.py summary --work W
    uv run usage.py wait    --file F [--file ...] [--settle-s 20] [--timeout-min 60]

`step` marks the start of a group of steps (`find`, `hints_bible`,
`translate`, `polish`, `check`, `review`, `deliver`), and `done` marks the
end of the run. A group lasts until the next mark. Each mark is a line in
W/usage.jsonl with the time it was made. `--new` starts the log afresh,
for the first mark of a run, so a film translated again does not add to
the last run's figures. `--at-file F` dates the mark by F's modification
time instead of now: the first mark is made once the work folder is
known, and step 0's result file says when the run really started.

`agent` records subagents that finished: their kind, the tokens and the
milliseconds their completion notice gave. Write `-` for a number the
notice did not give; it is counted as missing, never guessed. `step` takes
the same `--agent` values, so the agents of one group are recorded in the
same call that starts the next.

`summary` writes W/usage.json and returns the "Time and usage" section for
report.md. It says plainly which figures it does not have: the main
session's own tokens, the split into new and cached tokens, and any agent
whose notice gave no number. It never gives a cost in money, since that
needs the split.

`wait` returns once every file exists and none has changed for
`--settle-s` seconds: a subagent's output is written. A subagent's
completion notice can come many minutes after its last file, so the skill
runs `wait` in the background beside the subagent and goes on when either
ends. It gives up after `--timeout-min` minutes with `"ready": false`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402

GROUPS = {
    "find": "0–2 · film and source subtitles",
    "hints_bible": "3–5 · speaker hints, bible and bible check",
    "translate": "6–7 · translation",
    "polish": "6–7 · polish: seed and fix",
    "check": "8–9 · assemble and check",
    "review": "10 · whole-film review",
    "deliver": "11 · delivery and report",
}
END = "done"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
NOT_SEEN = [
    "the main session's own tokens: a run cannot read them",
    "the split into new and cached tokens: completion notices give one total per agent",
    "a cost in money: it needs that split",
]


def agent_arg(text: str) -> dict:
    """`translator:61234:182000`, with `-` for a number the notice did not give."""
    parts = text.split(":")
    if len(parts) != 3 or not NAME_RE.match(parts[0]):
        raise argparse.ArgumentTypeError(f"expected KIND:TOKENS:MS, got {text!r}")
    nums = []
    for part in parts[1:]:
        if part == "-":
            nums.append(None)
        elif part.isdigit():
            nums.append(int(part))
        else:
            raise argparse.ArgumentTypeError(f"expected a whole number or -, got {part!r}")
    return {"kind": parts[0], "tokens": nums[0], "ms": nums[1]}


def step_arg(text: str) -> str:
    if text != END and not NAME_RE.match(text):
        raise argparse.ArgumentTypeError(f"not a step name: {text!r}")
    return text


def _log(work: Path) -> Path:
    return work / "usage.jsonl"


def _append(work: Path, rows: list[dict]) -> None:
    work.mkdir(parents=True, exist_ok=True)
    with _log(work).open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def file_time(path: Path) -> str | None:
    """A file's modification time, or None when it does not exist."""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def record(
    work: Path, step: str | None, agents: list[dict], at: str | None = None, new: bool = False, at_file: Path | None = None
) -> dict:
    """Append agents and a step mark to the log. With at_file, the mark takes
    that file's time; when the file is missing it takes now and says so."""
    now = _now()
    mark_at = at or now
    dated_by_file = None
    if at_file is not None:
        found = file_time(at_file)
        dated_by_file = found is not None
        mark_at = found or mark_at
    if new:
        _log(work).unlink(missing_ok=True)
    rows = [{"event": "agent", "at": at or now, **a} for a in agents]
    if step is not None:
        row = {"event": "step", "at": mark_at, "name": step}
        if dated_by_file is not None:
            row["dated_by_file"] = dated_by_file
        rows.append(row)
    _append(work, rows)
    return {"recorded": {"step": step, "agents": len(agents)}, "at": mark_at, "dated_by_file": dated_by_file}


def read(work: Path) -> list[dict]:
    if not _log(work).exists():
        return []
    rows = []
    for line in _log(work).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _minutes(a: str, b: str) -> float:
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60, 1)


def summarize(rows: list[dict]) -> dict:
    marks = [r for r in rows if r["event"] == "step"]
    steps = []
    for i, m in enumerate(marks):
        if m["name"] == END:
            continue
        nxt = marks[i + 1]["at"] if i + 1 < len(marks) else None
        steps.append(
            {
                "name": m["name"],
                "label": GROUPS.get(m["name"], m["name"]),
                "started": m["at"],
                "minutes": _minutes(m["at"], nxt) if nxt else None,
            }
        )
    ends = [m["at"] for m in marks if m["name"] == END]
    ended = bool(ends)
    wall = _minutes(marks[0]["at"], ends[-1]) if ended and marks[0]["name"] != END else None

    kinds: dict[str, dict] = {}
    for r in rows:
        if r["event"] != "agent":
            continue
        k = kinds.setdefault(r["kind"], {"agents": 0, "tokens": 0, "tokens_missing": 0, "ms": 0, "ms_missing": 0})
        k["agents"] += 1
        if r["tokens"] is None:
            k["tokens_missing"] += 1
        else:
            k["tokens"] += r["tokens"]
        if r["ms"] is None:
            k["ms_missing"] += 1
        else:
            k["ms"] += r["ms"]
    agents = sum(k["agents"] for k in kinds.values())
    reported = sum(k["agents"] - k["tokens_missing"] for k in kinds.values())
    missing = list(NOT_SEEN)
    if agents > reported:
        missing.insert(0, f"tokens of {agents - reported} of {agents} agents: their notice gave no number")
    timed = sum(k["agents"] - k["ms_missing"] for k in kinds.values())
    if agents > timed:
        missing.insert(0, f"time of {agents - timed} of {agents} agents: their notice gave no number")
    if not ended:
        missing.insert(0, "the total time and the last group's time: the run was never marked done")
    if marks and marks[0].get("dated_by_file") is False:
        missing.insert(0, "the time before the film was found: step 0's result file was missing")
    return {
        "wall_minutes": wall,
        "steps": steps,
        "agents": {
            name: {
                "agents": k["agents"],
                "tokens": k["tokens"] if k["tokens_missing"] < k["agents"] else None,
                "tokens_missing": k["tokens_missing"],
                "agent_minutes": round(k["ms"] / 60000, 1) if k["ms_missing"] < k["agents"] else None,
                "minutes_missing": k["ms_missing"],
            }
            for name, k in sorted(kinds.items())
        },
        "agent_count": agents,
        "agents_with_tokens": reported,
        "subagent_tokens": sum(k["tokens"] for k in kinds.values()) if reported else None,
        "missing": missing,
    }


def _num(n) -> str:
    return "not given" if n is None else f"{n:,}"


def markdown(s: dict) -> str:
    out = ["## Time and usage", ""]
    wall = "not known" if s["wall_minutes"] is None else f"{s['wall_minutes']} minutes"
    out += [f"Wall-clock time: {wall}.", ""]
    if s["steps"]:
        out += ["| Steps | Minutes |", "| --- | --- |"]
        for st in s["steps"]:
            out.append(f"| {st['label']} | {'not known' if st['minutes'] is None else st['minutes']} |")
        out.append("")
    if s["agents"]:
        out += ["| Agent | Count | Tokens | Agent minutes |", "| --- | --- | --- | --- |"]
        for name, k in s["agents"].items():
            tokens = _num(k["tokens"])
            if k["tokens"] is not None and k["tokens_missing"]:
                tokens += f" ({k['tokens_missing']} not given)"
            mins = "not given" if k["agent_minutes"] is None else str(k["agent_minutes"])
            if k["agent_minutes"] is not None and k["minutes_missing"]:
                mins += f" ({k['minutes_missing']} not given)"
            out.append(f"| {name} | {k['agents']} | {tokens} | {mins} |")
        out.append("")
        total = _num(s["subagent_tokens"])
        out += [
            f"Subagent tokens: {total}, from {s['agents_with_tokens']} of {s['agent_count']} agents, "
            "as their completion notices gave them. Agents that ran side by side overlap in time.",
            "",
        ]
    else:
        out += ["No subagents were recorded.", ""]
    out.append("Not recorded:")
    out += [f"- {m}" for m in s["missing"]]
    return "\n".join(out) + "\n"


def summary(work: Path) -> dict:
    s = summarize(read(work))
    (work / "usage.json").write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"usage": s, "markdown": markdown(s), "saved": str(work / "usage.json")}


def _state(files: list[Path]) -> tuple | None:
    """Size and modification time of each file, or None while one is missing."""
    out = []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            return None
        out.append((st.st_size, st.st_mtime_ns))
    return tuple(out)


def wait(files: list[Path], settle_s: float, timeout_min: float, poll_s: float = 2.0) -> dict:
    """Return once every file exists and stayed unchanged for settle_s seconds."""
    start = time.monotonic()
    deadline = start + timeout_min * 60
    last, since = None, start
    while True:
        now = time.monotonic()
        state = _state(files)
        if state != last:
            last, since = state, now
        elif state is not None and now - since >= settle_s:
            return {"ready": True, "files": [str(f) for f in files], "waited_s": round(now - start)}
        if now >= deadline:
            missing = [str(f) for f in files if not f.exists()]
            return {"ready": False, "missing": missing, "waited_s": round(now - start)}
        time.sleep(poll_s)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("step")
    s.add_argument("--work", type=result.path, required=True)
    s.add_argument("--name", type=step_arg, required=True)
    s.add_argument("--new", action="store_true", help="start the log afresh: the first mark of a run")
    s.add_argument("--at-file", type=result.path, help="date the mark by this file's modification time")
    s.add_argument("--agent", type=agent_arg, action="append", default=[])
    s = sub.add_parser("agent")
    s.add_argument("--work", type=result.path, required=True)
    s.add_argument("--agent", type=agent_arg, action="append", required=True)
    s = sub.add_parser("summary")
    s.add_argument("--work", type=result.path, required=True)
    s = sub.add_parser("wait")
    s.add_argument("--file", type=result.path, action="append", required=True)
    s.add_argument("--settle-s", type=float, default=20)
    s.add_argument("--timeout-min", type=float, default=60)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "step":
        result.emit(record(a.work, a.name, a.agent, new=a.new, at_file=a.at_file), a.result)
    elif a.cmd == "agent":
        result.emit(record(a.work, None, a.agent), a.result)
    elif a.cmd == "wait":
        result.emit(wait(a.file, a.settle_s, a.timeout_min), a.result)
    else:
        result.emit(summary(a.work), a.result)


if __name__ == "__main__":
    main()
