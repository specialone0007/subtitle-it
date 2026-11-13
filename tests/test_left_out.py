"""Cues left out of the translation, as the Netflix Turkish style guide
does: bare sounds the audience hears ("Oh.", "Hmm?") and songs that do not
carry the story."""

import json
from pathlib import Path

import pytest

import assemble
import prepare
import srt


@pytest.mark.parametrize(
    ("lines", "bare"),
    [
        (["Oh."], True),
        (["Hmm?"], True),
        (["Uh, um..."], True),
        (["Ohh. Ahh!"], True),
        (["<i>Whoa.</i>"], True),
        (["- Oh.", "- Hmm."], True),
        (["Mm-hmm."], True),
        (["Oh, no."], False),
        (["Huh? What?"], False),
        (["Ouch!"], False),
        (["Yeah."], False),
        (["Ohio."], False),
        (["- Hmm?", "- Grand Junction, do you copy?"], False),
        (["..."], False),
        ([], False),
    ],
)
def test_bare_sound(lines, bare):
    assert srt.is_bare_sound(lines) is bare


@pytest.mark.parametrize(
    ("lines", "answer"),
    [(["Uh-huh."], True), (["Mm-hmm"], True), (["Mhm."], True), (["Nuh-uh!"], True), (["Uh-uh."], True), (["Huh?"], False)],
)
def test_answer_sound(lines, answer):
    assert srt.is_answer_sound(lines) is answer


@pytest.mark.parametrize(
    ("lines", "lyric"),
    [
        (["<i>♪ Lookin' back over my life ♪</i>"], True),
        (["♪ Spent the most of it", "Tongue-tied ♪"], True),
        (["# Old song line #"], True),
        (["♪ ♪"], False),
        (["- ♪ La la ♪", "- Turn it off!"], False),
        (["Turn it off!"], False),
    ],
)
def test_lyric(lines, lyric):
    assert srt.is_lyric(lines) is lyric


FILM = """1
00:00:01,000 --> 00:00:02,000
Come here.

2
00:00:03,000 --> 00:00:04,000
Oh.

3
00:00:05,000 --> 00:00:06,000
Do you trust me?

4
00:00:07,000 --> 00:00:08,000
Uh-huh.

5
00:00:09,000 --> 00:00:10,000
Mm-hmm.

6
00:00:11,000 --> 00:00:12,000
<i>♪ First song ♪</i>

7
00:00:13,000 --> 00:00:14,000
<i>♪ Second song ♪</i>

8
00:00:15,000 --> 00:00:16,000
Goodbye.
"""


@pytest.fixture
def work(tmp_path: Path) -> Path:
    src = tmp_path / "film.en.srt"
    src.write_text(FILM, encoding="utf-8")
    w = tmp_path / "work"
    out = prepare.build(w, src, None, None)
    assert out["song_cues"] == 2 and out["bare_sound_cues_dropped"] == 2
    return w


def rows(w: Path) -> dict[int, dict]:
    return {r["n"]: r for r in json.loads((w / "cues.json").read_text(encoding="utf-8"))}


def test_build_leaves_out_bare_sounds_but_keeps_an_answer_to_a_question(work: Path):
    r = rows(work)
    # "Oh." goes; "Uh-huh." answers "Do you trust me?" and stays; "Mm-hmm."
    # follows no question and goes.
    assert r[2]["left_out"] == "sound" and r[5]["left_out"] == "sound"
    assert "left_out" not in r[4]
    assert r[6]["song"] and r[7]["song"] and "left_out" not in r[6]


def chunk_cues(w: Path) -> list[int]:
    prepare.chunks(w, 250)
    text = (w / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    return [int(line.split()[0][1:]) for line in text.splitlines() if line.startswith("#") and line[1:2].isdigit()]


def test_story_mode_keeps_only_the_songs_the_bible_lists(work: Path):
    (work / "songs.json").write_text(json.dumps({"keep": [{"first": 7, "last": 7, "why": "sung on screen"}]}))
    out = prepare.songs(work, "story")
    assert out == {"mode": "story", "song_cues": 2, "kept": 1, "left_out": 1, "note": None}
    assert chunk_cues(work) == [1, 3, 4, 7, 8]


def test_story_mode_without_a_song_list_leaves_every_song_out(work: Path):
    out = prepare.songs(work, "story")
    assert out["left_out"] == 2 and "no songs.json" in out["note"]


def test_skip_and_all_and_running_again(work: Path):
    assert prepare.songs(work, "skip")["left_out"] == 2
    assert chunk_cues(work) == [1, 3, 4, 8]
    # Running again recomputes: `all` brings the songs back.
    assert prepare.songs(work, "all")["left_out"] == 0
    assert chunk_cues(work) == [1, 3, 4, 6, 7, 8]


@pytest.mark.parametrize(
    "bad",
    ['{"keep": [{"first": 9, "last": 3}]}', '{"keep": "6-7"}', "[]", "not json", '{"keep": [{"first": "6", "last": 7}]}'],
)
def test_a_bad_song_list_is_refused(work: Path, bad: str):
    (work / "songs.json").write_text(bad)
    with pytest.raises(SystemExit, match="songs.json"):
        prepare.songs(work, "story")


def test_check_and_where_leave_out_sounds_and_songs(work: Path):
    prepare.songs(work, "skip")
    (work / "out").mkdir(exist_ok=True)
    tr = "1\nGel buraya.\n\n2\nOh.\n\n3\nBana güveniyor musun?\n\n4\nEvet.\n\n8\nHoşça kal.\n"
    (work / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert (r["sound_only_cues"], r["bare_sounds_left_out"], r["songs_left_out"]) == (0, 2, 2)
    assert r["delivered_cues"] == 4
    # Text written for a left-out cue is rejected with a warning, not delivered.
    assert any(x["cue"] == 2 and x["check"] == "left-out cue" for x in r["warnings"])
    draft, _ = srt.parse(work / "draft.tr.srt")
    assert [c.lines for c in draft] == [["Gel buraya."], ["Bana güveniyor musun?"], ["Evet."], ["Hoşça kal."]]
    assert assemble.where(work, [2, 6, 8]) == [
        {"cue": 2, "delivered": [], "note": "a bare sound, left out: not in the delivered file"},
        {"cue": 6, "delivered": [], "note": "a song left out: not in the delivered file"},
        {"cue": 8, "delivered": [4], "at": ["00:00:15,000"]},
    ]
