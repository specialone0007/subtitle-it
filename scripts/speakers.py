# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "charset-normalizer>=3.3",
#   "faster-whisper>=1.1",
#   "huggingface_hub>=0.21,<1",
#   "numpy>=1.24",
#   "pyannote.audio>=3.3,<4",
#   "torch>=2.4,<2.9",
#   "torchaudio>=2.4,<2.9",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cu124"
# url = "https://download.pytorch.org/whl/cu124"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cu124", marker = "sys_platform != 'darwin'" }
# torchaudio = { index = "pytorch-cu124", marker = "sys_platform != 'darwin'" }
# ///
"""Speaker hints from the film's audio: which voice speaks each cue.

    uv run speakers.py setup --config CONFIG
    uv run speakers.py run   --video V --work W [--config CONFIG] [--no-sync-check]

CONFIG defaults to ~/.config/turkish-subtitles.

`setup` asks for a Hugging Face token without showing it and stores it in
CONFIG/credentials.json under "hf_token". The token's account must have
accepted the terms of pyannote/speaker-diarization-3.1 and
pyannote/segmentation-3.0 on huggingface.co. HF_TOKEN in the environment
also works.

`run` extracts the audio with ffmpeg, finds who speaks when with pyannote,
merges voices that sound alike (pyannote splits one character into
several), and gives each cue in W/timing.srt the voice that clearly
overlaps it most (V1, V2, ... in order of first appearance). A cue with
two dash lines holds two speakers, so it gets no voice. A voice whose
labelled cues name several characters, none of them in two thirds of the
cues, gives no voice to any cue; the result counts these in
"voices_dropped". Progress goes to stderr. It writes `voice` into
W/speakers.json and keeps every `label` and `name` already there. Unless
--no-sync-check is given, faster-whisper finds where speech starts in five
3-minute stretches spread over the film, and the script reports how far the
subtitles sit from the audio. The first run
downloads the models (a few GB). Without a token it prints
{"skipped": "token missing"} and exits with code 3.
"""

from __future__ import annotations

import argparse
import bisect
import getpass
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import srt  # noqa: E402

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
WHISPER_MODEL = "small"
MIN_SHARE = 0.3  # a voice must cover this share of the cue to be named
# The runner-up voice must cover less than this share of the top voice's time,
# or the cue is too close to call.
MARGIN = 0.3
# Voices whose embedding centroids have at least this cosine similarity are
# one voice. Tuned on a feature film against 412 speaker names from its SDH
# track: 57 voices became 32 with no loss of accuracy; at 0.4 accuracy fell.
MERGE_SIMILARITY = 0.55
TOKEN_MISSING = 3


# --- token -----------------------------------------------------------------


def _cred_path(config: Path) -> Path:
    return config / "credentials.json"


def load_token(config: Path | None) -> str | None:
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    if config is None or not _cred_path(config).exists():
        return None
    return json.loads(_cred_path(config).read_text(encoding="utf-8")).get("hf_token") or None


def save_token(config: Path, token: str) -> None:
    """Add the token to credentials.json, keeping the OpenSubtitles entries."""
    config.mkdir(parents=True, exist_ok=True)
    p = _cred_path(config)
    creds = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    creds["hf_token"] = token
    result.write_private(p, json.dumps(creds, indent=1))


def setup(config: Path) -> None:
    print("Hugging Face token for speaker hints. Nothing you type is shown or printed back.")
    print("Create a read token at https://huggingface.co/settings/tokens and accept the terms of")
    print(f"https://huggingface.co/{DIARIZATION_MODEL} and https://huggingface.co/pyannote/segmentation-3.0")
    token = getpass.getpass("Token: ").strip()
    if not token:
        raise SystemExit("No token entered; nothing changed.")
    save_token(config, token)
    print("Saved.")


# --- pure logic (tested) ---------------------------------------------------

Turn = tuple[int, int, str]  # start ms, end ms, speaker id from the diarizer


def two_speakers(c: srt.Cue) -> bool:
    """A cue with two or more lines starting with a dash ("- Who?" / "- Me.")."""
    return srt.dash_lines(c.lines) >= 2


def assign_voices(cues: list[srt.Cue], turns: list[Turn], min_share: float = MIN_SHARE, margin: float = MARGIN) -> dict[int, str]:
    """Give each cue the speaker that overlaps it most, when that speaker
    covers at least `min_share` of the cue and the runner-up covers less
    than `margin` times the top speaker's time. A cue with two dash lines
    gets no voice: one voice would be wrong for one of its lines. Speakers
    are renamed V1, V2, ... in the order they first win a cue."""
    turns = sorted(turns)
    names: dict[str, str] = {}
    out: dict[int, str] = {}
    i = 0
    for c in cues:
        while i < len(turns) and turns[i][1] <= c.start:
            i += 1
        overlap: dict[str, int] = {}
        j = i
        while j < len(turns) and turns[j][0] < c.end:
            s, e, who = turns[j]
            ov = min(e, c.end) - max(s, c.start)
            if ov > 0:
                overlap[who] = overlap.get(who, 0) + ov
            j += 1
        if not overlap or c.duration <= 0 or two_speakers(c):
            continue
        ranked = sorted(overlap.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
        who, ov = ranked[0]
        if ov / c.duration < min_share:
            continue
        if len(ranked) > 1 and ranked[1][1] >= margin * ov:
            continue
        names.setdefault(who, f"V{len(names) + 1}")
        out[c.n] = names[who]
    return out


def merge_similar(turns: list[Turn], centroids: dict[str, list[float]], threshold: float = MERGE_SIMILARITY) -> list[Turn]:
    """Relabel turns so speakers whose centroids are alike share one label.
    Merges the most similar pair first, over and over, while its cosine
    similarity is at least `threshold`; a merged centroid is the average
    of its parts weighted by speech time. A speaker with no centroid (or a
    zero or non-finite one) is never merged."""

    def unit(v: list[float]) -> list[float] | None:
        if not all(math.isfinite(x) for x in v):
            return None
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v] if n > 0 else None

    time: dict[str, int] = {}
    for s, e, who in turns:
        time[who] = time.get(who, 0) + e - s
    cent = {k: u for k, v in centroids.items() if k in time and (u := unit(v)) is not None}
    weight = {k: time[k] for k in cent}
    into = {k: k for k in time}
    while len(cent) > 1:
        keys = sorted(cent)
        sim, a, b = max((sum(x * y for x, y in zip(cent[a], cent[b])), a, b) for i, a in enumerate(keys) for b in keys[i + 1 :])
        if sim < threshold:
            break
        both = [x * weight[a] + y * weight[b] for x, y in zip(cent[a], cent[b])]
        cent[a] = unit(both) or cent[a]
        weight[a] += weight.pop(b)
        del cent[b]
        for k, v in into.items():
            if v == b:
                into[k] = a
    return [(s, e, into[who]) for s, e, who in turns]


def merge_voices(speakers: dict[str, dict], voices: dict[int, str]) -> dict[str, dict]:
    """Set `voice` per cue; drop old voices; keep labels and names."""
    merged: dict[str, dict] = {}
    for n, entry in speakers.items():
        rest = {k: v for k, v in entry.items() if k != "voice"}
        if rest:
            merged[n] = rest
    for n, v in voices.items():
        merged.setdefault(str(n), {})["voice"] = v
    return dict(sorted(merged.items(), key=lambda kv: int(kv[0])))


# A voice can gather several characters: pyannote sometimes hears a
# narrator, a crowd or two similar voices as one. The labels in the
# subtitles show this. A voice is "mixed" when at least MIXED_MIN_LABELLED
# of its cues carry a one-speaker label and no character holds
# MIXED_TOP_SHARE of them. Below that share the hint names the wrong person
# in at least one cue in three; the translator then picks sen or siz for
# the wrong pair, which is worse than having no hint. Fewer labelled cues
# are too few to judge, so the voice stays.
MIXED_MIN_LABELLED = 6
MIXED_TOP_SHARE = 2 / 3


def mixed_voices(speakers: dict[str, dict], voices: dict[int, str]) -> dict[str, dict]:
    """The voices that mix several characters, by the labels on their cues:
    {voice: {"labelled_cues", "characters", "top_share"}}. A label naming two
    speakers ("Nora / Sam") is left out."""
    seen: dict[str, dict[str, int]] = {}
    for n, v in voices.items():
        label = (speakers.get(str(n)) or {}).get("label")
        if not label or "/" in label:
            continue
        who = label.strip().casefold()
        seen.setdefault(v, {})
        seen[v][who] = seen[v].get(who, 0) + 1
    mixed = {}
    for v, names in seen.items():
        total = sum(names.values())
        top = max(names.values()) / total
        if total >= MIXED_MIN_LABELLED and top < MIXED_TOP_SHARE:
            mixed[v] = {"labelled_cues": total, "characters": len(names), "top_share": round(top, 2)}
    return dict(sorted(mixed.items(), key=lambda kv: int(kv[0][1:])))


# The sync check tries every constant offset in ±SYNC_SEARCH_MS, in
# SYNC_STEP_MS steps. A speech start matches an offset when a cue start lies
# within SYNC_TOLERANCE_MS of it once the cues are moved back by that offset.
SYNC_SEARCH_MS = 20_000
SYNC_STEP_MS = 100
SYNC_TOLERANCE_MS = 300
SYNC_MAX_IN_SYNC_MS = 300
# The best offset must match at least this many speech starts, and this many
# times as many as the best offset more than SYNC_PEAK_GAP_MS away from it.
# On a 2-hour test film the true offset matched 98 of 160 starts and the best other
# one 44, whatever the shift.
SYNC_MIN_MATCHED = 20
SYNC_MIN_LEAD = 1.5
SYNC_PEAK_GAP_MS = 1000


def _offset_pairs(cue_starts: list[int], speech: list[int], offset: int) -> list[int]:
    """cue start - speech start for each speech start whose nearest cue
    start, moved back by `offset`, lies within SYNC_TOLERANCE_MS of it.
    `cue_starts` is sorted."""
    out = []
    for s in speech:
        i = bisect.bisect_left(cue_starts, s + offset)
        near = [cue_starts[j] for j in (i - 1, i) if 0 <= j < len(cue_starts)]
        if near:
            c = min(near, key=lambda c: abs(c - s - offset))
            if abs(c - s - offset) <= SYNC_TOLERANCE_MS:
                out.append(c - s)
    return out


def sync_offset(cues: list[srt.Cue], speech_starts: list[int]) -> dict:
    """How far the subtitles sit from the speech, in ms. Positive: the
    subtitles come late.

    Matching each cue to its nearest speech start fails once the shift nears
    the gap between lines: the nearest start then belongs to the line before
    or after, and the gaps cancel out (1.5 s on a test film read as in sync).
    So, as `srt.py fit` does for two files, this tries every constant offset
    and keeps the one under which most speech starts land on a cue start;
    ties go to the smallest offset, so an in-sync file stays put. The
    reported offset is the median gap over the starts matched at that offset.

    `matched_cues` counts speech starts that landed on a cue start (two
    starts can land on one cue), `speech_starts` all of them, and
    `runner_up_matched` the best count of an offset more than
    SYNC_PEAK_GAP_MS from the chosen one."""
    speech = sorted(speech_starts)
    cue_starts = sorted(c.start for c in cues)
    base = {"matched_cues": 0, "speech_starts": len(speech), "runner_up_matched": 0, "median_offset_ms": None}
    if not speech or not cue_starts:
        return {**base, "verdict": "no speech matched the cues"}
    scores = {d: len(_offset_pairs(cue_starts, speech, d)) for d in range(-SYNC_SEARCH_MS, SYNC_SEARCH_MS + 1, SYNC_STEP_MS)}
    best = max(scores, key=lambda d: (scores[d], -abs(d)))
    runner_up = max((n for d, n in scores.items() if abs(d - best) > SYNC_PEAK_GAP_MS), default=0)
    diffs = _offset_pairs(cue_starts, speech, best)
    base |= {"matched_cues": len(diffs), "runner_up_matched": runner_up}
    if len(diffs) < SYNC_MIN_MATCHED:
        return {**base, "verdict": f"too little speech to judge: {len(diffs)} starts matched a cue (needs {SYNC_MIN_MATCHED})"}
    if len(diffs) < SYNC_MIN_LEAD * runner_up:
        return {**base, "verdict": f"no clear offset: best {best} ms matched {len(diffs)} starts, another {runner_up}"}
    # The 100 ms grid leaves the matched window off-centre; centre it on the
    # median once and measure again.
    diffs = _offset_pairs(cue_starts, speech, int(statistics.median(diffs))) or diffs
    base["matched_cues"] = len(diffs)
    med = int(statistics.median(diffs))
    verdict = "in sync" if abs(med) <= SYNC_MAX_IN_SYNC_MS else f"subtitles are {abs(med)} ms {'late' if med > 0 else 'early'}"
    return {**base, "median_offset_ms": med, "verdict": verdict}


# --- audio (needs the models) ---------------------------------------------


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def extract_audio(video: Path, dest: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
        check=True,
    )
    return dest


def _say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def diarize(wav: Path, token: str) -> tuple[list[Turn], dict[str, list[float]]]:
    """Turns, and each speaker's embedding centroid for merge_similar."""
    # torch 2.6 and later load checkpoints weights-only by default, and
    # pyannote 3.x's checkpoints store objects that loader refuses. They come
    # from pyannote's own gated repo, so allow the full load.
    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    import torch
    from pyannote.audio import Pipeline

    pipe = Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=token)
    if pipe is None:
        raise SystemExit(f"Could not load {DIARIZATION_MODEL}: accept its terms on huggingface.co with the token's account.")
    pipe.to(torch.device(_device()))
    annotation, embeddings = pipe(str(wav), return_embeddings=True)
    turns = [(int(t.start * 1000), int(t.end * 1000), str(who)) for t, _, who in annotation.itertracks(yield_label=True)]
    # Rows follow annotation.labels(), the order pyannote documents.
    centroids = {str(who): [float(x) for x in row] for who, row in zip(annotation.labels(), embeddings)}
    return turns, centroids


def read_wav(wav: Path):
    """The 16 kHz mono 16-bit wav from extract_audio as float32 samples in
    [-1, 1], the form faster-whisper takes. Handing faster-whisper a path
    makes it decode with PyAV, whose newer releases reject an argument
    faster-whisper passes, so the sync check never ran."""
    import numpy as np

    with wave.open(str(wav), "rb") as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2 or f.getframerate() != 16000:
            raise ValueError(f"{wav} is not 16 kHz mono 16-bit audio")
        frames = f.readframes(f.getnframes())
    # One float32 copy, scaled in place: a feature film is ~420 MB of
    # samples, and a second copy for the division would double that.
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    del frames
    samples /= 32768.0
    return samples


# The sync check transcribes this many windows of this many seconds, spread
# over the film, not the whole film: a file's offset is the same all
# through, and a whole feature film took about 2.5 minutes on a GPU.
SYNC_WINDOWS = 5
SYNC_WINDOW_S = 180
SAMPLE_RATE = 16000
# Speech starts this close to a window's edge are left out: a sentence cut
# by the edge looks like one starting there, and a cue just outside the
# window would match it.
EDGE_MS = 2000


def sync_windows(n_samples: int, count: int = SYNC_WINDOWS, seconds: int = SYNC_WINDOW_S) -> list[tuple[int, int]]:
    """Sample ranges to transcribe: `count` windows centred at even steps
    through the audio, or the whole audio when the windows would cover most
    of it anyway."""
    size = seconds * SAMPLE_RATE
    if count * size * 2 >= n_samples:
        return [(0, n_samples)]
    out = []
    for i in range(count):
        mid = n_samples * (2 * i + 1) // (2 * count)
        out.append((mid - size // 2, mid + size // 2))
    return out


def speech_starts(wav: Path) -> list[int]:
    from faster_whisper import WhisperModel

    audio = read_wav(wav)
    windows = sync_windows(len(audio))

    def transcribe(device: str) -> list[int]:
        model = WhisperModel(WHISPER_MODEL, device=device, compute_type="float16" if device == "cuda" else "int8")
        starts = []
        for a, b in windows:
            part = audio if (a, b) == (0, len(audio)) else audio[a:b]
            segments, _ = model.transcribe(part, vad_filter=True, word_timestamps=False)
            # segments is lazy: CUDA library errors surface here, inside the try.
            at = [int(s.start * 1000) for s in segments]
            if len(windows) > 1:
                end_ms = (b - a) * 1000 // SAMPLE_RATE
                at = [ms for ms in at if EDGE_MS <= ms <= end_ms - EDGE_MS]
            starts += [a * 1000 // SAMPLE_RATE + ms for ms in at]
        return starts

    device = _device()
    if device == "cpu":
        return transcribe("cpu")
    try:
        return transcribe(device)
    except Exception as e:
        # Only a GPU library problem is worth a second, slower try on the CPU.
        if not any(w in str(e).lower() for w in CUDA_WORDS):
            raise
        _say(f"GPU transcription failed ({type(e).__name__}); trying the CPU")
        return transcribe("cpu")


# Words in a GPU library error. "float16": older cards (GTX 10 series and
# before) refuse the float16 compute type, and the CPU uses int8 instead.
CUDA_WORDS = ("cuda", "cudnn", "cublas", "nvrtc", "float16")

DEFAULT_CONFIG = Path.home() / ".config" / "turkish-subtitles"


def run(video: Path, work: Path, config: Path | None, sync_check: bool) -> dict:
    token = load_token(config)
    if not token:
        where = config or DEFAULT_CONFIG
        return {"skipped": "token missing", "fix": f'uv run "{Path(__file__).resolve()}" setup --config "{where}"'}
    cues, _ = srt.parse(work / "timing.srt")
    speakers_file = work / "speakers.json"
    speakers = json.loads(speakers_file.read_text(encoding="utf-8")) if speakers_file.exists() else {}
    with tempfile.TemporaryDirectory() as tmp:
        _say("speakers: extracting the audio")
        wav = extract_audio(video, Path(tmp) / "audio.wav")
        _say("speakers: finding who speaks when (a few minutes on a GPU, about the film's length on a CPU)")
        turns, centroids = diarize(wav, token)
        found = len({who for _, _, who in turns})
        turns = merge_similar(turns, centroids)
        voices = assign_voices(cues, turns)
        # A voice that mixes several characters gives no hint at all.
        mixed = mixed_voices(speakers, voices)
        voices = {n: v for n, v in voices.items() if v not in mixed}
        # Save the voices first: the sync check is optional and must never
        # cost the diarization.
        speakers_file.write_text(json.dumps(merge_voices(speakers, voices), ensure_ascii=False, indent=1), encoding="utf-8")
        sync = None
        if sync_check:
            _say("speakers: voices saved; checking sync with the audio")
            try:
                sync = sync_offset(cues, speech_starts(wav))
            except Exception as e:  # report, keep the voices
                sync = {
                    "matched_cues": 0,
                    "speech_starts": 0,
                    "runner_up_matched": 0,
                    "median_offset_ms": None,
                    "verdict": f"sync check failed: {type(e).__name__}: {e}",
                }
    counts: dict[str, int] = {}
    for v in voices.values():
        counts[v] = counts.get(v, 0) + 1
    return {
        "cues": len(cues),
        "cues_with_voice": len(voices),
        "voices_before_merge": found,
        "voices": dict(sorted(counts.items(), key=lambda kv: int(kv[0][1:]))),
        "voices_dropped": len(mixed),
        "mixed_voices": mixed,
        "sync": sync,
    }


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--config", type=result.path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--video", type=result.path, required=True)
    r.add_argument("--work", type=result.path, required=True)
    r.add_argument("--config", type=result.path, default=DEFAULT_CONFIG)
    r.add_argument("--no-sync-check", action="store_true")
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "setup":
        setup(a.config)
    else:
        out = run(a.video, a.work, a.config, not a.no_sync_check)
        result.emit(out, a.result)
        if out.get("skipped") == "token missing":
            raise SystemExit(TOKEN_MISSING)


if __name__ == "__main__":
    main()
