import argparse
import json
from datetime import datetime
from pathlib import Path

import pytest
import usage


def marks(work: Path, *steps: tuple[str, str, list[str]]) -> None:
    for at, name, agents in steps:
        usage.record(work, name, [usage.agent_arg(a) for a in agents], at=at)


def test_groups_last_until_the_next_mark_and_done_ends_the_run(tmp_path: Path):
    marks(
        tmp_path,
        ("2026-11-12T20:00:00+01:00", "find", []),
        ("2026-11-12T20:01:30+01:00", "hints_bible", []),
        ("2026-11-12T20:10:00+01:00", "translate", ["bible-writer:84000:300000", "second-reader:75000:240000"]),
        ("2026-11-12T20:17:00+01:00", "done", ["translator:30000:120000", "translator:28000:110000"]),
    )
    s = usage.summary(tmp_path)["usage"]
    assert s["wall_minutes"] == 17.0
    assert [(st["name"], st["minutes"]) for st in s["steps"]] == [("find", 1.5), ("hints_bible", 8.5), ("translate", 7.0)]
    assert s["agents"]["translator"] == {
        "agents": 2,
        "tokens": 58000,
        "tokens_missing": 0,
        "agent_minutes": 3.8,
        "minutes_missing": 0,
    }
    assert s["subagent_tokens"] == 84000 + 75000 + 58000
    assert s["agent_count"] == s["agents_with_tokens"] == 4
    assert json.loads((tmp_path / "usage.json").read_text(encoding="utf-8")) == s


def test_a_number_the_notice_did_not_give_is_missing_never_guessed(tmp_path: Path):
    marks(
        tmp_path,
        ("2026-11-12T20:00:00+01:00", "review", ["reviewer:-:-", "translator:1000:-"]),
        ("2026-11-12T20:05:00+01:00", "done", []),
    )
    out = usage.summary(tmp_path)
    s = out["usage"]
    assert s["agents"]["reviewer"]["tokens"] is None
    assert s["agents"]["reviewer"]["agent_minutes"] is None
    assert s["subagent_tokens"] == 1000
    assert s["missing"][:2] == [
        "time of 2 of 2 agents: their notice gave no number",
        "tokens of 1 of 2 agents: their notice gave no number",
    ]
    assert "from 1 of 2 agents" in out["markdown"]
    assert "| reviewer | 1 | not given | not given |" in out["markdown"]


def test_a_run_never_marked_done_has_no_total_time(tmp_path: Path):
    marks(tmp_path, ("2026-11-12T20:00:00+01:00", "find", []), ("2026-11-12T20:02:00+01:00", "check", []))
    s = usage.summary(tmp_path)["usage"]
    assert s["wall_minutes"] is None
    assert s["steps"][-1]["minutes"] is None
    assert s["missing"][0].startswith("the total time")
    assert s["subagent_tokens"] is None


def test_the_report_names_what_a_run_cannot_see(tmp_path: Path):
    marks(tmp_path, ("2026-11-12T20:00:00+01:00", "find", []), ("2026-11-12T20:01:00+01:00", "done", []))
    md = usage.summary(tmp_path)["markdown"]
    assert md.startswith("## Time and usage\n")
    assert "No subagents were recorded." in md
    for line in usage.NOT_SEEN:
        assert f"- {line}" in md
    assert "$" not in md


@pytest.mark.parametrize("bad", ["translator", "translator:12k:5", "Translator:1:1", "x:1:2:3"])
def test_bad_agent_values_are_refused(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        usage.agent_arg(bad)


def test_cli_records_and_summarizes(tmp_path: Path, capsys):
    usage.main(["step", "--work", str(tmp_path), "--name", "find"])
    usage.main(["agent", "--work", str(tmp_path), "--agent", "reviewer:5:6"])
    usage.main(["step", "--work", str(tmp_path), "--name", "done"])
    capsys.readouterr()
    out = tmp_path / "out.json"
    usage.main(["--result", str(out), "summary", "--work", str(tmp_path)])
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["usage"]["agents"]["reviewer"]["tokens"] == 5
    assert saved["usage"]["wall_minutes"] is not None


def test_new_starts_afresh_and_at_file_dates_the_first_mark(tmp_path: Path):
    import os

    marks(tmp_path, ("2026-11-10T09:00:00+01:00", "find", ["reviewer:9:9"]), ("2026-11-10T09:30:00+01:00", "done", []))
    scan = tmp_path / "learn-scan.json"
    scan.write_text("{}", encoding="utf-8")
    then = datetime(2026, 11, 12, 20, 0, 0).timestamp()
    os.utime(scan, (then, then))
    out = usage.record(tmp_path, "find", [], new=True, at_file=scan)
    assert out["dated_by_file"] is True
    usage.record(tmp_path, "done", [], at="2026-11-12T20:12:00" + out["at"][19:])
    s = usage.summary(tmp_path)["usage"]
    assert s["wall_minutes"] == 12.0 and s["agent_count"] == 0


def test_a_missing_start_file_is_said_not_guessed(tmp_path: Path):
    usage.record(tmp_path, "find", [], new=True, at_file=tmp_path / "nope.json")
    usage.record(tmp_path, "done", [])
    s = usage.summary(tmp_path)["usage"]
    assert s["missing"][0] == "the time before the film was found: step 0's result file was missing"


def test_the_skill_marks_every_step_group():
    skill = (Path(__file__).resolve().parents[1] / "skills" / "subtitle" / "SKILL.md").read_text(encoding="utf-8")
    for name in [*usage.GROUPS, usage.END]:
        assert f"`{name}`" in skill, name
    assert "usage.py summary" in skill


def test_a_time_some_agents_did_not_give_is_named_in_the_cell(tmp_path: Path):
    marks(
        tmp_path,
        ("2026-11-12T20:00:00+01:00", "translate", ["translator:1000:-", "translator:2000:60000"]),
        ("2026-11-12T20:05:00+01:00", "done", []),
    )
    out = usage.summary(tmp_path)
    assert out["usage"]["agents"]["translator"]["minutes_missing"] == 1
    assert "| translator | 2 | 3,000 | 1.0 (1 not given) |" in out["markdown"]
    assert "- time of 1 of 2 agents: their notice gave no number" in out["markdown"]
