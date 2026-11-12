"""Hearing-impaired text: sound descriptions and speaker labels found,
removed from every text the agents see, and kept out of the Turkish."""

import json
from pathlib import Path

import pytest

import assemble
import prepare
import srt


@pytest.mark.parametrize(
    ("line", "text", "label"),
    [
        ("[Door slams]", "", None),
        ("(door slams)", "", None),
        ("[Laughs] Yes.", "Yes.", None),
        ("Yes. (sighs)", "Yes.", None),
        ("SANDRA: Who's there?", "Who's there?", "SANDRA"),
        ("- SANDRA: Who's there?", "- Who's there?", "SANDRA"),
        ("[Sandra] Who's there?", "Who's there?", "Sandra"),
        ("[1. Man] Over here.", "Over here.", "Man"),
        ("-[Sandra] Over here.", "- Over here.", "Sandra"),
        ("<i>[Thunder]</i>", "", None),
        ("<i>[Thunder] Run!</i>", "<i>Run!</i>", None),
        ("- (gasps) Run!", "- Run!", None),
        ("Yes [laughs].", "Yes.", None),
        ("[Scoffs] Yeah.", "Yeah.", None),
        ("[Gunshot] Get down!", "Get down!", None),
        ("[Exhales] Okay.", "Okay.", None),
        ("[IN SPANISH] Hola.", "Hola.", None),
        ("[BANG] Get down!", "Get down!", None),
        ("[SANDRA]: Hi.", "Hi.", "SANDRA"),
        ("- [Siren wailing] Move!", "- Move!", None),
        ("[rire] Quoi ?", "Quoi ?", None),
        ("Quoi ?", "Quoi ?", None),
        ("♪ Coming back for me ♪", "♪ Coming back for me ♪", None),
        ("Rule one: never lie.", "Rule one: never lie.", None),
        ("10:30: meet me.", "10:30: meet me.", None),
        ("Who's there?", "Who's there?", None),
    ],
)
def test_clean_line_drops_descriptions_and_labels_and_keeps_speech(line, text, label):
    c = srt.clean_line(line, hi=True)
    assert c.text == text and c.label == label


# (line, text in a hearing-impaired file, text in a plain file, label in both)
SPEECH_OR_TAG = [
    ("(Are you there?)", "(Are you there?)", "(Are you there?)", None),
    ("(Wait!) Come back.", "(Wait!) Come back.", "(Wait!) Come back.", None),
    ("I said (and I mean it) no.", "I said (and I mean it) no.", "I said (and I mean it) no.", None),
    ("DAY 3: we leave.", "DAY 3: we leave.", "DAY 3: we leave.", None),
    ("WARNING: HIGH VOLTAGE", "WARNING: HIGH VOLTAGE", "WARNING: HIGH VOLTAGE", None),
    ("OK: let's go.", "OK: let's go.", "OK: let's go.", None),
    ("AT 10: meet me", "AT 10: meet me", "AT 10: meet me", None),
    ("BÖLÜM 1: Başlangıç", "BÖLÜM 1: Başlangıç", "BÖLÜM 1: Başlangıç", None),
    ("UYARI: Yüksek gerilim", "UYARI: Yüksek gerilim", "UYARI: Yüksek gerilim", None),
    ("ANNA MARIA LOUISE KAY: Hi.", "ANNA MARIA LOUISE KAY: Hi.", "ANNA MARIA LOUISE KAY: Hi.", None),
    ("SANDRA: Who's there?", "Who's there?", "SANDRA: Who's there?", "SANDRA"),
    ("- ŞULE: Merhaba.", "- Merhaba.", "- ŞULE: Merhaba.", "ŞULE"),
    ("MR. O'NEIL: Sit.", "Sit.", "MR. O'NEIL: Sit.", "MR. O'NEIL"),
    ("[Man 2] Hi.", "Hi.", "Hi.", "Man 2"),
    ("[Guard 2]: Stop.", "Stop.", "Stop.", "Guard 2"),
    ("(door slams)", "", "(door slams)", None),
    ("Yes (sighs) okay.", "Yes okay.", "Yes (sighs) okay.", None),
    ("[Door slams]", "", "", None),
    ("Fine. [door slams]", "Fine.", "Fine.", None),
]


@pytest.mark.parametrize(("line", "hi_text", "plain_text", "label"), SPEECH_OR_TAG)
def test_clean_line_follows_the_files_flag(line, hi_text, plain_text, label):
    hi, plain = srt.clean_line(line, hi=True), srt.clean_line(line, hi=False)
    assert (hi.text, hi.label) == (hi_text, label)
    assert (plain.text, plain.label) == (plain_text, label)
    # Nothing removed means nothing found: the line counts as untouched.
    assert plain.found == (plain_text != line)


def test_strip_hi_drops_sound_lines_and_an_orphan_dash():
    lines, names, found = srt.strip_hi(["- [Door slams]", "- SANDRA: Who's there?"])
    assert lines == ["Who's there?"] and names == ["SANDRA"] and found
    lines, _, found = srt.strip_hi(["- Who?", "- Me."])
    assert lines == ["- Who?", "- Me."] and not found
    assert srt.strip_hi(["[Thunder rumbling]", "(rain)"])[0] == []


def _cues(texts: list[str]) -> list[srt.Cue]:
    return [srt.Cue(n=i, start=i * 1000, end=i * 1000 + 500, ts="", lines=[t]) for i, t in enumerate(texts, 1)]


def test_hearing_impaired_is_judged_by_the_share_of_tagged_cues():
    plain = [f"Line {i}." for i in range(100)]
    assert srt.hearing_impaired(_cues(plain))["hearing_impaired"] is False
    two = plain[:98] + ["[Laughs] Yes.", "SAM: No."]
    assert srt.hearing_impaired(_cues(two))["hearing_impaired"] is False
    three = plain[:97] + ["[Laughs] Yes.", "SAM: No.", "(sighs)"]
    assert srt.hearing_impaired(_cues(three))["hearing_impaired"] is True  # exactly 3% counts
    film = [f"Line {i}." for i in range(1455)] + ["(sighs)"] * 45
    assert srt.hearing_impaired(_cues(film))["hearing_impaired"] is True  # the docstring's 45 of 1,500
    five = plain[:95] + ["[Laughs] Yes.", "SAM: No.", "(sighs)", "[Man] Hey.", "Fine. [door slams]"]
    out = srt.hearing_impaired(_cues(five))
    assert out == {"hearing_impaired": True, "cues_with_tags_or_labels": 5, "share": 0.05}


def test_is_sound_covers_bracketed_names_with_no_speech():
    assert srt.is_sound(_cues(["[Sandra]"])[0])
    assert not srt.is_sound(_cues(["[Sandra] Come."])[0])


FR = """1
00:00:01,000 --> 00:00:03,000
[Door slams]
SANDRA: Viens.

2
00:00:03,500 --> 00:00:06,000
[Thunder rumbling]

3
00:00:07,000 --> 00:00:09,000
[Daniel] Tu es là ?

4
00:00:10,000 --> 00:00:12,000
♪ La nuit tombe ♪
"""


def built(films: Path, hi: str = "remove") -> Path:
    w = films / "work"
    prepare.build(w, films / "fr.srt", None, None, hi=hi)
    prepare.chunks(w, target=250)
    return w


@pytest.fixture
def films(tmp_path: Path) -> Path:
    (tmp_path / "fr.srt").write_text(FR, encoding="utf-8")
    return tmp_path


def test_build_removes_tags_and_labels_and_leaves_out_sound_only_cues(films: Path):
    w = films / "work"
    out = prepare.build(w, films / "fr.srt", None, None)
    assert out["hearing_impaired"] == {"timing": True}
    assert out["sound_only_cues_dropped"] == 1 and out["cues_with_tags_or_labels_removed"] == 3
    assert out["cues_with_speaker_label"] == 2 and out["hearing_impaired_tags"] == "remove"
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert [r["source"] for r in rows] == [["Viens."], [], ["Tu es là ?"], ["♪ La nuit tombe ♪"]]
    assert [r.get("sound_only", False) for r in rows] == [False, True, False, False]
    speakers = json.loads((w / "speakers.json").read_text(encoding="utf-8"))
    assert speakers == {"1": {"label": "Sandra"}, "3": {"label": "Daniel"}}
    # The timing file keeps every cue's time; the text loses the tags.
    timing, _ = srt.parse(w / "timing.srt")
    assert [c.ts for c in timing] == [c.ts for c in srt.parse(films / "fr.srt")[0]]
    assert timing[0].lines == ["Viens."]
    prepare.chunks(w, target=250)
    chunk = (w / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    assert "#2 " not in chunk and "Door" not in chunk and "#3 00:00:07 [Daniel]" in chunk


def test_build_keeps_everything_when_asked(films: Path):
    w = films / "work"
    out = prepare.build(w, films / "fr.srt", None, None, hi="keep")
    assert out["sound_only_cues_dropped"] == 0 and out["cues_with_tags_or_labels_removed"] == 0
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert rows[0]["source"] == ["[Door slams]", "SANDRA: Viens."] and not rows[1].get("sound_only")


def test_build_refuses_an_unknown_mode(films: Path):
    with pytest.raises(SystemExit, match="remove, keep"):
        prepare.build(films / "work", films / "fr.srt", None, None, hi="drop")


GOOD = "1\nGel.\n\n3\nOrada mısın?\n\n4\n♪ Gece çöküyor ♪\n"


def test_check_delivers_without_the_sound_only_cue_and_maps_the_numbers(films: Path):
    w = built(films)
    (w / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["sound_only_cues"] == 1 and r["delivered_cues"] == 3
    draft, _ = srt.parse(w / "draft.tr.srt")
    assert [c.n for c in draft] == [1, 2, 3] and draft[1].ts.startswith("00:00:07,000")
    cue_map = json.loads((w / "cue_map.json").read_text(encoding="utf-8"))
    assert cue_map == {"cues": {"1": {"cue": 1}, "2": {"cue": 3}, "3": {"cue": 4}}, "sound_only": [2]}
    assert assemble.where(w, [2, 3]) == [
        {"cue": 2, "delivered": [], "note": "sound only: not in the delivered file"},
        {"cue": 3, "delivered": [2], "at": ["00:00:07,000"]},
    ]
    rows = assemble.sidebyside(w).read_text(encoding="utf-8").splitlines()
    assert [ln.split("\t")[0] for ln in rows[1:]] == ["1", "3", "4"]


def test_check_hard_fails_a_label_or_description_put_back(films: Path):
    w = built(films)
    bad = "1\nSANDRA: Gel.\n\n3\n[Daniel] Orada mısın?\n\n4\n[Kapı çarpar]\n"
    (w / "out" / "tr_01.txt").write_text(bad, encoding="utf-8")
    hard = {(x["cue"], x["check"]) for x in assemble.run_checks(w)["hard"]}
    assert {(1, "speaker label"), (3, "speaker label"), (4, "sound description")} <= hard
    (w / "out" / "tr_01.txt").write_text("1\nGel.\n\n3\nEvet (iç çeker).\n\n4\nOrada mısın?\n", encoding="utf-8")
    hard = {(x["cue"], x["check"]) for x in assemble.run_checks(w)["hard"]}
    assert hard == {(3, "sound description")}


def test_check_reads_capitals_and_parentheses_as_text_where_the_source_had_no_tags(films: Path):
    # Cue 4's source ("♪ La nuit tombe ♪") had nothing removed, so a
    # heading or a parenthesis in its Turkish is text; square brackets
    # never are.
    w = built(films)
    for text in ("BÖLÜM 1: Gece", "Evet (iç çeker).", "(Orada mısın?)", "SANDRA: Gel."):
        (w / "out" / "tr_01.txt").write_text(f"1\nGel.\n\n3\nOrada mısın?\n\n4\n{text}\n", encoding="utf-8")
        assert assemble.run_checks(w)["hard"] == [], text
    (w / "out" / "tr_01.txt").write_text("1\nGel.\n\n3\nOrada mısın?\n\n4\nEvet [iç çeker].\n", encoding="utf-8")
    assert [(x["cue"], x["check"]) for x in assemble.run_checks(w)["hard"]] == [(4, "sound description")]
    (w / "out" / "tr_01.txt").write_text("1\nGel.\n\n3\nOrada mısın?\n\n4\n[Daniel] Gel.\n", encoding="utf-8")
    assert [(x["cue"], x["check"]) for x in assemble.run_checks(w)["hard"]] == [(4, "speaker label")]
    (w / "out" / "tr_01.txt").write_text("1\nGel.\n\n3\nOrada mısın?\n\n4\n(iç çeker)\n", encoding="utf-8")
    assert assemble.run_checks(w)["hard"] == []


def _srt(texts: list[str]) -> str:
    return "\n".join(
        f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},800\n{t}\n" for i, t in enumerate(texts, 1)
    )


EXAMPLES = [
    "(Are you there?)",
    "I said (and I mean it) no.",
    "DAY 3: we leave.",
    "WARNING: HIGH VOLTAGE",
    "OK: let's go.",
    "AT 10: meet me",
    "SANDRA: Come.",
    "[Guard 2] Stop.",
    "(sighs)",
    "[Door slams]",
]


@pytest.mark.parametrize("flagged", [True, False])
def test_build_cleans_each_file_by_its_own_flag(tmp_path: Path, flagged: bool):
    # Flagged: every filler cue has a tag. Plain: 4 tagged cues of 160
    # (SANDRA:, [Guard 2], (sighs) and [Door slams]), under 3%.
    filler = [f"[laughs] Line {i}." if flagged else f"Line {i}." for i in range(150)]
    (tmp_path / "en.srt").write_text(_srt(EXAMPLES + filler), encoding="utf-8")
    w = tmp_path / "work"
    out = prepare.build(w, tmp_path / "en.srt", None, None)
    assert out["hearing_impaired"] == {"timing": flagged}
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))[: len(EXAMPLES)]
    speech = [
        ["(Are you there?)"],
        ["I said (and I mean it) no."],
        ["DAY 3: we leave."],
        ["WARNING: HIGH VOLTAGE"],
        ["OK: let's go."],
        ["AT 10: meet me"],
    ]
    if flagged:
        rest = [["Come."], ["Stop."], [], []]
    else:
        rest = [["SANDRA: Come."], ["Stop."], ["(sighs)"], []]
    assert [r["source"] for r in rows] == speech + rest
    assert [n for n, r in enumerate(rows, 1) if r.get("sound_only")] == ([9, 10] if flagged else [10])
    assert [n for n, r in enumerate(rows, 1) if r.get("tags_removed")] == ([7, 8, 9, 10] if flagged else [8, 10])
    speakers = json.loads((w / "speakers.json").read_text(encoding="utf-8"))
    assert {n: s["label"] for n, s in speakers.items()} == {"7": "Sandra", "8": "Guard 2"}


def test_check_warns_on_text_for_a_sound_only_cue(films: Path):
    w = built(films)
    (w / "out" / "tr_01.txt").write_text(GOOD + "\n2\nGök gürlüyor.\n", encoding="utf-8")
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0 and [(x["cue"], x["check"]) for x in r["warnings"]] == [(2, "sound-only cue")]
    assert "Gök" not in (w / "draft.tr.srt").read_text(encoding="utf-8")


def test_keep_mode_leaves_labels_alone(films: Path):
    w = built(films, hi="keep")
    tr = "1\n[Kapı çarpar]\nSANDRA: Gel.\n\n2\n[Gök gürlüyor]\n\n3\n[Daniel] Orada mısın?\n\n4\n♪ Gece çöküyor ♪\n"
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["delivered_cues"] == 4
