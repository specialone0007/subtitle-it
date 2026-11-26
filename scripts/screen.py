# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""What the picture shows, read with ffmpeg.

    uv run screen.py ends    --work W --video V
    uv run screen.py frames  --work W --video V
    uv run screen.py collect --work W

`ends` looks for the cut to black after the story: ffmpeg's blackdetect
(`d=2:pic_th=0.98:pix_th=0.10`, on the full-size picture) from story end
to 2.5 minutes after it. ffmpeg counts the times from the seek point;
without `-copyts` the seek itself counts from the video's start_time, as
the tracks `sources.py` extracts do, so only the seek is added back.
Story end is the end of the draft's last cue that is not on-screen text,
as `assemble.py deliver` reads it, so run it after `check` has written the
draft. It writes W/screen/ends.json with every black stretch of 2 s or
more, in ms on the subtitles' clock; `deliver` starts the closing credit
on the one that leads into the end cards the frames show (credits, a
title card, closing text or a logo), never on a fade inside the last
scene. pic_th=0.98 lets 2% of the picture be lit: a cut to black that a
white title fades in over still counts.

ffmpeg missing, failing or too slow never stops a run: the result then
says why in `error`, no ends.json is left, and `deliver` places the
closing credit as it does without one.

`frames` saves the frames a reader agent reads for on-screen text, after
`prepare.py build` in step 2. Spoken cues here are the cues that are not
on-screen text, songs or sound descriptions. The head runs from 0:00 to
the first spoken cue (2.5 minutes at most), the tail from story end (the
end of the last spoken cue) to 2.5 minutes after it: one frame every
1.5 s in both, fitted into 960x540. HDR video is tone-mapped when this ffmpeg has zscale; otherwise the frames
are saved as they are and `notes` says so. The entries left out as shown
in too few languages become `unsure` in on_screen.json, and so do, when
the tracks hold exactly one other language (build.json
`other_languages`), that language's one-language entries; each unsure
entry outside the head and the tail gets 5 frames across its time widened by
2 s on each side, since the sync shift is not known yet. At most 300
frames: the unsure entries' frames are thinned first, down to 1 each,
then dropped latest first; the head and the tail never are. It writes
the frames to W/screen/frames/, W/screen/frames.json (each frame's file,
time, why it was picked and the texts of the entries within 3 s of it)
and one batch file of 20 frames at a time, W/screen/batch_NN.json, with
the file the reader writes its lines to; `readers` gives each reader's
batches, one reader per 40 frames.

Every frame is saved and listed, but not every one goes to a reader. A
frame with no pixel brighter than grey 20 of 255 (DARK_LEVEL) is `dark`:
stricter than `ends`, which lets 2% of the picture be lit, so a faint
title fading in over black is still read. A frame whose 96x54 grid of
tiles is within 4 grey levels (TILE_NOISE) of the frame that opened its
run shows the same picture, so it is `same_as` that frame: one changed
digit on a card moves a tile far more. The frame read for a run lists the
entries near any frame of it, and its reader can name several. Only the
other frames go into the batches (`sent` counts them). When ffmpeg cannot
measure the frames, all of them are sent and `notes` says so.

`collect` reads the readers' lines (agents/screen-reader.md) and writes
W/screen/readings.json: neighbouring frames with the same text (case,
punctuation, line breaks and spacing aside) joined into one reading, first
and last seen, and when the next frame was saved. A dark frame counts as
read with no text; a `same_as` frame takes the reading of its run's
frame, so a held card keeps its full time on screen. Every frame sent
must have exactly one valid line. The first time some do not, it writes
W/screen/batch_redo.json with those frames for one more reader and
returns it in `redo`; after that, frames still without a reading
(a sent frame or a repeat of it) are listed in `missing`.
`prepare.py build --screen W/screen/readings.json` then uses them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble  # noqa: E402
import prepare  # noqa: E402
import result  # noqa: E402
import srt  # noqa: E402

BLACK_FILTER = "blackdetect=d=2:pic_th=0.98:pix_th=0.10"
BLACK_MIN_MS = 2000
WINDOW_MS = 150_000
TIMEOUT_S = 900
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
        "black": black_stretches(run.stderr, s),
        "seconds": took,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return {"ends": str(dest), **data}


# --- frames for the reader ----------------------------------------------------

FRAME_STEP_MS = 1500
FRAME_W, FRAME_H = 960, 540
MAX_FRAMES = 300
FRAMES_PER_UNSURE = 5
UNSURE_WIDEN_MS = 2000
NEAR_MS = 3000
BATCH = 20
PER_READER = 40
# Neighbouring frames further apart than this are never one reading.
NEIGHBOUR_MS = 5000
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
TONE_MAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)
SCALE = f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=decrease"
FRAMES_DIR = Path("screen") / "frames"
READINGS_FILE = Path("screen") / "readings.json"
REDO = "redo"
# A frame is dark, and not read, when no pixel of it is brighter than this
# grey level (of 255), measured at full size. Stricter than the cut to black
# (`ends`), which lets 2% of the picture be lit: one brighter pixel keeps
# the frame, so a faint title fading in over black is still read. Black
# frames saved as JPEG peak at about 15.
DARK_LEVEL = 20
# A frame repeats the frame that opened its run when no tile of a 96x54 grid
# (10x10 pixels of a 960x540 frame) moved more than TILE_NOISE grey levels:
# one changed digit on a card ("2020", "2021") moves a tile by 80 or more,
# a held card moves none by more than 2 or 3.
TILES_W, TILES_H = 96, 54
TILE_NOISE = 4
DARK = "dark"
# What `collect` records for a dark frame: read, with no text.
BLANK = {"text": "", "kind": "background", "wants_read": False, "shows_entry": []}


def spoken_spans(rows: list[dict]) -> list[tuple[int, int]]:
    """The spoken cues of step 2: not on-screen text, not a song row and
    not a sound description, whatever --hi said."""
    out = []
    for r in rows:
        lines = r.get("timing_lines") or []
        if r.get("on_screen") or r.get("song") or r.get("sound_only") or not lines:
            continue
        if srt.is_sound(srt.Cue(n=r["n"], start=r["start"], end=r["end"], ts=r["ts"], lines=lines)):
            continue
        out.append((r["start"], r["end"]))
    return out


def unsure_ids(entries: list[dict], other_languages: list[str]) -> list[str]:
    """The entries the picture decides: those left out as shown in too few
    languages, whatever the count, and with exactly one other language its
    one-language entries. An entry an earlier run marked unsure stays so."""
    one = other_languages[0] if len(other_languages) == 1 else None
    out = []
    for e in entries:
        state, reason = e.get("state"), e.get("reason")
        if state not in ("unsure", "left_out"):
            continue
        langs = srt.other_languages(e.get("texts", {}), None)
        if reason == prepare.FEW_LANGUAGES or (state == "unsure" and len(langs) >= 2):
            out.append(e["id"])
        elif one and (state == "unsure" or reason == prepare.ONE_LANGUAGE) and langs == [one]:
            out.append(e["id"])
    return out


def _spread(a: int, b: int, k: int) -> list[int]:
    """k times across a..b, both ends included; the middle for one."""
    if k == 1:
        return [(a + b) // 2]
    return [round(a + i * (b - a) / (k - 1)) for i in range(k)]


def plan_frames(rows: list[dict], entries: list[dict], other_languages: list[str], duration_ms: int | None) -> dict:
    """Which frames to save, and why: no ffmpeg here. Returns the windows,
    the unsure ids, the frame list (ms, why) in time order and notes."""
    spoken = spoken_spans(rows)
    if not spoken:
        return {"error": "no spoken cue: nothing marks the head or the tail"}
    first = min(a for a, _ in spoken)
    end = max(b for _, b in spoken)
    head = (0, min(first, WINDOW_MS))
    tail_to = end + WINDOW_MS
    if duration_ms:
        tail_to = min(tail_to, duration_ms)
    tail = (end, max(end, tail_to))
    picks: list[tuple[int, str]] = [(t, "head") for t in range(head[0], head[1], FRAME_STEP_MS)]
    picks += [(t, "tail") for t in range(tail[0], tail[1], FRAME_STEP_MS)]
    unsure = unsure_ids(entries, other_languages)
    by_id = {e["id"]: e for e in entries}

    def in_ends(e: dict) -> bool:
        return any(min(e["end"], b) > max(e["start"], a) for a, b in (head, tail) if b > a)

    mid = sorted((by_id[i] for i in unsure if not in_ends(by_id[i])), key=lambda e: (e["start"], e["id"]))
    budget = MAX_FRAMES - len(picks)
    notes = []
    counts = {e["id"]: FRAMES_PER_UNSURE for e in mid}
    if FRAMES_PER_UNSURE * len(mid) > budget:
        if budget >= len(mid):
            per, extra = divmod(budget, len(mid))
            for k, e in enumerate(mid):
                counts[e["id"]] = per + (1 if k < extra else 0)
            notes.append(
                f"frame cap {MAX_FRAMES}: the frames of {len(mid)} unsure entries were thinned to {per}"
                + (f" or {per + 1}" if extra else "")
                + " each"
            )
        else:
            keep = max(budget, 0)
            for k, e in enumerate(mid):
                counts[e["id"]] = 1 if k < keep else 0
            dropped = [e["id"] for e in mid[keep:]]
            notes.append(
                f"frame cap {MAX_FRAMES}: {len(mid)} unsure entries thinned to 1 frame each and the "
                f"{len(dropped)} latest got none: {', '.join(dropped)}"
            )
    for e in mid:
        a = max(e["start"] - UNSURE_WIDEN_MS, 0)
        b = e["end"] + UNSURE_WIDEN_MS
        if duration_ms:
            b = min(b, duration_ms - 1)
        if counts[e["id"]]:
            picks += [(t, f"entry {e['id']}") for t in _spread(a, max(a, b), counts[e["id"]])]
    picks.sort(key=lambda x: (x[0], x[1]))
    return {
        "head": list(head),
        "tail": list(tail),
        "first_spoken_ms": first,
        "story_end_ms": end,
        "unsure": unsure,
        "picks": picks,
        "notes": notes,
    }


def near(entries: list[dict], ms: int) -> list[dict]:
    """The entries within 3 s of a frame, with their texts on one line each,
    so the reader can say which one the frame shows."""
    return [
        {"id": e["id"], "texts": {k: prepare._one_line(v) for k, v in e.get("texts", {}).items()}}
        for e in entries
        if e["start"] - NEAR_MS <= ms <= e["end"] + NEAR_MS
    ]


def _probe(exe: str, video: Path) -> tuple[int | None, bool]:
    """The video's length in ms and whether its picture is HDR."""
    probe = shutil.which("ffprobe") or str(Path(exe).with_name("ffprobe"))
    cmd = [probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer:format=duration"]
    cmd += ["-of", "json", str(video)]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        data = json.loads(run.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, False
    try:
        duration = round(float(data.get("format", {}).get("duration")) * 1000)
    except (TypeError, ValueError):
        duration = None
    transfer = ((data.get("streams") or [{}])[0] or {}).get("color_transfer", "")
    return duration, transfer in HDR_TRANSFERS


def _has_zscale(exe: str) -> bool:
    try:
        run = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return re.search(r"\bzscale\b", run.stdout) is not None


def _run(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S).returncode == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _save_window(exe: str, video: Path, a: int, b: int, vf: str, pattern: Path) -> list[Path]:
    """One frame every FRAME_STEP_MS from a to b, in one ffmpeg pass: the
    k-th file is the frame on screen at a + k * step. Returns the files in
    order. The fps filter drops its last frame when the input stops at it
    (the window's end, or the video's), so it reads one step more than it
    keeps; round=up takes the frame at or just before each step."""
    count = math.ceil((b - a) / FRAME_STEP_MS)
    cmd = [exe, "-hide_banner", "-nostats", "-v", "error", "-y", "-ss", f"{a / 1000:.3f}", "-i", str(video)]
    cmd += ["-t", f"{(count + 1) * FRAME_STEP_MS / 1000:.3f}", "-map", "0:v:0", "-an", "-sn"]
    fps = f"fps={1000 / FRAME_STEP_MS:.6f}:round=up"
    cmd += ["-vf", f"{vf},{fps}", "-frames:v", str(count), "-q:v", "3", str(pattern)]
    _run(cmd)
    return [Path(str(pattern) % (k + 1)) for k in range(count)]


def _save_one(exe: str, video: Path, ms: int, vf: str, dest: Path) -> None:
    cmd = [exe, "-hide_banner", "-nostats", "-v", "error", "-y", "-ss", f"{ms / 1000:.3f}", "-i", str(video)]
    cmd += ["-map", "0:v:0", "-an", "-sn", "-vf", vf, "-frames:v", "1", "-q:v", "3", str(dest)]
    _run(cmd)


def _grey(exe: str, pattern: Path, count: int, scale: str, size: int) -> list[bytes] | None:
    """The `count` frames of `pattern` (numbered from 1) as grey bytes of
    `size` each, after `scale`; None when ffmpeg fails or gives fewer. Read
    one frame at a time, so 300 full-size frames never sit in memory."""
    cmd = [exe, "-hide_banner", "-nostats", "-v", "error", "-start_number", "1", "-i", str(pattern)]
    cmd += ["-frames:v", str(count), "-vf", f"{scale},format=gray", "-f", "rawvideo", "-"]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        return None
    out = []
    try:
        for _ in range(count):
            chunk = proc.stdout.read(size)
            if len(chunk) < size:
                return None
            out.append(chunk)
        return out if proc.wait(timeout=TIMEOUT_S) == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()


def _measure(exe: str, out_dir: Path, count: int) -> list[tuple[int, bytes]] | None:
    """Each saved frame's brightest grey level at full size and its 96x54
    grid of tile means, or None when ffmpeg could not read them. Frames
    fitted into less than 960x540 are stretched to it pixel by pixel, which
    keeps their brightest pixel."""
    pattern = out_dir / "frame_%04d.jpg"
    full = _grey(exe, pattern, count, f"scale={FRAME_W}:{FRAME_H}:flags=neighbor", FRAME_W * FRAME_H)
    tiles = _grey(exe, pattern, count, f"scale={TILES_W}:{TILES_H}:flags=area", TILES_W * TILES_H) if full else None
    if full is None or tiles is None:
        return None
    return [(max(f), t) for f, t in zip(full, tiles)]


def _same_picture(a: bytes, b: bytes) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= TILE_NOISE for x, y in zip(a, b))


def plan_reads(stats: list[tuple[int, bytes]]) -> list[int | str | None]:
    """For each frame in time order: DARK when no pixel is brighter than
    DARK_LEVEL; the index of the frame that opened its run when every tile
    is within TILE_NOISE of that frame's (it shows the same picture, so
    the same text); None when it is read. A dark frame ends a run."""
    out: list[int | str | None] = []
    kept = None
    for k, (peak, tiles) in enumerate(stats):
        if peak <= DARK_LEVEL:
            out.append(DARK)
            kept = None
        elif kept is not None and _same_picture(stats[kept][1], tiles):
            out.append(kept)
        else:
            out.append(None)
            kept = k
    return out


def mark_reads(listed: list[dict], plan: list[int | str | None]) -> list[dict]:
    """Mark the frames.json frames per `plan_reads`: `dark: true`, or
    `same_as` the file of the frame read for them. The frame read for a run
    lists the entries near any frame of it, so its reader can name one the
    later frames are near. Returns the frames the readers get."""
    for f, p in zip(listed, plan):
        if p == DARK:
            f["dark"] = True
        elif p is not None:
            kept = listed[p]
            f["same_as"] = kept["file"]
            have = {e["id"] for e in kept["entries"]}
            kept["entries"] += [e for e in f["entries"] if e["id"] not in have]
    return [f for f in listed if not f.get("dark") and not f.get("same_as")]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _clear_reading(work: Path) -> None:
    """An earlier `frames` run's frames, batches and readings: never read
    into this one. ends.json stays."""
    shutil.rmtree(work / FRAMES_DIR, ignore_errors=True)
    screen = work / "screen"
    if screen.exists():
        for old in list(screen.glob("batch_*.json")) + list(screen.glob("read_*.jsonl")):
            old.unlink()
    (work / prepare.FRAMES_FILE).unlink(missing_ok=True)
    (work / READINGS_FILE).unlink(missing_ok=True)


def frames(work: Path, video: Path) -> dict:
    """Write the frames, frames.json and the batch files (see the module
    docstring), and mark the unsure entries in on_screen.json. Never
    raises for ffmpeg: a failure is returned in `error`, with no
    frames.json and on_screen.json as it was."""
    _clear_reading(work)
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    entries_path = work / prepare.ON_SCREEN_FILE
    entries = json.loads(entries_path.read_text(encoding="utf-8")) if entries_path.exists() else []
    info = (assemble._build_info(work).get("on_screen") or {}) if (work / "build.json").exists() else {}
    others = info.get("other_languages") or []
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"frames": None, "error": "ffmpeg not found on PATH"}
    began = time.monotonic()
    duration, hdr = _probe(exe, video)
    plan = plan_frames(rows, entries, others, duration)
    if "error" in plan:
        return {"frames": None, "error": plan["error"]}
    notes = list(plan["notes"])
    vf = SCALE
    tone_mapped = None
    if hdr:
        tone_mapped = _has_zscale(exe)
        if tone_mapped:
            vf = f"{SCALE},{TONE_MAP}"
        else:
            notes.append("HDR video: this ffmpeg has no zscale (zimg), so the frames were saved without tone mapping")
    out_dir = work / FRAMES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[tuple[int, str], Path] = {}
    for why in ("head", "tail"):
        a, b = plan[why]
        if b <= a:
            continue
        files = _save_window(exe, video, a, b, vf, out_dir / f"{why}_%04d.jpg")
        if tone_mapped and not any(f.exists() for f in files):
            # The tone map failed on this video: save them as they are.
            tone_mapped = False
            vf = SCALE
            notes.append("HDR video: tone mapping failed, so the frames were saved without it")
            files = _save_window(exe, video, a, b, vf, out_dir / f"{why}_%04d.jpg")
        for k, f in enumerate(files):
            saved[(a + k * FRAME_STEP_MS, why)] = f
    for k, (ms, why) in enumerate(p for p in plan["picks"] if p[1] not in ("head", "tail")):
        dest = out_dir / f"entry_{k + 1:04d}.jpg"
        _save_one(exe, video, ms, vf, dest)
        saved[(ms, why)] = dest
    frames_out = []
    lost = 0
    for ms, why in plan["picks"]:
        src = saved.get((ms, why))
        if src is None or not src.exists():
            lost += 1
            continue
        frames_out.append({"ms": ms, "why": why, "src": src})
    if not frames_out:
        shutil.rmtree(out_dir, ignore_errors=True)
        return {"frames": None, "error": "ffmpeg saved no frame from this video", "seconds": round(time.monotonic() - began, 1)}
    if lost:
        notes.append(f"{lost} frames could not be saved (past the end of the video or unreadable)")
    # Numbered in time order, so a file name says where it is.
    listed = []
    for k, f in enumerate(frames_out, 1):
        name = f"frame_{k:04d}.jpg"
        dest = out_dir / name
        os.replace(f["src"], dest)
        listed.append(
            {
                "file": name,
                "path": str(dest),
                "ms": f["ms"],
                "at": srt.fmt_ms(f["ms"]),
                "why": f["why"],
                "entries": near(entries, f["ms"]),
            }
        )
    for leftover in out_dir.glob("*.jpg"):
        if not leftover.name.startswith("frame_"):
            leftover.unlink()
    stats = _measure(exe, out_dir, len(listed))
    if stats is None:
        notes.append(f"the frames could not be measured for black or repeats, so all {len(listed)} go to the readers")
        sent = listed
    else:
        sent = mark_reads(listed, plan_reads(stats))
    readers = []
    batch_no = 0
    for r in range(math.ceil(len(sent) / PER_READER)):
        mine = sent[r * PER_READER : (r + 1) * PER_READER]
        batches = []
        for b in range(0, len(mine), BATCH):
            batch_no += 1
            path = work / "screen" / f"batch_{batch_no:02d}.json"
            _write_json(
                path,
                {"batch": batch_no, "out": str(work / "screen" / f"read_{batch_no:02d}.jsonl"), "frames": mine[b : b + BATCH]},
            )
            batches.append(str(path))
        readers.append({"reader": r + 1, "frames": len(mine), "batches": batches})
    data = {
        "video": str(video),
        "head": plan["head"],
        "tail": plan["tail"],
        "first_spoken_ms": plan["first_spoken_ms"],
        "story_end_ms": plan["story_end_ms"],
        "other_languages": others,
        "unsure": plan["unsure"],
        "hdr": hdr,
        "tone_mapped": tone_mapped,
        "notes": notes,
        "readers": readers,
        "frames": listed,
    }
    # Unsure, not left out, until `build --screen` decides.
    unsure = set(plan["unsure"])
    for e in entries:
        if e["id"] in unsure:
            e["state"] = "unsure"
            e.pop("reason", None)
    if unsure:
        _write_json(entries_path, entries)
    _write_json(work / prepare.FRAMES_FILE, data)
    took = round(time.monotonic() - began, 1)
    return {
        "frames_file": str(work / prepare.FRAMES_FILE),
        "frames": len(listed),
        "sent": len(sent),
        "dark": sum(1 for f in listed if f.get("dark")),
        "repeats": sum(1 for f in listed if f.get("same_as")),
        "head": sum(1 for f in listed if f["why"] == "head"),
        "tail": sum(1 for f in listed if f["why"] == "tail"),
        "unsure": len(unsure),
        "readers": readers,
        "hdr": hdr,
        "tone_mapped": tone_mapped,
        "notes": notes,
        "seconds": took,
    }


# --- collecting the readers' lines ------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_line(line: str, frames_by_name: dict[str, dict]) -> tuple[str | None, dict | None]:
    """One reader line: (frame name, reading) or (frame name, None) when
    the line names a frame but is not valid, (None, None) otherwise."""
    try:
        item = json.loads(line)
    except ValueError:
        return None, None
    # A value of the wrong type (a list, a number) is a bad line, never a
    # crash: it is what the redo is for.
    if not isinstance(item, dict) or not isinstance(item.get("frame"), str) or item["frame"] not in frames_by_name:
        return None, None
    name = item["frame"]
    text, kind, wants = item.get("text"), item.get("kind"), item.get("wants_read")
    # One id, or a list of them when the text shows several entries (one
    # card a track split into two lines).
    shows = item.get("shows_entry")
    if shows in ("", "none", "None", None):
        shows = []
    elif isinstance(shows, str):
        shows = [shows]
    listed = {e["id"] for e in frames_by_name[name].get("entries", [])}
    if not isinstance(text, str) or kind not in prepare.READER_KINDS or not isinstance(wants, bool):
        return name, None
    if not isinstance(shows, list) or not all(isinstance(i, str) and i in listed for i in shows):
        return name, None
    return name, {"text": _norm(text), "kind": kind, "wants_read": wants, "shows_entry": sorted(set(shows))}


def _read_lines(path: Path, frames_by_name: dict[str, dict]) -> dict[str, list[dict | None]]:
    got: dict[str, list[dict | None]] = {}
    if not path.exists():
        return got
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        name, reading = parse_line(line.strip(), frames_by_name)
        if name is not None:
            got.setdefault(name, []).append(reading)
    return got


def _one(lines: list[dict | None] | None) -> dict | None:
    """The frame's reading when it has exactly one line and it is valid."""
    return lines[0] if lines and len(lines) == 1 and lines[0] is not None else None


def _join_key(r: dict) -> tuple[str, str]:
    """What two neighbouring frames must share to be one reading: the text
    with case, punctuation, line breaks and spacing folded away, and the
    kind, any two story kinds counting as one ("sign" and "caption")."""
    return prepare.fold_text(r["text"]), "story" if prepare.is_story_kind(r["kind"]) else r["kind"]


def _most(values: list) -> object:
    """The value most frames give; on a tie, the first frame's."""
    return max(values, key=lambda v: (values.count(v), -values.index(v)))


def join_readings(listed: list[dict], read: dict[str, dict]) -> list[dict]:
    """Neighbouring frames (next to each other in time order, NEIGHBOUR_MS
    apart at most) that show the same text become one reading (_join_key):
    a reader writing "Mommy's home" on one frame and "mommy's home" on the
    next is one text. The reading takes the text and kind most of its frames
    give (the first frame's on a tie), and wants_read when any frame says so,
    since a card fading in can look like background on its first frame.
    `next_ms` is the time of the next saved frame after its last one, null
    after the last saved frame: the text stays on screen until then at most
    (prepare.picture_shown_end). A frame with no text, or not read, ends a
    reading."""
    groups: list[list[tuple[dict, dict]]] = []
    prev = None
    for f in listed:
        r = read.get(f["file"])
        if r is None or not r["text"]:
            prev = None
            continue
        key = _join_key(r)
        if prev is not None and prev[0] == key and f["ms"] - prev[1] <= NEIGHBOUR_MS:
            groups[-1].append((f, r))
        else:
            groups.append([(f, r)])
        prev = (key, f["ms"])
    times = [f["ms"] for f in listed]
    out: list[dict] = []
    for g in groups:
        first, last = g[0][0], g[-1][0]
        kind = _most([r["kind"] for _, r in g])
        wants = any(r["wants_read"] for _, r in g)
        shows = sorted({i for _, r in g for i in r["shows_entry"]})
        out.append(
            {
                "text": _most([r["text"] for _, r in g]),
                "kind": kind,
                "wants_read": wants,
                "story": prepare.is_story(kind, wants),
                "first_ms": first["ms"],
                "last_ms": last["ms"],
                "next_ms": next((t for t in times if t > last["ms"]), None),
                "at": first["at"],
                "frames": [f["file"] for f, _ in g],
                "shows_entry": shows,
            }
        )
    return out


def collect(work: Path) -> dict:
    """Write W/screen/readings.json from the readers' lines (see the module
    docstring)."""
    frames_path = work / prepare.FRAMES_FILE
    if not frames_path.exists():
        raise SystemExit(f"no {frames_path}: run screen.py frames first")
    data = json.loads(frames_path.read_text(encoding="utf-8"))
    listed = data["frames"]
    by_name = {f["file"]: f for f in listed}
    screen = work / "screen"
    got: dict[str, list[dict | None]] = {}
    for batch in sorted(screen.glob("batch_[0-9]*.json")):
        out = Path(json.loads(batch.read_text(encoding="utf-8"))["out"])
        for name, lines in _read_lines(out, by_name).items():
            got.setdefault(name, []).extend(lines)
    read = {name: r for name in by_name if (r := _one(got.get(name))) is not None}
    redo_batch = screen / f"batch_{REDO}.json"
    if redo_batch.exists():
        redo_lines = _read_lines(Path(json.loads(redo_batch.read_text(encoding="utf-8"))["out"]), by_name)
        for name in by_name:
            if name not in read and (r := _one(redo_lines.get(name))) is not None:
                read[name] = r
    # Frames no reader got: a dark one is read with no text, a repeat takes
    # the reading of the frame read for its run.
    for f in listed:
        if f.get("dark"):
            read[f["file"]] = dict(BLANK)
        elif f.get("same_as") in read:
            read[f["file"]] = read[f["same_as"]]
    missing = [f["file"] for f in listed if f["file"] not in read]
    redo = None
    resend = [by_name[n] for n in missing if not by_name[n].get("same_as")]
    if resend and not redo_batch.exists():
        # Back to one reader, once; a repeat follows its run's frame.
        _write_json(
            redo_batch,
            {"batch": REDO, "out": str(screen / f"read_{REDO}.jsonl"), "frames": resend},
        )
        redo = str(redo_batch)
    readings = join_readings(listed, read)
    _write_json(
        work / READINGS_FILE,
        {"frames": len(listed), "read": len(read), "missing": missing, "readings": readings},
    )
    return {
        "readings_file": str(work / READINGS_FILE),
        "frames": len(listed),
        "read": len(read),
        "missing": missing,
        "redo": redo,
        "readings": len(readings),
        "story_readings": sum(1 for r in readings if r["story"]),
    }


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("ends", "frames"):
        e = sub.add_parser(name)
        e.add_argument("--work", type=result.path, required=True)
        e.add_argument("--video", type=result.path, required=True)
    c = sub.add_parser("collect")
    c.add_argument("--work", type=result.path, required=True)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "ends":
        result.emit(ends(a.work, a.video), a.result)
    elif a.cmd == "frames":
        result.emit(frames(a.work, a.video), a.result)
    else:
        result.emit(collect(a.work), a.result)


if __name__ == "__main__":
    main()
