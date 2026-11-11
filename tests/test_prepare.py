import json
from pathlib import Path

import assemble
import prepare


def test_cue_label_one_speaker_takes_the_first_label():
    assert prepare.cue_label(["SANDRA: Come.", "Now."]) == "Sandra"
    assert prepare.cue_label(["- SANDRA: Come."]) == "Sandra"
    assert prepare.cue_label(["Come."]) is None


def test_cue_label_names_each_dash_line_of_a_two_speaker_cue():
    assert prepare.cue_label(["- Who is it?", "- IVY: Me."]) == "? / Ivy"
    assert prepare.cue_label(["- SAM: Who?", "<i>- IVY: Me.</i>"]) == "Sam / Ivy"
    # A line without a dash belongs to the dash line above it.
    assert prepare.cue_label(["- Who is", "it?", "- IVY: Me."]) == "? / Ivy"
    assert prepare.cue_label(["- Who?", "- Me."]) is None


def test_speaker_hint_shows_name_or_label_and_voice():
    assert prepare.speaker_hint({"label": "Ivy", "voice": "V3"}) == "Ivy · V3"
    assert prepare.speaker_hint({"name": "Ivy", "label": "Ivana", "voice": "V3"}) == "Ivy · V3"
    assert prepare.speaker_hint({"voice": "V3"}) == "V3"
    assert prepare.speaker_hint({"label": "Ivy"}) == "Ivy"
    assert prepare.speaker_hint({}) == ""


SRT = """1
00:00:01,000 --> 00:00:03,000
- Who is it?
- IVY: Me.

2
00:00:04,000 --> 00:00:06,000
Come in.
"""


def test_chunks_and_review_file_show_label_and_voice(tmp_path: Path):
    (tmp_path / "en.srt").write_text(SRT, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, None)
    assert json.loads((w / "speakers.json").read_text(encoding="utf-8")) == {"1": {"label": "? / Ivy"}}
    hints = {"1": {"label": "? / Ivy", "voice": "V2"}, "2": {"voice": "V1"}}
    (w / "speakers.json").write_text(json.dumps(hints), encoding="utf-8")
    prepare.chunks(w, target=250)
    chunk = (w / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    assert "#1 00:00:01 [? / Ivy · V2]" in chunk and "#2 00:00:04 [V1]" in chunk
    (w / "out" / "tr_01.txt").write_text("1\n- Kim o?\n- Benim.\n\n2\nGir.\n", encoding="utf-8")
    lines = assemble.sidebyside(w).read_text(encoding="utf-8").splitlines()
    assert lines[1].split("\t")[1] == "? / Ivy · V2" and lines[2].split("\t")[1] == "V1"
