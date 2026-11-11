"""End-to-end over the scripts with a tiny fake film: build, chunk,
translate (by hand), check, review file, deliver, learn."""

import json
from pathlib import Path

import pytest

import assemble
import learn
import prepare
import srt

FR = """1
00:00:01,000 --> 00:00:03,000
SANDRA: Viens.

2
00:00:03,500 --> 00:00:06,000
<i>Il fait froid.</i>

3
00:00:07,000 --> 00:00:09,000
- Ça va ?
- Oui.

4
00:00:12,000 --> 00:00:14,000
D'accord.
"""

EN = """1
00:00:01,100 --> 00:00:02,900
SANDRA: Come.

2
00:00:03,600 --> 00:00:05,900
<i>It's cold.</i>

3
00:00:07,000 --> 00:00:09,000
- OK?
- Yes.

4
00:00:12,000 --> 00:00:14,000
Okay.
"""

GOOD = "1\nGel.\n\n2\n<i>Hava soğuk.</i>\n\n3\n- İyi misin?\n- Evet.\n\n4\nTamam.\n"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "fr.srt").write_text(FR, encoding="utf-8")
    (tmp_path / "en.srt").write_text(EN, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, tmp_path / "en.srt")
    prepare.chunks(w, target=250)
    return w


def test_build_pairs_english_and_finds_speaker(work: Path):
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    assert rows[0]["source"] == ["SANDRA: Viens."]
    assert rows[0]["en"] == ["SANDRA: Come."]
    speakers = json.loads((work / "speakers.json").read_text(encoding="utf-8"))
    assert speakers["1"]["label"] == "Sandra"
    chunk = (work / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    assert "#1 00:00:01 [Sandra]" in chunk and "src: - Ça va ? / - Oui." in chunk


def test_check_passes_and_writes_draft(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["warning_count"] == 0, r["warnings"]
    back, _ = srt.parse(work / "draft.tr.srt")
    assert [c.ts for c in back] == [c.ts for c in srt.parse(work / "timing.srt")[0]]


def test_check_hard_fails_and_warnings(work: Path):
    bad = "1\nGelmek.\n\n2\nHava soğuk.\n\n3\nİyi misin? Evet.\n\n4\nTAMAM.\n"
    (work / "out" / "tr_01.txt").write_text(bad, encoding="utf-8")
    r = assemble.run_checks(work)
    hard = {(x["cue"], x["check"]) for x in r["hard"]}
    assert (2, "italic tags") in hard and (3, "dialogue dashes") in hard
    warns = {(x["cue"], x["check"]) for x in r["warnings"]}
    assert (1, "infinitive command") in warns and (4, "caps") in warns


def test_missing_cue_blocks_draft(work: Path):
    (work / "out" / "tr_01.txt").write_text("1\nGel.\n", encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["draft"] is None
    assert sum(1 for x in r["hard"] if x["detail"] == "missing") == 3


def test_fix_files_override(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "TAMAM."), encoding="utf-8")
    (work / "out" / "fix_r1.txt").write_text("4\nTamam.\n", encoding="utf-8")
    assert assemble.run_checks(work)["warning_count"] == 0


def test_glossary_variant_warning(work: Path):
    (work / "glossary.json").write_text(json.dumps({"Tamam": ["Peki"]}), encoding="utf-8")
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "Peki."), encoding="utf-8")
    r = assemble.run_checks(work)
    assert [x["check"] for x in r["warnings"]] == ["term variant"]


def test_sidebyside(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    p = assemble.sidebyside(work)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "1\tSandra\tSANDRA: Viens.\tGel."


def test_deliver_backs_up_and_learn_finds_swaps(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Evet.", "Peki."), encoding="utf-8")
    assemble.run_checks(work)
    dest = tmp_path / "Film.tr.srt"
    dest.write_text("old", encoding="utf-8")
    backups = tmp_path / "backups"
    info = assemble.deliver(work, dest, backups, force=False)
    assert Path(info["backup_of_old_file"]).read_text(encoding="utf-8") == "old"
    assert not (work / "chunks").exists()

    films = tmp_path / "data" / "films"
    films.mkdir(parents=True)
    assert learn.scan(tmp_path / "data") == []
    work.rename(films / "film")
    w2 = films / "film"
    assert learn.scan(tmp_path / "data") == []
    text = dest.read_text(encoding="utf-8").replace("Peki.", "Tamam.").replace("Gel.", "Gel buraya.")
    dest.write_bytes(text.replace("\n", "\r\n").encode())
    assert [x["file"] for x in learn.scan(tmp_path / "data")] == [str(dest)]
    d = learn.diff(w2)
    assert d["cues_edited"] == 2
    learn.mark_learned(w2)
    assert learn.scan(tmp_path / "data") == []


def test_deliver_refuses_hard_fails(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("<i>Hava soğuk.</i>", "Hava soğuk."), encoding="utf-8")
    assemble.run_checks(work)
    with pytest.raises(SystemExit):
        assemble.deliver(work, tmp_path / "x.tr.srt", tmp_path / "b", force=False)
    assemble.deliver(work, tmp_path / "x.tr.srt", tmp_path / "b", force=True)
