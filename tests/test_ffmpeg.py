"""The real ffmpeg and ffprobe, on whatever system runs the tests.

The other tests replace both tools with fakes. These build a short video with
a text subtitle track and read it back the way a run does, so CI shows that
the tools behave the same on Linux, macOS and Windows. Skipped when ffmpeg is
not installed, except in CI, which installs it on every system.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_screen_ends_finds_a_real_cut_to_black(tmp_path: Path):
    # White to 6 s, black from 6 s to 9 s, white again to 12 s. The story
    # ends at 3 s, so ffmpeg seeks there and the times must be moved back.
    video = tmp_path / "Film.mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=25:d=6",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=25:d=3",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
            "-c:v", "mpeg4", str(video),
        ],
        check=True,
    )  # fmt: skip
    w = tmp_path / "work"
    w.mkdir()
    (w / "draft.tr.srt").write_text("1\n00:00:00,500 --> 00:00:03,000\nMerhaba.\n", encoding="utf-8")
    (w / "cues.json").write_text("[]", encoding="utf-8")
    out = screen.ends(w, video)
    [(start, end)] = out["black"]
    assert out["story_end_ms"] == 3_000 and abs(start - 6_000) <= 80 and abs(end - 9_000) <= 80
