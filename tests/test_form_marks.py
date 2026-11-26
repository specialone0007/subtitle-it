"""The checks on a cue's marks agree with the pack: a song is in italics
even where the source shows it plain, and the "- " that carries a
sentence on from a cue ending with " -" is no dialogue dash."""

import json
from pathlib import Path

import pytest

import assemble
import polish
import prepare
import srt

SRC = """1
00:00:01,000 --> 00:00:03,000
I know you well

2
00:00:03,500 --> 00:00:06,000
Plain line.

3
00:00:07,000 --> 00:00:09,000
In 2021, using her documents, -

4
00:00:09,500 --> 00:00:12,000
- the Journal published
the first of 17 articles.

5
00:00:13,000 --> 00:00:15,000
I was-

6
00:00:15,500 --> 00:00:17,000
- Go on.

7
00:00:18,000 --> 00:00:20,000
- Where are you?
- At home.
"""

GOOD = (
    "1\n<i>♪ Seni iyi tanırım ♪</i>\n\n"
    "2\nDüz satır.\n\n"
    "3\n2021'de, onun belgeleriyle...\n\n"
    "4\n...gazete 17 makalenin\nilkini yayımladı.\n\n"
    "5\nBen...\n\n"
    "6\n- Devam et.\n\n"
    "7\n- Neredesin?\n- Evdeyim.\n"
)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "da.srt").write_text(SRC, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "da.srt", None, None)
    # As in The Social Reckoning: the timing file shows the lyric plain,
    # and only the English track marks it with ♪.
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    for r in rows:
        if r["n"] == 1:
            r["en"] = ["♪ I know you well ♪"]
        if r["n"] == 7:
            # A chat on a phone screen, shown as on-screen text.
            r["on_screen"] = {"en": r["source"]}
    (w / "cues.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    prepare.chunks(w, target=250)
    return w


def _hard(w: Path, text: str) -> set[tuple[int, str]]:
    (w / "out" / "tr_01.txt").write_text(text, encoding="utf-8")
    return {(x["cue"], x["check"]) for x in assemble.run_checks(w)["hard"]}


def test_song_and_continuation_marks_pass(work: Path):
    assert _hard(work, GOOD) == set()


def test_song_in_italics_is_no_hard_fail_but_speech_still_is(work: Path):
    hard = _hard(work, GOOD.replace("Düz satır.", "<i>Düz satır.</i>"))
    assert hard == {(2, "italic tags")}
    # A plain song still matches its plain source.
    assert _hard(work, GOOD.replace("<i>♪ Seni iyi tanırım ♪</i>", "♪ Seni iyi tanırım ♪")) == set()


@pytest.mark.parametrize(
    ("row", "song"),
    [
        ({"song": True, "source": ["la la"]}, True),
        ({"source": ["I know you well"], "en": ["♪ I know you well ♪"]}, True),
        ({"timing_lines": ["♫ Hey ♫"], "source": None, "en": None}, True),
        ({"source": ["I know you well"], "en": ["I know you well"]}, False),
    ],
)
def test_song_cue(row: dict, song: bool):
    assert assemble.song_cue(row) is song


def test_continuation_dash_is_not_a_speaker(work: Path):
    # A "- " on the card that carries the sentence on reads as dialogue.
    hard = _hard(work, GOOD.replace("...gazete", "- gazete"))
    assert hard == {(4, "dialogue dashes")}
    # A cut-off word ("I was-") is no continuation: the next cue's dash stays.
    assert _hard(work, GOOD.replace("- Devam et.", "Devam et.")) == {(6, "dialogue dashes")}


def test_on_screen_card_with_two_speakers_keeps_its_dash_check(work: Path):
    # Only the continuation mark is skipped: a chat shown on screen with
    # two speakers still needs both dashes.
    plain = GOOD.replace("- Neredesin?\n- Evdeyim.", "Neredesin?\nEvdeyim.")
    assert _hard(work, plain) == {(7, "dialogue dashes")}


@pytest.mark.parametrize(
    ("prev", "lines", "dashes"),
    [
        (["Frances Haugens dokumenter, -"], ["- publicerede Wall Street Journal", "den første."], 0),
        (["<i>over for parlamentet, -</i>"], ["<i>- og hun medvirkede</i>"], 0),
        (["I was-"], ["- Go on."], 1),
        (["Who's there?"], ["- Me.", "- And me."], 2),
        (["it runs on -"], ["- og så", "- Hvad?"], 1),
        (None, ["- Go on."], 1),
        # An interruption with a space before its hyphen, then a new
        # speaker in a capital: both dashes are speakers.
        (["If you don't -"], ["- I won't.", "- Good."], 2),
        (["If you don't -"], ["- I won't."], 1),
        (["dokumenter, -"], ["- 17 artikler om Facebook."], 0),
    ],
)
def test_dialogue_dashes(prev, lines, dashes):
    assert srt.dialogue_dashes(lines, prev) == dashes


def test_match_form_keeps_song_italics_and_drops_continuation_dash():
    assert polish.match_form(["I know you well"], ["<i>♪ Seni iyi tanırım ♪</i>"], song=True) == (
        ["<i>♪ Seni iyi tanırım ♪</i>"],
        False,
    )
    assert polish.match_form(["Plain."], ["<i>Düz.</i>"]) == (["Düz."], True)
    src = ["- publicerede Wall Street Journal", "den første af 17 artikler."]
    out = polish.match_form(src, ["- gazete 17 makalenin", "ilkini yayımladı."], prev=["dokumenter, -"])
    assert out == (["gazete 17 makalenin", "ilkini yayımladı."], True)


def test_seed_keeps_song_italics_and_drops_a_continuation_dash(work: Path, tmp_path: Path):
    tr = tmp_path / "tr.srt"
    tr.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n<i>♪ Seni iyi tanırım ♪</i>\n\n"
        "2\n00:00:03,500 --> 00:00:06,000\n<i>Düz satır.</i>\n\n"
        "3\n00:00:07,000 --> 00:00:09,000\n2021'de, onun belgeleriyle...\n\n"
        "4\n00:00:09,500 --> 00:00:12,000\n- gazete 17 makalenin\nilkini yayımladı.\n",
        encoding="utf-8",
    )
    polish.seed(work, tr)
    texts, _ = assemble.load_translation(work)
    assert texts[1] == ["<i>♪ Seni iyi tanırım ♪</i>"]
    assert texts[2] == ["Düz satır."]
    assert texts[4] == ["gazete 17 makalenin", "ilkini yayımladı."]
