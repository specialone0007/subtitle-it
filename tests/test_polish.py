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


def test_match_form_copies_italics_line_by_line():
    src = ["<i>Voice.</i>", "Real."]
    assert polish.match_form(src, ["Ses.", "Gerçek."]) == (["<i>Ses.</i>", "Gerçek."], True)


def test_match_form_drops_italics_the_source_does_not_have():
    assert polish.match_form(["Plain."], ["<i>Düz.</i>"]) == (["Düz."], True)


def test_flags_lists_only_the_cues_to_fix(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    out = polish.flags(work)
    assert out["flagged"] == 3
    assert out["by_check"] == {"cue count": 1, "untranslated": 1, "placement": 1}
    text = (work / polish.FLAG_FILE).read_text(encoding="utf-8")
    assert "#5 " in text and "flag: untranslated" in text
    assert "#6 " in text and "flag: cue count: missing" in text
    # A cue with no Turkish says so on its tr: line and in the header,
    # which names every such cue, so the fixer cannot skip one.
    assert "tr: <none: write this cue>" in text and polish.MISSING_FLAG in text
    assert text.splitlines()[1] == (
        "# 1 of them has no Turkish yet (tr: <none: write this cue>). Every one must be in your file, or the check fails: 6"
    )
    assert out["missing"] == 1 and out["missing_cues"] == [6]
    assert "#1 " in text and "flag: placement: two Turkish cues were joined" in text
    assert "#2 " not in text and "#3 " not in text


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


def test_soft_command_writes_the_result(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    res = tmp_path / "r.json"
    polish.main(["--result", str(res), "soft", "--work", str(work)])
    out = json.loads(res.read_text(encoding="utf-8"))
    assert out["left"] == 0 and out["cue_numbers"] == []
    assert (work / polish.SOFT_FILE).exists()


def test_match_form_drops_dashes_the_source_does_not_have():
    assert polish.match_form(["Wait, who?"], ["- Bekle, kim?"]) == (["Bekle, kim?"], True)
    assert polish.match_form(["<i>Go on.</i>"], ["<i>- Devam et.</i>"]) == (["<i>Devam et.</i>"], True)


def test_review_parts_work_without_chunks(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    (work / "chunks.json").unlink(missing_ok=True)
    text = "\n".join(Path(assemble.review_parts(work)["parts"][0]["file"]).read_text(encoding="utf-8").splitlines()[2:])
    assert "Hava soğuk" in text and "chunk join" not in text


def test_toned_down_spots_a_softened_line():
    assert polish.toned_down(["Kötü bir film izliyor."], ["He's watching porn."]) == "porn"
    assert polish.toned_down(["Porno izliyor."], ["He's watching porn."]) is None
    assert polish.toned_down(["Siktir git."], ["Fuck off."]) is None


def test_toned_down_ignores_words_that_only_look_crude():
    assert polish.toned_down(["Kokteyl ister misin?"], ["A cocktail?"]) is None
    assert polish.toned_down(["Bunu götürmem lazım."], ["I need to take this."]) is None
    assert polish.toned_down(["Boks maçı."], ["Shitty boxing match."]) == "shit"
    assert polish.toned_down(["Hadi ama, yine mi?"], ["Oh shit, not again?"]) == "shit"
    assert polish.toned_down(["Kahrolası kapı."], ["Damn door."]) is None
    assert polish.toned_down(["Kahramanlar hep geç kalır."], ["Heroes are always damn late."]) == "damn"


def test_flags_lists_toned_down_and_misplaced_cues(tmp_path: Path):
    en = (
        "1\n00:00:01,000 --> 00:00:03,000\nGet the fuck out.\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nFine.\n\n"
        "3\n00:00:12,000 --> 00:00:14,000\nBye.\n"
    )
    tr = (
        "1\n00:00:01,000 --> 00:00:03,000\nÇık dışarı.\n\n"
        "2\n00:00:05,000 --> 00:00:05,900\nPeki,\n\n"
        "3\n00:00:06,000 --> 00:00:07,000\ntamam.\n\n"
        "4\n00:00:09,000 --> 00:00:10,500\nŞEHİR MERKEZİ\n\n"
        "5\n00:00:12,000 --> 00:00:14,000\nHoşça kal.\n"
    )
    (tmp_path / "en.srt").write_text(en, encoding="utf-8")
    (tmp_path / "tr.srt").write_text(tr, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    polish.seed(w, tmp_path / "tr.srt")
    placement = json.loads((w / polish.PLACEMENT_FILE).read_text(encoding="utf-8"))
    assert placement["joined"] == [2]
    assert placement["unplaced"] == [{"near": [2, 3], "text": "ŞEHİR MERKEZİ"}]
    out = polish.flags(w)
    assert out["by_check"]["toned down"] == 1
    assert out["by_check"]["placement"] == 2
    text = (w / polish.FLAG_FILE).read_text(encoding="utf-8")
    assert 'toned down: the English says "fuck"' in text
    assert "landed on no cue: ŞEHİR MERKEZİ" in text


def test_review_parts_mark_no_joins_in_a_seeded_run(work: Path, tmp_path: Path):
    prepare.chunks(work, 2)
    polish.seed(work, tmp_path / "tr.srt")
    assert "chunk join" not in "\n".join(
        Path(assemble.review_parts(work)["parts"][0]["file"]).read_text(encoding="utf-8").splitlines()[2:]
    )


def test_review_parts_show_the_fixers_flags(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    polish.flags(work)
    flagged = {
        int(ln[1:].split()[0]) for ln in (work / polish.FLAG_FILE).read_text(encoding="utf-8").splitlines() if ln[1:2].isdigit()
    }
    rows = {
        ln.split("\t")[0]: ln.split("\t")[4:6]
        for ln in Path(assemble.review_parts(work)["parts"][0]["file"]).read_text(encoding="utf-8").splitlines()[2:]
    }
    shown = [rows[str(n)] for n in flagged if str(n) in rows]
    assert shown and all("fixer: " in note for tr, note in shown if tr != "<MISSING>")
    # A cue with no Turkish says so in its Turkish field: the fixer's
    # "cue count: missing" flag would only repeat it (the check's hard fail stays).
    assert any(tr == "<MISSING>" for tr, _ in shown)
    assert not any("fixer: cue count: missing" in note for _, note in shown)


def test_flags_skip_a_fixed_cue_the_timing_file_does_not_have(work: Path, tmp_path: Path):
    polish.seed(work, tmp_path / "tr.srt")
    (work / "out" / "fix_polish.txt").write_text("99\nFazladan.\n", encoding="utf-8")
    out = polish.flags(work)
    assert "#99 " not in (work / polish.FLAG_FILE).read_text(encoding="utf-8")
    assert out["flagged"] >= 1


def test_toned_down_needs_a_strong_word_for_a_strong_one():
    assert polish.toned_down(["Lanet olsun."], ["Fuck."]) == "fuck"
    assert polish.toned_down(["Siktir."], ["Fuck."]) is None
    assert polish.toned_down(["Lanet olsun."], ["Damn it."]) is None
    assert polish.toned_down(["Kahretsin."], ["Shit."]) is None
    assert polish.toned_down(["Siktir."], ["Shit."]) is None
    assert polish.toned_down(["Onunla yattım."], ["I fucked her."]) == "fuck"


def test_soft_lists_what_the_fixes_left_soft(tmp_path: Path):
    en = "1\n00:00:01,000 --> 00:00:03,000\nFuck off.\n\n2\n00:00:05,000 --> 00:00:07,000\nShit.\n"
    tr = "1\n00:00:01,000 --> 00:00:03,000\nDefol.\n\n2\n00:00:05,000 --> 00:00:07,000\nOlamaz.\n"
    (tmp_path / "en.srt").write_text(en, encoding="utf-8")
    (tmp_path / "tr.srt").write_text(tr, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    polish.seed(w, tmp_path / "tr.srt")
    assert polish.soft(w)["cue_numbers"] == [1, 2]
    (w / "out" / "fix_polish.txt").write_text("1\nSiktir git.\n", encoding="utf-8")
    out = polish.soft(w)
    assert out["left"] == 1 and out["cue_numbers"] == [2]
    text = (w / polish.SOFT_FILE).read_text(encoding="utf-8")
    assert "#2 " in text and 'the English says "shit"' in text and "#1 " not in text


def test_flags_leave_sen_and_siz_to_the_reviewers(tmp_path: Path):
    en = (
        "1\n00:00:01,000 --> 00:00:03,000\nNora, sit down.\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nAre you comfortable?\n\n"
        "3\n00:00:20,000 --> 00:00:22,000\nAre you ready?\n"
    )
    tr = (
        "1\n00:00:01,000 --> 00:00:03,000\nNora, sen otur.\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nRahat mısın?\n\n"
        "3\n00:00:20,000 --> 00:00:22,000\nHazır mısın?\n"
    )
    (tmp_path / "en.srt").write_text(en, encoding="utf-8")
    (tmp_path / "tr.srt").write_text(tr, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    decisions = {
        "characters": [{"name": "Sam", "aliases": []}, {"name": "Nora", "aliases": []}],
        "decisions": [
            {
                "id": "address:Sam>Nora",
                "kind": "address",
                "speaker": "Sam",
                "listener": "Nora",
                "question": "Does Sam say sen or siz to Nora?",
                "answer": [{"from_cue": 1, "form": "siz"}],
                "evidence": [1],
                "confidence": "sure",
            }
        ],
    }
    (w / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    (w / "speakers.json").write_text(json.dumps({"1": {"label": "Sam"}}), encoding="utf-8")
    polish.seed(w, tmp_path / "tr.srt")
    out = polish.flags(w)
    # The check still sees cue 1's sen against the bible's siz, but the
    # human file's form is the evidence: nothing goes to the fixer.
    assert any(x["check"] == "address form" for x in assemble.run_checks(w)["warnings"])
    assert not any(k.startswith("address form") for k in out["by_check"])
    text = (w / polish.FLAG_FILE).read_text(encoding="utf-8")
    assert "#1 " not in text and "#2 " not in text


SPLIT_EN = """1
00:00:01,000 --> 00:00:03,000
[Door creaks]

2
00:00:05,000 --> 00:00:13,000
- I told you before, don't you remember?
- I do, but you said something else then.

3
00:00:14,000 --> 00:00:16,000
SAM: Fine.
"""

# A file this plugin delivered: the sound-only cue left out, the
# two-speaker cue split at the speaker change, renumbered from 1.
SPLIT_TR = """1
00:00:05,000 --> 00:00:09,200
Bunu sana daha önce söylemiştim,
hatırlamıyor musun?

2
00:00:09,320 --> 00:00:13,000
Hatırlıyorum ama o zaman
başka bir şey demiştin.

3
00:00:14,000 --> 00:00:16,000
SAM: Peki.
"""


def test_seed_from_a_delivered_file_joins_a_split_cue_back_by_speaker(tmp_path: Path):
    (tmp_path / "en.srt").write_text(SPLIT_EN, encoding="utf-8")
    (tmp_path / "tr.srt").write_text(SPLIT_TR, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    out = polish.seed(w, tmp_path / "tr.srt")
    assert out["cues"] == 2 and out["seeded"] == 2 and out["turkish_cues_with_tags_or_labels_removed"] == 1
    texts = _seeded(w)
    assert 1 not in texts
    assert texts[2] == [
        "- Bunu sana daha önce söylemiştim, hatırlamıyor musun?",
        "- Hatırlıyorum ama o zaman başka bir şey demiştin.",
    ]
    assert texts[3] == ["Peki."]
    # The layout step splits it again on check.
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["split_cues"] == 1 and r["delivered_cues"] == 3


def _numbered(texts: list[str]) -> str:
    return "\n".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},800\n{t}\n" for i, t in enumerate(texts, 1))


@pytest.mark.parametrize("flagged", [True, False])
def test_seed_cleans_the_turkish_by_its_own_flag(tmp_path: Path, flagged: bool):
    # A plain Turkish file keeps its parentheses and headings; a
    # hearing-impaired one loses the description.
    (tmp_path / "en.srt").write_text(_numbered([f"Line {i}." for i in range(40)]), encoding="utf-8")
    rest = [f"[güler] Satır {i}." if flagged else f"Satır {i}." for i in range(37)]
    tr = ["Evet (iç çeker).", "(Orada mısın?)", "BÖLÜM 1: Başlangıç"] + rest
    (tmp_path / "tr.srt").write_text(_numbered(tr), encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    polish.seed(w, tmp_path / "tr.srt")
    texts = _seeded(w)
    assert texts[1] == (["Evet."] if flagged else ["Evet (iç çeker)."])
    assert texts[2] == ["(Orada mısın?)"] and texts[3] == ["BÖLÜM 1: Başlangıç"]
