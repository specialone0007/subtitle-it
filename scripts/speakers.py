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
and gives each cue in W/timing.srt the voice that overlaps it most
(V1, V2, ... in order of first appearance). It writes `voice` into
W/speakers.json and keeps every `label` and `name` already there. Unless
--no-sync-check is given, faster-whisper finds where speech starts and the
script reports how far the subtitles sit from the audio. The first run
downloads the models (a few GB). Without a token it prints
{"skipped": "token missing"} and exits with code 3.
"""

from __future__ import annotations

import argparse
import getpass
import json
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
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(creds, indent=1), encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    tmp.replace(p)


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


def assign_voices(cues: list[srt.Cue], turns: list[Turn], min_share: float = MIN_SHARE) -> dict[int, str]:
    """Give each cue the speaker that overlaps it most, when that speaker
    covers at least `min_share` of the cue. Speakers are renamed V1, V2, ...
    in the order they first win a cue."""
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
        if not overlap or c.duration <= 0:
            continue
        who, ov = max(overlap.items(), key=lambda kv: (kv[1], kv[0]))
        if ov / c.duration < min_share:
            continue
        names.setdefault(who, f"V{len(names) + 1}")
        out[c.n] = names[who]
    return out


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


def sync_offset(cues: list[srt.Cue], speech_starts: list[int], window: int = 2000) -> dict:
    """Median gap between each cue start and the nearest speech start within
    `window` ms. Positive: the subtitles come late."""
    starts = sorted(speech_starts)
    diffs = []
    k = 0
    for c in cues:
        while k + 1 < len(starts) and starts[k + 1] <= c.start:
            k += 1
        near = [s for s in starts[max(0, k - 1) : k + 2] if abs(c.start - s) <= window]
        if near:
            diffs.append(c.start - min(near, key=lambda s: abs(c.start - s)))
    if not diffs:
        return {"matched_cues": 0, "median_offset_ms": None, "verdict": "no speech matched the cues"}
    med = int(statistics.median(diffs))
    verdict = "in sync" if abs(med) <= 300 else f"subtitles are {abs(med)} ms {'late' if med > 0 else 'early'}"
    return {"matched_cues": len(diffs), "median_offset_ms": med, "verdict": verdict}


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


def diarize(wav: Path, token: str) -> list[Turn]:
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
    result = pipe(str(wav))
    return [(int(t.start * 1000), int(t.end * 1000), str(who)) for t, _, who in result.itertracks(yield_label=True)]


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


def speech_starts(wav: Path) -> list[int]:
    from faster_whisper import WhisperModel

    audio = read_wav(wav)

    def transcribe(device: str) -> list[int]:
        model = WhisperModel(WHISPER_MODEL, device=device, compute_type="float16" if device == "cuda" else "int8")
        segments, _ = model.transcribe(audio, vad_filter=True, word_timestamps=False)
        # segments is lazy: CUDA library errors surface here, inside the try.
        return [int(s.start * 1000) for s in segments]

    device = _device()
    if device == "cpu":
        return transcribe("cpu")
    try:
        return transcribe(device)
    except Exception:  # CUDA libraries missing: fall back to the CPU
        return transcribe("cpu")


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
        wav = extract_audio(video, Path(tmp) / "audio.wav")
        turns = diarize(wav, token)
        voices = assign_voices(cues, turns)
        # Save the voices first: the sync check is optional and must never
        # cost the diarization.
        speakers_file.write_text(json.dumps(merge_voices(speakers, voices), ensure_ascii=False, indent=1), encoding="utf-8")
        sync = None
        if sync_check:
            try:
                sync = sync_offset(cues, speech_starts(wav))
            except Exception as e:  # report, keep the voices
                sync = {"matched_cues": 0, "median_offset_ms": None, "verdict": f"sync check failed: {type(e).__name__}: {e}"}
    counts: dict[str, int] = {}
    for v in voices.values():
        counts[v] = counts.get(v, 0) + 1
    return {
        "cues": len(cues),
        "cues_with_voice": len(voices),
        "voices": dict(sorted(counts.items(), key=lambda kv: int(kv[0][1:]))),
        "sync": sync,
    }


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--config", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--video", type=Path, required=True)
    r.add_argument("--work", type=Path, required=True)
    r.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    r.add_argument("--no-sync-check", action="store_true")
    result.add_argument(p)
    a = p.parse_args(argv)
    result.clear(a.result)
    if a.cmd == "setup":
        setup(a.config)
    else:
        out = run(a.video, a.work, a.config, not a.no_sync_check)
        result.emit(out, a.result)
        if out.get("skipped") == "token missing":
            raise SystemExit(TOKEN_MISSING)


if __name__ == "__main__":
    main()
