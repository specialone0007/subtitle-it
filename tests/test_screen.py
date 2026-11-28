"""The closing credit at the film's end: `screen.py ends` finds the black
stretches, `screen.py collect` the end cards, and `assemble.py deliver`
places the goodbye after every translated line, on the cut to black that
leads into the end cards or on the first of them. ffmpeg is faked here;
tests/test_ffmpeg.py runs the real one."""

import json
import subprocess
from pathlib import Path

import pytest

import assemble
import prepare
import screen
import srt

BYE = [assemble.CREDIT_BYE, "specialone0007"]
Ends = assemble.Ends


def _cues(*spans: tuple[int, int]) -> list[srt.Cue]:
    return [
        srt.Cue(n=i, start=a, end=b, ts=f"{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}", lines=[f"Satır {i}."])
        for i, (a, b) in enumerate(spans, 1)
    ]


def _cards(*cards: tuple[int, int, str]) -> tuple[assemble.EndCard, ...]:
    return tuple(assemble.EndCard(a, b, prepare.fold_text(t)) for a, b, t in cards)


def _bye(cues: list[srt.Cue], ends: assemble.Ends | None = None, video_end=None) -> tuple[int, int, str]:
    shown, _, credits, how = assemble.with_credit(cues, "specialone0007", video_end, ends)
    bye = shown[credits[-1] - 1]
    assert bye.lines == BYE and credits[-1] == len(shown)
    return bye.start, bye.end, how


ON_BLACK, ON_CARD, AFTER = assemble.GOODBYE_ON_BLACK, assemble.GOODBYE_ON_CARD, assemble.GOODBYE_AFTER_LINE
# The last line ends at 62.5 s.
STORY = ((10_000, 12_000), (60_000, 62_500))
CREDITS = _cards((70_000, 71_500, "DIRECTED BY X"), (73_000, 74_500, "WRITTEN BY Y"))


def test_a_real_run_lands_on_the_cut_to_black_before_the_credits():
    # Times from one test film, all moved by the same amount: the last spoken
    # line ends at 01:31:05.958, a sign in the picture is a cue until
    # 01:31:22.458, the cut to black runs 01:32:29.5 to 01:32:38.25 and the
    # credits start 0.7 s after it, a new card every 4.5 s.
    cues = _cues((5_463_000, 5_465_958), (5_479_458, 5_482_458))
    cards = _cards(
        (5_558_958, 5_561_958, "DIRECTED BY / X"),
        (5_563_458, 5_564_958, "SCREENPLAY BY / Y"),
        (5_567_958, 5_569_458, "BASED ON THE BOOK BY / Z"),
    )
    ends = Ends(((5_549_500, 5_558_250),), cards, 5_614_458)
    assert _bye(cues, ends) == (5_549_500, 5_553_500, ON_BLACK)
    # Without the picture the goodbye still never comes before the sign.
    assert _bye(cues) == (5_485_458, 5_489_458, AFTER)


def test_a_fade_inside_the_last_scene_is_not_used():
    # Black with no end card after it: a fade between two silent shots.
    assert _bye(_cues(*STORY), Ends(((64_000, 67_000),))) == (65_500, 69_500, AFTER)
    # Black, 4 s of picture, then credits over the picture: the black ends
    # more than 3 s before the credits, so the goodbye goes on the first card.
    assert _bye(_cues(*STORY), Ends(((64_000, 66_000),), CREDITS)) == (70_000, 74_000, ON_CARD)
    # Black that ends 3 s before the credits still leads into them.
    assert _bye(_cues(*STORY), Ends(((64_000, 67_000),), _cards((70_000, 71_500, "A"), (72_000, 73_000, "B")))) == (
        64_000,
        68_000,
        ON_BLACK,
    )


def test_credits_over_the_picture_with_no_black():
    assert _bye(_cues(*STORY), Ends((), CREDITS)) == (70_000, 74_000, ON_CARD)


def test_the_earliest_black_that_leads_into_the_end_cards():
    ends = Ends(((64_000, 67_500), (68_000, 72_000)), CREDITS)
    assert _bye(_cues(*STORY), ends) == (64_000, 68_000, ON_BLACK)
    # Credits that start inside a black blackdetect reads as running past them.
    assert _bye(_cues(*STORY), Ends(((64_000, 80_000),), CREDITS)) == (64_000, 68_000, ON_BLACK)


def test_an_end_title_on_the_black_is_followed_by_the_goodbye():
    # The black starts at 63 s; a translated title is shown on it until 67 s.
    # The black is still running half a second later, so the goodbye goes
    # there.
    cues = _cues(*STORY, (64_000, 67_000))
    ends = Ends(((63_000, 75_000),), _cards((72_000, 73_500, "DIRECTED BY X"), (75_000, 76_500, "WRITTEN BY Y")))
    assert _bye(cues, ends) == (67_500, 71_500, ON_BLACK)
    # A black that is over by then does not count.
    ends = Ends(((63_000, 67_400),), _cards((69_000, 70_500, "DIRECTED BY X"), (72_000, 73_500, "WRITTEN BY Y")))
    assert _bye(cues, ends) == (69_000, 73_000, ON_CARD)


def test_a_title_card_or_logo_starts_the_end():
    cards = _cards((68_000, 69_500, "A FILM BY X"), *CREDITS)
    assert _bye(_cues(*STORY), Ends((), cards)) == (68_000, 72_000, ON_CARD)
    assert _bye(_cues(*STORY), Ends(((67_000, 69_000),), cards)) == (67_000, 71_000, ON_BLACK)


def test_a_stray_card_or_one_card_read_twice_does_not_start_the_end():
    # A logo on a mug at 66 s, alone, and the same logo read again 3 s later.
    stray = _cards((66_000, 66_000, "ACME"), (69_000, 69_000, "acme"))
    late = _cards((90_000, 91_500, "DIRECTED BY X"), (93_000, 94_500, "WRITTEN BY Y"))
    assert _bye(_cues(*STORY), Ends((), stray + late)) == (90_000, 94_000, ON_CARD)
    assert _bye(_cues(*STORY), Ends((), stray)) == (65_500, 69_500, AFTER)
    # More than 10 s from one card's last frame to the next: not the end yet.
    far = _cards((66_000, 67_000, "A"), (77_001, 78_000, "B"))
    assert _bye(_cues(*STORY), Ends((), far)) == (65_500, 69_500, AFTER)


def test_one_card_held_to_the_end_of_the_tail_counts():
    held = _cards((70_000, 90_000, "THE END"))
    assert _bye(_cues(*STORY), Ends((), held, 90_000)) == (70_000, 74_000, ON_CARD)
    assert _bye(_cues(*STORY), Ends((), held, 91_500)) == (65_500, 69_500, AFTER)


def test_a_song_over_the_credits_comes_before_the_goodbye():
    # Lyrics translated over the first credits: a card under them is not an
    # end card; the goodbye goes on the first card after the last lyric.
    cues = _cues(*STORY, (64_000, 67_000), (68_000, 71_000))
    cards = _cards((65_000, 66_500, "DIRECTED BY X"), (72_000, 73_500, "WRITTEN BY Y"), (75_000, 76_500, "MUSIC BY Z"))
    assert _bye(cues, Ends((), cards)) == (72_000, 76_000, ON_CARD)
    # A card that starts right after the last lyric: half a second after it.
    cards = _cards((71_200, 72_500, "WRITTEN BY Y"), (75_000, 76_500, "MUSIC BY Z"))
    assert _bye(cues, Ends((), cards)) == (71_500, 75_500, ON_CARD)


def test_an_after_credits_scene_comes_before_the_goodbye():
    cues = _cues(*STORY, (200_000, 202_000))
    assert _bye(cues, Ends(((64_000, 69_000),), CREDITS)) == (205_000, 209_000, AFTER)


def test_a_cue_timed_backwards_stays_before_the_goodbye():
    # Cue 3 is timed 65 s to 63 s, a typo in the timing file.
    cues = _cues(*STORY, (65_000, 63_000))
    assert _bye(cues) == (68_000, 72_000, AFTER)
    assert _bye(cues, video_end=70_000) == (66_000, 70_000, AFTER)


@pytest.mark.parametrize("shift", [-5_000, 0, 7_250])
def test_the_goodbye_moves_with_the_film(shift: int):
    # Subtitles shifted onto the video's clock: the picture's times are the
    # video's, so everything moves together and no clock is converted.
    cues = _cues(*((a + shift, b + shift) for a, b in STORY))
    cards = tuple(c._replace(first_ms=c.first_ms + shift, last_ms=c.last_ms + shift) for c in CREDITS)
    ends = Ends(((68_000 + shift, 71_000 + shift),), cards, 90_000 + shift)
    assert _bye(cues, ends) == (68_000 + shift, 72_000 + shift, ON_BLACK)


def _work(tmp_path: Path, rows=None, black=None, story_end=62_500) -> Path:
    w = tmp_path / "work"
    w.mkdir(parents=True)
    (w / "draft.tr.srt").write_text(srt.render(_cues(*STORY, (80_000, 83_000))), encoding="utf-8")
    rows = rows or [{"n": 1}, {"n": 2}, {"n": 3, "on_screen": {"fr": ["FIN"], "es": ["FIN"]}}]
    (w / "cues.json").write_text(json.dumps(rows), encoding="utf-8")
    (w / assemble.MAP_FILE).write_text(json.dumps({"cues": {str(k): {"cue": k} for k in (1, 2, 3)}}), encoding="utf-8")
    (w / "screen").mkdir()
    if black is not None:
        data = {"story_end_ms": story_end, "from_ms": story_end, "to_ms": story_end + 150_000, "black": black}
        (w / assemble.ENDS_FILE).write_text(json.dumps(data), encoding="utf-8")
    return w


def _readings(w: Path, *cards: tuple[int, int, str, str]) -> None:
    data = {"readings": [{"text": t, "kind": kind, "wants_read": False, "first_ms": a, "last_ms": b} for a, b, t, kind in cards]}
    (w / assemble.READINGS_FILE).write_text(json.dumps(data), encoding="utf-8")


def test_black_stretches_reads_only_a_file_for_this_story_end(tmp_path: Path):
    assert assemble.black_stretches(_work(tmp_path), 62_500) == []
    w = _work(tmp_path / "a", black=[[64_000, 67_000], [161_500, 165_000]])
    assert assemble.black_stretches(w, 62_500) == [(64_000, 67_000), (161_500, 165_000)]
    # A later check held the last line up to half a second longer, or
    # shorter: still read. A draft that ends elsewhere, or no story: not read.
    assert assemble.black_stretches(w, 62_000) == assemble.black_stretches(w, 70_000) != []
    assert assemble.black_stretches(w, 61_999) == []
    assert assemble.black_stretches(w, 182_501) == []
    assert assemble.black_stretches(w, None) == []
    ok = '"from_ms": 62500, "to_ms": 212500'
    for bad in ("not json", "[]", "{" + ok + "}", "{" + ok + ', "black": [[1]]}', "{" + ok + ', "black": 3}'):
        (w / assemble.ENDS_FILE).write_text(bad, encoding="utf-8")
        assert assemble.black_stretches(w, 62_500) == []


def test_end_cards_are_the_credits_title_cards_closing_texts_and_logos(tmp_path: Path):
    w = _work(tmp_path)
    assert assemble.end_cards(w) == []
    kinds = ("credits", "title card", "closing text", "logo", "sign", "caption", "background")
    _readings(w, *((70_000 + k, 70_500 + k, f"Card {k}!", kind) for k, kind in enumerate(kinds)))
    assert assemble.end_cards(w) == [assemble.EndCard(70_000 + k, 70_500 + k, f"card {k}") for k in range(4)]
    for bad in ('{"readings": [1, 2]}', '{"readings": 3}', "[]", "not json"):
        (w / assemble.READINGS_FILE).write_text(bad, encoding="utf-8")
        assert assemble.end_cards(w) == []


def _tail(w: Path, tail: tuple[int, int]) -> None:
    """frames.json with the tail span `screen.py frames` wrote and a frame
    every 1.5 s across it."""
    frames = [{"ms": 1_000, "why": "head"}] + [{"ms": t, "why": "tail"} for t in range(tail[0], tail[1], 1_500)]
    (w / prepare.FRAMES_FILE).write_text(
        json.dumps({"tail": list(tail), "frames": frames + [{"ms": 90_000, "why": "x"}]}), encoding="utf-8"
    )


def test_tail_end_is_the_last_tail_frame_when_the_tail_ended_with_the_video(tmp_path: Path):
    w = _work(tmp_path)
    assert assemble.tail_end(w) is None
    # The video ends 3 s after story end, so the tail is cut short.
    _tail(w, (62_500, 65_500))
    assert assemble.tail_end(w) == 64_000
    # A full tail stops inside the film: its last frame proves nothing.
    _tail(w, (62_500, 62_500 + assemble.TAIL_WINDOW_MS))
    assert assemble.tail_end(w) is None
    for bad in ('{"frames": [1], "tail": [0, 1]}', '{"frames": 3, "tail": [0, 1]}', '{"frames": []}', "[]", "not json"):
        (w / prepare.FRAMES_FILE).write_text(bad, encoding="utf-8")
        assert assemble.tail_end(w) is None


def test_the_full_tail_matches_the_frames_window():
    assert assemble.TAIL_WINDOW_MS == screen.WINDOW_MS


def test_a_lone_card_held_to_a_full_tail_does_not_start_the_end(tmp_path: Path):
    # A silent last scene runs past the 2.5-minute tail, and one misread card
    # is still up in the tail's last frame: the end has not started.
    w = _work(tmp_path)
    _tail(w, (62_500, 62_500 + assemble.TAIL_WINDOW_MS))
    _readings(w, (200_500, 211_000, "ACME", "logo"))
    assert _bye(_cues(*STORY), assemble.read_ends(w, 62_500)) == (65_500, 69_500, AFTER)
    # The same card when the video ends with the tail: the film's last card.
    _tail(w, (62_500, 212_000))
    assert _bye(_cues(*STORY), assemble.read_ends(w, 62_500)) == (200_500, 204_500, ON_CARD)


def test_read_ends_with_only_cards_or_only_black(tmp_path: Path):
    # Readings but no ends.json: the goodbye goes on the first end card.
    w = _work(tmp_path)
    _readings(w, (70_000, 71_500, "DIRECTED BY X", "credits"), (73_000, 74_500, "WRITTEN BY Y", "credits"))
    assert _bye(_cues(*STORY), assemble.read_ends(w, 62_500)) == (70_000, 74_000, ON_CARD)
    # ends.json but no readings (the frames were not read): 3 s after the
    # last line, whatever the black.
    w = _work(tmp_path / "b", black=[[64_000, 67_000]])
    assert _bye(_cues(*STORY), assemble.read_ends(w, 62_500)) == (65_500, 69_500, AFTER)
    # Both: the cut to black.
    _readings(w, (68_000, 69_500, "DIRECTED BY X", "credits"), (71_000, 72_500, "WRITTEN BY Y", "credits"))
    assert _bye(_cues(*STORY), assemble.read_ends(w, 62_500)) == (64_000, 68_000, ON_BLACK)


def _ffmpeg(monkeypatch, stderr: str = "", code: int = 0) -> list[list[str]]:
    ran = []

    def run(cmd, **kw):
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, code, "", stderr)

    monkeypatch.setattr(screen.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(screen.subprocess, "run", run)
    return ran


LOG = (
    "[blackdetect @ 0x1] black_start:1.5 black_end:2.5 black_duration:1\n"
    "[blackdetect @ 0x1] black_start:12.346 black_end:15.057 black_duration:2.711\n"
)


def test_ends_writes_the_black_stretches_on_the_video_clock(tmp_path: Path, monkeypatch):
    w = _work(tmp_path)
    ran = _ffmpeg(monkeypatch, LOG)
    out = screen.ends(w, tmp_path / "Film.mkv")
    # Seek to story end (62.5 s, the end title left out), 150 s window; the
    # 1 s stretch is dropped, the other moved by the seek.
    cmd = ran[-1]
    assert cmd[cmd.index("-ss") + 1] == "62.500" and cmd[cmd.index("-t") + 1] == "150"
    assert screen.BLACK_FILTER in cmd and len(ran) == 1
    data = json.loads((w / assemble.ENDS_FILE).read_text(encoding="utf-8"))
    assert out["ends"] == str(w / assemble.ENDS_FILE) and data["black"] == [[74_846, 77_557]]
    assert data["story_end_ms"] == 62_500 and data["to_ms"] == 212_500
    assert assemble.black_stretches(w, 62_500) == [(74_846, 77_557)]


def test_ends_adds_only_the_seek_for_a_transport_stream(tmp_path: Path, monkeypatch):
    # ffmpeg already counts from the stream's start_time, as the extracted
    # tracks do: no ffprobe call, and the same times as for an .mkv.
    w = _work(tmp_path)
    ran = _ffmpeg(monkeypatch, LOG)
    screen.ends(w, tmp_path / "Film.m2ts")
    assert len(ran) == 1 and json.loads((w / assemble.ENDS_FILE).read_text(encoding="utf-8"))["black"] == [[74_846, 77_557]]


def test_ends_never_fails_a_run(tmp_path: Path, monkeypatch):
    w = _work(tmp_path, black=[[64_000, 67_000]])
    # A failing ffmpeg: an error, and the earlier file is gone.
    _ffmpeg(monkeypatch, "Invalid data found when processing input\n", code=1)
    out = screen.ends(w, tmp_path / "Film.mkv")
    assert out["ends"] is None and "exit 1" in out["error"] and "Invalid data" in out["error"]
    assert not (w / assemble.ENDS_FILE).exists()
    # No ffmpeg on PATH.
    monkeypatch.setattr(screen.shutil, "which", lambda name: None)
    assert screen.ends(w, tmp_path / "Film.mkv") == {"ends": None, "error": "ffmpeg not found on PATH"}

    # ffmpeg that cannot start, or runs too long.
    def broken(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(screen.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(screen.subprocess, "run", broken)
    assert screen.ends(w, tmp_path / "Film.mkv")["error"] == "ffmpeg failed: TimeoutExpired"
    # No draft, or no story cue in it.
    (w / "draft.tr.srt").unlink()
    assert "no draft" in screen.ends(w, tmp_path / "Film.mkv")["error"]
    w2 = _work(tmp_path / "b", rows=[{"n": k, "on_screen": {"fr": ["X"], "es": ["X"]}} for k in (1, 2, 3)])
    assert "no cue" in screen.ends(w2, tmp_path / "Film.mkv")["error"]


def test_screen_cli_writes_the_result(tmp_path: Path, monkeypatch):
    w = _work(tmp_path)
    _ffmpeg(monkeypatch, LOG)
    res = tmp_path / "res.json"
    screen.main(["--result", str(res), "ends", "--work", str(w), "--video", str(tmp_path / "Film.mkv")])
    assert json.loads(res.read_text(encoding="utf-8"))["black"] == [[74_846, 77_557]]
