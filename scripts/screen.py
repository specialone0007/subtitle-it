# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""What the picture shows, read with ffmpeg: no agent, no tokens.

    uv run screen.py ends --work W --video V

`ends` looks for the cut to black after the story: ffmpeg's blackdetect
(`d=2:pic_th=1.0:pix_th=0.10`, on the full-size picture) from story end
to 2.5 minutes after it. Story end is the end of the draft's last cue
that is not on-screen text, as `assemble.py deliver` reads it, so run it
after `check` has written the draft. It writes W/screen/ends.json with
every black stretch of 2 s or more, in ms of the video's own clock;
`deliver` starts the closing credit on the first one that begins within
30 s after story end.

ffmpeg missing, failing or too slow never stops a run: the result then
says why in `error`, no ends.json is left, and `deliver` places the
closing credit as it does without one.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble  # noqa: E402
import result  # noqa: E402
import srt  # noqa: E402

BLACK_FILTER = "blackdetect=d=2:pic_th=1.0:pix_th=0.10"
BLACK_MIN_MS = 2000
WINDOW_MS = 150_000
TIMEOUT_S = 900
# Transport streams keep their own clock: a picture's time is counted from
# the format's start_time, which a seek before -i does not add back.
OWN_CLOCK = {".ts", ".m2ts", ".mts"}
BLACK_RE = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")


def story_end(work: Path) -> int | None:
    """The end of the draft's last cue that is not on-screen text, or None
    with no such cue."""
    cues, _ = srt.parse(work / "draft.tr.srt")
    return assemble.story_end(cues, assemble.on_screen_draft_cues(work))


def black_stretches(stderr: str, offset_ms: int) -> list[list[int]]:
    """The black stretches blackdetect printed, moved by `offset_ms`, those
    of 2 s or more only, in time order."""
    out = []
    for a, b in BLACK_RE.findall(stderr):
        start, end = round(float(a) * 1000) + offset_ms, round(float(b) * 1000) + offset_ms
        if end - start >= BLACK_MIN_MS:
            out.append([start, end])
    return sorted(out)


def start_time_ms(video: Path) -> int:
    """The format's start_time for a transport stream, 0 for anything else."""
    if video.suffix.lower() not in OWN_CLOCK:
        return 0
    out = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=start_time", "-of", "json", str(video)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    return round(float(json.loads(out).get("format", {}).get("start_time") or 0) * 1000)


def ends(work: Path, video: Path) -> dict:
    """Write W/screen/ends.json (see the module docstring). Never raises for
    ffmpeg: a failure is returned in `error`, with no file left behind."""
    dest = work / assemble.ENDS_FILE
    dest.unlink(missing_ok=True)
    if not (work / "draft.tr.srt").exists():
        return {"ends": None, "error": "no draft: run assemble.py check first"}
    s = story_end(work)
    if s is None:
        return {"ends": None, "error": "the draft has no cue that is not on-screen text"}
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ends": None, "error": "ffmpeg not found on PATH"}
    cmd = [exe, "-hide_banner", "-nostats", "-ss", f"{s / 1000:.3f}", "-i", str(video), "-t", f"{WINDOW_MS / 1000:.0f}"]
    cmd += ["-map", "0:v:0", "-vf", BLACK_FILTER, "-an", "-sn", "-f", "null", "-"]
    began = time.monotonic()
    try:
        offset = s + start_time_ms(video)
        run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"ends": None, "error": f"ffmpeg failed: {type(e).__name__}"}
    took = round(time.monotonic() - began, 1)
    if run.returncode != 0:
        last = (run.stderr.strip().splitlines() or ["no message"])[-1]
        return {"ends": None, "error": f"ffmpeg failed (exit {run.returncode}): {last[:200]}", "seconds": took}
    data = {
        "video": str(video),
        "story_end_ms": s,
        "from_ms": s,
        "to_ms": s + WINDOW_MS,
        "black": black_stretches(run.stderr, offset),
        "seconds": took,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return {"ends": str(dest), **data}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ends")
    e.add_argument("--work", type=result.path, required=True)
    e.add_argument("--video", type=result.path, required=True)
    result.add_argument(p)
    a = result.parse(p, argv)
    result.emit(ends(a.work, a.video), a.result)


if __name__ == "__main__":
    main()
