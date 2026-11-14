"""Stray source italics and the fix round: one-word italics in the source
are no hard fail, and a fix round starts from the Turkish a cue has now."""

import json
import os
from pathlib import Path

import pytest

import assemble
import prepare

EN = """1
00:00:01,000 --> 00:00:03,000
<i>To</i> all Marc Antony's cavalry,
Caesar's left wing and right arm.

2
00:00:03,500 --> 00:00:06,000
We've gotten <i>off</i> to a bad start.

3
00:00:07,000 --> 00:00:09,000
<i>A voice from far away.</i>

4
00:00:12,000 --> 00:00:14,000
<i>Two words</i> here.

5
00:00:15,000 --> 00:00:17,000
Plain line.
"""

GOOD = (
    "1\nMarc Antonius'un tüm süvarilerine,\nSezar'ın sol kanadı ve sağ kolu.\n\n"
    "2\nKötü bir başlangıç yaptık.\n\n"
    "3\n<i>Uzaktan bir ses.</i>\n\n"
    "4\n<i>İki kelime</i> burada.\n\n"
    "5\nDüz satır.\n"
)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "en.srt").write_text(EN, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, None)
    prepare.chunks(w, target=250)
    return w


def _checks(r: dict, kind: str) -> set[tuple[int, str]]:
    return {(x["cue"], x["check"]) for x in r[kind]}


@pytest.mark.parametrize(
    ("lines", "stray"),
    [
        (["<i>To</i> all Marc Antony's cavalry,", "Caesar's left wing."], True),
        (["We've gotten <i>off</i> to a bad start."], True),
        (["<i>To</i> drain the marshes.", "<i>To</i> free Rome."], True),
        (["<i>A voice from far away.</i>"], False),
        (["<i>Two words</i> here."], False),
        (["<i>Alone</i>"], False),
        (["<i>To</i>"], False),
        (["Plain."], False),
        (["<i>To all", "of them.</i>"], False),
    ],
)
def test_word_italics(lines: list[str], stray: bool):
    assert assemble.word_italics(lines) is stray


def test_stray_source_italics_are_no_hard_fail(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert not any(x["check"] == "stray italics" for x in r["warnings"])


def test_stray_italics_copied_onto_turkish_is_a_warning(work: Path):
    copied = GOOD.replace("Kötü bir başlangıç", "<i>Kötü</i> bir başlangıç")
    (work / "out" / "tr_01.txt").write_text(copied, encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert (2, "stray italics") in _checks(r, "warnings")


def test_whole_line_and_phrase_italics_still_must_match(work: Path):
    bad = GOOD.replace("<i>Uzaktan bir ses.</i>", "Uzaktan bir ses.").replace("<i>İki kelime</i>", "İki kelime")
    (work / "out" / "tr_01.txt").write_text(bad, encoding="utf-8")
    hard = _checks(assemble.run_checks(work), "hard")
    assert {(3, "italic tags"), (4, "italic tags")} <= hard
    # Italics the source does not have are still a hard fail.
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Düz satır.", "<i>Düz satır.</i>"), encoding="utf-8")
    assert (5, "italic tags") in _checks(assemble.run_checks(work), "hard")


def test_fix_round_hands_over_the_current_turkish(work: Path):
    out = work / "out"
    # A polish run: only tr_00.txt (the seed) and fix files exist. The
    # seed lost cue 3's italics; the reviewer then reworded cue 3 without
    # them, and the polish fixer touched cue 5.
    (out / "tr_00.txt").write_text(GOOD.replace("<i>Uzaktan bir ses.</i>", "Uzaktan ses."), encoding="utf-8")
    (out / "fix_polish.txt").write_text("5\nDümdüz satır.\n", encoding="utf-8")
    (out / "fix_review.txt").write_text("3\nTa uzaklardan bir ses.\n", encoding="utf-8")
    t = (out / "tr_00.txt").stat().st_mtime
    os.utime(out / "fix_polish.txt", (t + 10, t + 10))
    os.utime(out / "fix_review.txt", (t + 20, t + 20))
    assemble.run_checks(work)

    r = assemble.fix_round(work, "r1")
    assert r["cues"] == 1 and r["outside_chunks"] == [] and r["no_cue"] == []
    [group] = r["chunks"]
    assert group["cues"] == [3]
    assert group["write_to"] == str(out / "fix_r1_01.txt")
    assert group["flags_to"] == str(out / "flags_r1_01.txt")
    text = Path(group["fix_file"]).read_text(encoding="utf-8")
    # The reviewed wording, not the seed and not a fresh translation.
    assert (
        "#3\nfail: italic tags (source and Turkish differ)\nsrc: <i>A voice from far away.</i>\nnow:\nTa uzaklardan bir ses.\n"
        in text
    )
    assert "#5" not in text and "#1" not in text
    # The file stays out of W/out, so `check` and `deliver` never see it.
    assert Path(group["fix_file"]).parent == work / assemble.FIX_DIR
    assert not list(out.glob("*r1*"))


def test_fix_round_marks_a_cue_with_no_turkish(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.split("\n\n5\n")[0] + "\n", encoding="utf-8")
    assemble.run_checks(work)
    r = assemble.fix_round(work, "post")
    text = Path(r["chunks"][0]["fix_file"]).read_text(encoding="utf-8")
    assert "#5\nfail: cue count (missing)\n" in text and f"now:\n{assemble.NO_TURKISH}\n" in text
    assert r["chunks"][0]["write_to"].endswith("fix_post_01.txt")


def test_fix_round_replaces_its_own_old_files_only(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Düz satır.", "<i>Düz satır.</i>"), encoding="utf-8")
    assemble.run_checks(work)
    fixes = work / assemble.FIX_DIR
    fixes.mkdir()
    (fixes / "r1_09.txt").write_text("old", encoding="utf-8")
    (fixes / "r2_01.txt").write_text("other round", encoding="utf-8")
    assemble.fix_round(work, "r1")
    assert sorted(p.name for p in fixes.iterdir()) == ["r1_01.txt", "r2_01.txt"]


def test_fix_round_rejects_a_label_that_is_a_path(work: Path):
    (work / "checks.json").write_text(json.dumps({"hard": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        assemble.fix_round(work, "../r1")


def test_the_skill_runs_fixround_and_the_translator_starts_from_now():
    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills" / "translate" / "SKILL.md").read_text(encoding="utf-8")
    bullet = next(line for line in skill.splitlines() if line.startswith("- Hard fails:"))
    assert "assemble.py fixround --work WORK --round r<round>" in bullet and "Fix round." in bullet
    agent = (root / "agents" / "translator.md").read_text(encoding="utf-8")
    assert "## Fix round" in agent and "Start from `now`" in agent and "read the pack and the bible" in agent
