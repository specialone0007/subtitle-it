"""Seeding a run from an existing Turkish subtitle, and the flag list the
fixer works from."""

import json
from pathlib import Path

import pytest

import assemble
import polish
import prepare

EN = """1
00:00:01,000 --> 00:00:03,000
Come here.

2
00:00:03,500 --> 00:00:06,000
<i>It's cold.</i>

3
00:00:07,000 --> 00:00:09,000
- OK?
- Yes.

4
00:00:12,000 --> 00:00:14,000
I need to go now.

5
00:00:15,000 --> 00:00:17,000
See you tomorrow morning.

6
00:00:20,000 --> 00:00:22,000
Goodbye.
"""

# Cue 1 split in two, cue 2 without its italics, cue 3 without dashes,
# cue 5 left in English, cue 6 missing.
TR = """1
00:00:01,000 --> 00:00:01,900
Buraya

2
00:00:02,000 --> 00:00:03,000
gel.

3
00:00:03,500 --> 00:00:06,000
Hava soğuk.

4
00:00:07,000 --> 00:00:09,000
İyi misin?
Evet.

5
00:00:12,000 --> 00:00:14,000
Şimdi gitmem lazım.

6
00:00:15,000 --> 00:00:17,000
See you tomorrow morning.
"""


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "en.srt").write_text(EN, encoding="utf-8")
    (tmp_path / "tr.srt").write_text(TR, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    return w


def _seeded(work: Path) -> dict[int, list[str]]:
    texts, _ = assemble.load_translation(work)
    return texts


def test_seed_puts_the_turkish_on_the_timing_cues(work: Path, tmp_path: Path):
    out = polish.seed(work, tmp_path / "tr.srt")
    assert out["cues"] == 6
    assert out["seeded"] == 5
    assert out["without_turkish"] == 1
    assert out["joined"] == 1
    assert out["form_matched"] == 2
    texts = _seeded(work)
    assert texts[1] == ["Buraya", "gel."]
    assert texts[2] == ["<i>Hava soğuk.</i>"]
    assert texts[3] == ["- İyi misin?", "- Evet."]
    assert 6 not in texts


def test_seed_rewraps_joined_cues_that_grow_past_two_lines(tmp_path: Path):
    (tmp_path / "en.srt").write_text("1\n00:00:01,000 --> 00:00:05,000\nOne long English line here.\n", encoding="utf-8")
    parts = "".join(f"{i + 1}\n00:00:0{i + 1},000 --> 00:00:0{i + 1},900\nbir iki üç dört\n\n" for i in range(4))
    (tmp_path / "tr.srt").write_text(parts, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    out = polish.seed(w, tmp_path / "tr.srt")
    assert out["rewrapped"] == 1
    assert len(_seeded(w)[1]) == 2


def test_match_form_leaves_mixed_italics_alone():
    src = ["<i>Off screen</i> and on", "second"]
    tr = ["Ekran dışı ve içi", "ikinci"]
    assert polish.match_form(src, tr) == (tr, False)


def test_match_form_drops_italics_the_source_does_not_have():
    assert polish.match_form(["Plain."], ["<i>Düz.</i>"]) == (["Düz."], True)


def test_flags_lists_only_the_cues_to_fix(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    out = polish.flags(work)
    assert out["flagged"] == 2
    assert out["by_check"] == {"cue count": 1, "untranslated": 1}
    text = (work / polish.FLAG_FILE).read_text(encoding="utf-8")
    assert "#5 " in text and "flag: untranslated" in text
    assert "#6 " in text and "flag: cue count: missing" in text
    assert "#1 " not in text


def test_flags_leave_reading_speed_to_the_reviewer(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    fast = "Çok çok çok uzun bir cümle ki okumaya hiç vakit yok"
    (work / "out" / "fix_x.txt").write_text(f"1\n{fast}\n", encoding="utf-8")
    out = polish.flags(work)
    assert out["reading_speed_left_to_reviewer"] >= 1
    assert "reading speed" not in out["by_check"]


def test_untranslated_needs_two_words():
    assert polish.untranslated(["OK."], ["OK."]) is False
    assert polish.untranslated(["See you."], ["See you."]) is True
    assert polish.untranslated(["Görüşürüz."], ["See you."]) is False


def test_command_writes_the_result(work: Path, tmp_path: Path):
    res = tmp_path / "r.json"
    polish.main(["--result", str(res), "seed", "--work", str(work), "--tr", str(tmp_path / "tr.srt")])
    assert json.loads(res.read_text(encoding="utf-8"))["seeded"] == 5


def test_match_form_drops_dashes_the_source_does_not_have():
    assert polish.match_form(["Wait, who?"], ["- Bekle, kim?"]) == (["Bekle, kim?"], True)
    assert polish.match_form(["<i>Go on.</i>"], ["<i>- Devam et.</i>"]) == (["<i>Devam et.</i>"], True)


def test_sidebyside_works_without_chunks(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    assemble.sidebyside(work)
    text = (work / "sidebyside.tsv").read_text(encoding="utf-8")
    assert "Hava soğuk" in text and "chunk join" not in text
