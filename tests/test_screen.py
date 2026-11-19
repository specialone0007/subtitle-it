"""The closing credit on the cut to black after the story: `screen.py ends`
finds the black stretches, `assemble.py deliver` places the goodbye on one.
ffmpeg is faked here; tests/test_ffmpeg.py runs the real one."""

import json
import subprocess
from pathlib import Path

import assemble
import screen
import srt

BYE = [assemble.CREDIT_BYE, "specialone0007"]


def _cues(*spans: tuple[int, int]) -> list[srt.Cue]:
    return [
        srt.Cue(n=i, start=a, end=b, ts=f"{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}", lines=[f"Satır {i}."])
        for i, (a, b) in enumerate(spans, 1)
    ]


def _bye(cues: list[srt.Cue], black, on_screen=frozenset({3}), video_end=None) -> tuple[int, int]:
    shown, _, credits = assemble.with_credit(cues, "specialone0007", video_end, set(on_screen), black)
    bye = shown[credits[-1] - 1]
    assert bye.lines == BYE
    return bye.start, bye.end


# Story ends at 62.5 s; cue 3 is an end title from another track at 80 s.
STORY = ((10_000, 12_000), (60_000, 62_500))
TITLE = (80_000, 83_000)
AFTER_THE_STORY = (65_500, 69_500)


def test_goodbye_starts_on_the_cut_to_black():
    assert _bye(_cues(*STORY, TITLE), [(64_000, 67_000)]) == (64_000, 68_000)
    # Without black stretches the rule after the story places it.
    assert _bye(_cues(*STORY, TITLE), None) == AFTER_THE_STORY
    assert _bye(_cues(*STORY, TITLE), []) == AFTER_THE_STORY


def test_goodbye_on_black_waits_half_a_second_after_the_last_line():
    assert _bye(_cues(*STORY, TITLE), [(62_500, 66_000)]) == (63_000, 67_000)


def test_goodbye_on_black_waits_for_a_cue_still_on_screen():
    # A card from 63.5 s to 65 s is on screen when the black begins.
    cues = _cues(*STORY, (63_500, 65_000), TITLE)
    assert _bye(cues, [(64_000, 67_000)], on_screen={3, 4}) == (65_000, 69_000)


def test_goodbye_on_black_ends_before_the_next_cue():
    cues = _cues(*STORY, (66_500, 70_000), TITLE)
    assert _bye(cues, [(64_000, 67_000)], on_screen={3, 4}) == (64_000, 66_400)


def test_goodbye_with_under_two_seconds_on_black_follows_the_story():
    # The black leaves 1.4 s before the card at 66 s: the old rule places it,
    # after the card, as with no black at all.
    cues = _cues(*STORY, (66_000, 70_000))
    assert _bye(cues, [(64_500, 67_000)]) == _bye(cues, None) == (73_000, 77_000)


def test_goodbye_takes_the_first_black_after_the_story():
    cues = _cues(*STORY)
    assert _bye(cues, [(92_500, 95_000)], on_screen=()) == (92_500, 96_500)
    # Black before story end does not count; the first one after it does.
    assert _bye(cues, [(50_000, 70_000), (70_000, 73_000), (75_000, 78_000)], on_screen=()) == (70_000, 74_000)


def test_goodbye_on_black_stays_inside_the_video():
    assert _bye(_cues(*STORY), [(64_000, 67_000)], on_screen=(), video_end=66_000) == (63_000, 66_000)


def _work(tmp_path: Path, rows=None, black=None, story_end=62_500) -> Path:
    w = tmp_path / "work"
    w.mkdir(parents=True)
    (w / "draft.tr.srt").write_text(srt.render(_cues(*STORY, TITLE)), encoding="utf-8")
    rows = rows or [{"n": 1}, {"n": 2}, {"n": 3, "on_screen": {"fr": ["FIN"], "es": ["FIN"]}}]
    (w / "cues.json").write_text(json.dumps(rows), encoding="utf-8")
    (w / assemble.MAP_FILE).write_text(json.dumps({"cues": {str(k): {"cue": k} for k in (1, 2, 3)}}), encoding="utf-8")
    if black is not None:
        (w / "screen").mkdir()
        data = {"story_end_ms": story_end, "from_ms": story_end, "to_ms": story_end + 150_000, "black": black}
        (w / assemble.ENDS_FILE).write_text(json.dumps(data), encoding="utf-8")
    return w


def test_black_after_story_reads_only_a_file_for_this_story_end(tmp_path: Path):
    assert assemble.black_after_story(_work(tmp_path), 62_500) is None
    w = _work(tmp_path / "a", black=[[64_000, 67_000]])
    assert assemble.black_after_story(w, 62_500) == [(64_000, 67_000)]
    # A later check held the last line up to half a second longer, or
    # shorter: still read. A draft that ends elsewhere, or no story: not read.
    assert assemble.black_after_story(w, 62_000) == assemble.black_after_story(w, 70_000) == [(64_000, 67_000)]
    assert assemble.black_after_story(w, 61_999) is None
    assert assemble.black_after_story(w, 182_501) is None
    assert assemble.black_after_story(w, None) is None
    ok = '"from_ms": 62500, "to_ms": 212500'
    for bad in ("not json", "[]", "{" + ok + "}", "{" + ok + ', "black": [[1]]}', "{" + ok + ', "black": 3}'):
        (w / assemble.ENDS_FILE).write_text(bad, encoding="utf-8")
        assert assemble.black_after_story(w, 62_500) is None


def _readings(w: Path, *cards: tuple[int, str]) -> None:
    data = {"readings": [{"text": "X", "kind": kind, "wants_read": False, "first_ms": ms, "last_ms": ms} for ms, kind in cards]}
    (w / assemble.READINGS_FILE).write_text(json.dumps(data), encoding="utf-8")


def test_black_counts_within_30_s_or_with_the_films_end_right_after(tmp_path: Path):
    # Story ends at 62.5 s. Black at 92.5 s counts; at 161.5 s (99 s later,
    # after an epilogue with no lines) only with a title card or the
    # credits first read within 12 s of its start.
    w = _work(tmp_path, black=[[92_500, 95_000], [161_500, 165_000]])
    assert assemble.black_after_story(w, 62_500) == [(92_500, 95_000)]
    w = _work(tmp_path / "late", black=[[92_501, 95_000], [161_500, 165_000]])
    assert assemble.black_after_story(w, 62_500) == []
    _readings(w, (162_700, "title card"))
    assert assemble.black_after_story(w, 62_500) == [(161_500, 165_000)]
    for ms, kind in ((173_501, "title card"), (161_000, "credits"), (163_000, "sign"), (163_000, "logo")):
        _readings(w, (ms, kind))
        assert assemble.black_after_story(w, 62_500) == [], (ms, kind)
    for kind in ("credits", "closing text"):
        _readings(w, (173_500, kind))
        assert assemble.black_after_story(w, 62_500) == [(161_500, 165_000)]
    (w / assemble.READINGS_FILE).write_text("not json", encoding="utf-8")
    assert assemble.black_after_story(w, 62_500) == []


def test_deliver_lands_the_goodbye_on_a_late_cut_to_black_only_with_the_end_card(tmp_path: Path):
    cues = _cues(*STORY)
    w = _work(tmp_path, black=[[161_500, 165_000]])
    assert _bye(cues, assemble.black_after_story(w, 62_500), on_screen=()) == AFTER_THE_STORY
    _readings(w, (162_700, "title card"))
    assert _bye(cues, assemble.black_after_story(w, 62_500), on_screen=()) == (161_500, 165_500)
    # A last line half a second later still reads the same file.
    assert assemble.black_after_story(w, 63_000) == [(161_500, 165_000)]


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
    assert assemble.black_after_story(w, 62_500) == [(74_846, 77_557)]


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


def test_goodbye_on_black_goes_after_a_title_card_on_the_black():
    # The title is read on the black 1.2 s in and becomes a cue of its own:
    # the goodbye follows it while the black lasts.
    cues = _cues(*STORY, (162_700, 166_000))
    assert _bye(cues, [(161_500, 175_000)]) == (166_000, 170_000)
    # Once the black is over, the rule after the story places it.
    assert _bye(cues, [(161_500, 165_000)]) == AFTER_THE_STORY


def test_end_cards_ignore_readings_of_the_wrong_shape(tmp_path: Path):
    w = _work(tmp_path, black=[[161_500, 165_000]])
    for bad in ('{"readings": [1, 2]}', '{"readings": 3}', "[]"):
        (w / assemble.READINGS_FILE).write_text(bad, encoding="utf-8")
        assert assemble.end_cards(w) == []
