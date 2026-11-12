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
            "-c:v", "mpeg4", "-c:a", "aac", "-c:s", "srt",
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
