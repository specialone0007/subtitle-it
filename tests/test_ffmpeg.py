"""The real ffmpeg and ffprobe, on whatever system runs the tests.

The other tests replace both tools with fakes. These build a short video with
a text subtitle track and read it back the way a run does, so CI shows that
the tools behave the same on Linux, macOS and Windows. Skipped when ffmpeg is
not installed, except in CI, which installs it on every system.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import prepare
import screen
import sources
import srt

pytestmark = pytest.mark.skipif(
    not os.environ.get("CI") and (shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None),
    reason="ffmpeg and ffprobe are not installed",
)

SRT = """1
00:00:00,500 --> 00:00:01,500
Good morning.

2
00:00:02,000 --> 00:00:03,200
<i>The train is late again.</i>

3
00:00:03,600 --> 00:00:04,800
- Coming?
- In a minute.
"""


def make_video(folder: Path) -> Path:
    """The audio is plain PCM. With AAC, ffmpeg 6 on Ubuntu moved every cue
    23 ms later (the encoder's start-up delay) while newer versions did not,
    and this test is about the scripts, not that difference."""
    sub = folder / "track.srt"
    sub.write_text(SRT, encoding="utf-8")
    video = folder / "Harbour Lights (2026).mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:d=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-i", str(sub),
            "-map", "0:v", "-map", "1:a", "-map", "2:s",
            "-c:v", "mpeg4", "-c:a", "pcm_s16le", "-c:s", "srt",
            "-metadata:s:s:0", "language=eng",
            str(video),
        ],
        check=True,
    )  # fmt: skip
    sub.unlink()
    return video


def test_local_reads_a_real_text_track(tmp_path: Path):
    films = tmp_path / "films"
    films.mkdir()
    video = make_video(films)

    out = sources.local(video, tmp_path / "work")

    assert 4_500 <= out["duration_ms"] <= 5_500
    [track] = out["candidates"]
    assert track["source"] == "built-in track"
    assert track["language"] == "en"
    assert track["text"] is True
    cues, _ = srt.parse(track["path"])
    assert [c.start for c in cues] == [500, 2000, 3600]
    assert [c.end for c in cues] == [1500, 3200, 4800]
    assert cues[2].lines == ["- Coming?", "- In a minute."]


@pytest.mark.parametrize(
    "name, out",
    [("Film.mkv", ["-c:v", "mpeg4"]), ("Film.ts", ["-c:v", "mpeg2video", "-output_ts_offset", "10", "-f", "mpegts"])],
)
def test_screen_ends_finds_a_real_cut_to_black(tmp_path: Path, name: str, out: list[str]):
    # White to 6 s, black from 6 s to 9 s, white again to 12 s. The story
    # ends at 3 s, so ffmpeg seeks there and the times must be moved back.
    # The .ts starts its own clock at 10 s; its tracks are extracted from
    # 0 s, so the black must be found at 6 s there too.
    video = tmp_path / name
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=25:d=6",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=25:d=3",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
            *out, str(video),
        ],
        check=True,
    )  # fmt: skip
    w = tmp_path / "work"
    w.mkdir()
    (w / "draft.tr.srt").write_text("1\n00:00:00,500 --> 00:00:03,000\nMerhaba.\n", encoding="utf-8")
    (w / "cues.json").write_text("[]", encoding="utf-8")
    found = screen.ends(w, video)
    [(start, end)] = found["black"]
    assert found["story_end_ms"] == 3_000 and abs(start - 6_000) <= 80 and abs(end - 9_000) <= 80


def test_screen_frames_saves_real_frames_fitted_into_960x540(tmp_path: Path):
    # 12 s of 1280x720. One spoken line from 6 s to 7 s: the head is 0-6 s
    # (4 frames, one every 1.5 s) and the tail 7-12 s (4 frames).
    video = tmp_path / "Film.mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=s=1280x720:r=5:d=12",
            "-c:v", "mpeg4", str(video),
        ],
        check=True,
    )  # fmt: skip
    timing = tmp_path / "en.srt"
    timing.write_text("1\n00:00:06,000 --> 00:00:07,000\nGood morning.\n", encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, timing, None, None)
    out = screen.frames(w, video)
    assert "error" not in out, out
    assert (out["frames"], out["head"], out["tail"], out["notes"]) == (8, 4, 4, [])
    listed = json.loads((w / prepare.FRAMES_FILE).read_text(encoding="utf-8"))["frames"]
    assert [f["ms"] for f in listed] == [0, 1_500, 3_000, 4_500, 7_000, 8_500, 10_000, 11_500]
    for f in listed:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", f["path"]],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        assert probe.stdout.strip() == "960,540"


def test_screen_ends_finds_black_with_a_small_title_on_it(tmp_path: Path, monkeypatch):
    # White to 6 s, then black from 6 s to 9 s with a white box of 1.5% of
    # the picture, as a title fading in over the cut to black, then white.
    # pic_th=0.98 lets 2% be lit; the 1.0 it replaced found nothing here.
    video = tmp_path / "Film.mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=25:d=6",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=25:d=3",
            "-filter_complex",
            "[1:v]drawbox=x=70:y=40:w=18:h=12:color=white:t=fill[t];[0:v][t][2:v]concat=n=3:v=1:a=0",
            "-c:v", "mpeg4", "-q:v", "2", str(video),
        ],
        check=True,
    )  # fmt: skip
    w = tmp_path / "work"
    w.mkdir()
    (w / "draft.tr.srt").write_text("1\n00:00:00,500 --> 00:00:03,000\nMerhaba.\n", encoding="utf-8")
    (w / "cues.json").write_text("[]", encoding="utf-8")
    [(start, end)] = screen.ends(w, video)["black"]
    assert abs(start - 6_000) <= 80 and abs(end - 9_000) <= 80
    monkeypatch.setattr(screen, "BLACK_FILTER", "blackdetect=d=2:pic_th=1.0:pix_th=0.10")
    assert screen.ends(w, video)["black"] == []
