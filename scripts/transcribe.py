# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "charset-normalizer>=3.3",
#   "faster-whisper>=1.1",
#   "numpy>=1.24",
#   "torch>=2.4,<2.9",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cu124"
# url = "https://download.pytorch.org/whl/cu124"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cu124", marker = "sys_platform != 'darwin'" }
# ///
"""Subtitles made from the film's own audio: the last resort when no usable
subtitle file exists on disk or on OpenSubtitles.

    uv run transcribe.py run  --video V --work W [--language xx] [--model NAME]
    uv run transcribe.py sync --video V --timing T [--language xx] [--model NAME]

`run` extracts the audio with ffmpeg and transcribes it with faster-whisper
(default model large-v3-turbo) on the GPU when there is one, else on the
CPU. Words are grouped into cues of at most two lines, split at pauses and
sentence ends, and written to W/sources/asr.<language>.srt in the film's
own language. --language skips the language guess; without it Whisper
detects the language from the first 30 seconds. The timing comes from the
audio itself, so no sync check is needed. Nothing leaves the machine except
the one-time model download from Hugging Face, which needs no token.
Progress goes to stderr.

`sync` measures how far the timing file T sits from the film's speech. It
transcribes SYNC_WINDOWS short stretches spread over the film (about a
minute on a GPU), finds each timing cue whose first words the transcript
says nearby, and takes the gap between the cue's start and the moment
those words are spoken. Matching words, not mere speech starts, keeps a
neighbouring line from passing for the right one, so a sub-second offset
shows plainly in dense talk. It prints the median gap less Whisper's lead
(`offset_ms`, positive when the subtitles come late), how widely the gaps
spread, the number of lines matched, the offset per stretch (one that
changes means a different cut or drift, which no single shift fixes), a
verdict, and `shift_ms`, the `srt.py shift` amount that puts the file on
the speech (0 unless the verdict says the subtitles are late or early).
--language is the timing file's language; the check needs the film's
speech to be in that language.

PyTorch is listed only so that its CUDA libraries are on hand for the GPU;
it is the same download the audio hints use.
"""

from __future__ import annotations

import argparse
import bisect
import re
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import sources  # noqa: E402
import speakers  # noqa: E402
import srt  # noqa: E402

MODEL = "large-v3-turbo"
LINE = 42  # characters per line
MAX_GAP = 1.0  # seconds of silence that end a cue
MAX_DURATION = 7.0  # seconds a cue may stay on screen
SENTENCE_MIN = 30  # a sentence end closes the cue once it holds this many characters
MIN_DURATION = 700  # ms, so a short word stays readable
MAX_REPEATS = 2  # identical cues in a row kept before the rest count as a Whisper loop
SENTENCE_END = re.compile(r"[.!?…]['\"»”)]?$")


@dataclass
class Word:
    start: float  # seconds
    end: float
    text: str


def fits(text: str) -> bool:
    """True when text fits in two LINE-character lines: one line, or a
    space that leaves both halves short enough."""
    if len(text) <= LINE:
        return True
    return any(ch == " " and i <= LINE and len(text) - i - 1 <= LINE for i, ch in enumerate(text))


def words_to_cues(words: list[Word]) -> list[tuple[int, int, str]]:
    """Group words into (start_ms, end_ms, text) cues. A cue closes at a
    pause over MAX_GAP, before it would no longer fit in two LINE-character
    lines or pass MAX_DURATION, and at a sentence end once it holds
    SENTENCE_MIN characters."""
    cues: list[tuple[int, int, str]] = []
    cur: list[Word] = []

    def close() -> None:
        if cur:
            text = " ".join(w.text for w in cur)
            cues.append((round(cur[0].start * 1000), round(cur[-1].end * 1000), text))
            cur.clear()

    for w in words:
        w = Word(w.start, w.end, w.text.strip())
        if not w.text:
            continue
        if cur:
            text = " ".join(x.text for x in cur)
            if (
                w.start - cur[-1].end > MAX_GAP
                or not fits(text + " " + w.text)
                or w.end - cur[0].start > MAX_DURATION
                or (SENTENCE_END.search(cur[-1].text) and len(text) >= SENTENCE_MIN)
            ):
                close()
        cur.append(w)
    close()
    return cues


def wrap(text: str) -> list[str]:
    """One line when it fits in LINE characters, else two (`srt.wrap`)."""
    return srt.wrap(text, LINE)


def drop_repeats(cues: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Keep at most MAX_REPEATS identical cues in a row. Whisper sometimes
    loops on one phrase over music or silence; a real "No. No." survives."""
    kept: list[tuple[int, int, str]] = []
    run = 0
    for c in cues:
        same = bool(kept) and c[2].casefold() == kept[-1][2].casefold()
        run = run + 1 if same else 1
        if run <= MAX_REPEATS:
            kept.append(c)
    return kept


def to_srt_cues(cues: list[tuple[int, int, str]]) -> list[srt.Cue]:
    """Number the cues and give a short one MIN_DURATION on screen, never
    past the start of the next cue."""
    out = []
    for i, (start, end, text) in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < len(cues) else None
        end = max(end, start + MIN_DURATION)
        if nxt is not None:
            end = max(min(end, nxt - 1), start + 1)
        out.append(srt.Cue(i + 1, start, end, f"{srt.fmt_ms(start)} --> {srt.fmt_ms(end)}", wrap(text)))
    return out


# --- sync check: the timing file against the speech (pure logic, tested) ---

# A timing cue is matched by its first ANCHOR_WORDS words, said in that
# order by the transcript within SYNC_SEARCH_MS of the cue's start. An
# anchor the transcript says twice in that span, or that another cue near
# it also opens with ("I don't know"), is left out: it could pair the
# wrong line.
ANCHOR_WORDS = 3
SYNC_SEARCH_MS = 20_000
# At least SYNC_MIN_MATCHES lines must match, and SYNC_MIN_AGREEING of them
# must lie within SYNC_AGREE_MS of the median, or there is no one offset.
SYNC_MIN_MATCHES = 30
SYNC_MIN_AGREEING = 0.5
SYNC_AGREE_MS = 400
# Within this the file counts as in sync, as speakers.py judges it.
SYNC_MAX_IN_SYNC_MS = 300
# A stretch with this many matches gets an offset of its own; offsets
# further apart than SYNC_MAX_DRIFT_MS mean the offset changes through the
# film. A stretch's offset is noisy: on two films in sync, stretches of 15
# to 40 matches lay up to 440 ms apart, and fewer matches strayed further.
# A different cut moves lines by seconds.
SYNC_WINDOW_MIN_MATCHES = 15
SYNC_MAX_DRIFT_MS = 700
# Whisper's word starts come a little before a subtitle that starts with
# the voice. On two films whose timing tracks are in sync, Sinners (2025)
# and Project Hail Mary (2026), the median gap was 158 and 164 ms. This
# much is taken off the median gap before it is judged, so the shift is a
# little under the raw gap.
WHISPER_LEAD_MS = 150
WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")


def tokens(text: str) -> list[str]:
    """Lowercase words without punctuation; curly apostrophes made straight."""
    return WORD_RE.findall(text.replace("’", "'").replace("‘", "'").casefold())


def cue_words(c: srt.Cue) -> list[str]:
    """The words a cue says: sound descriptions, speaker labels, dialogue
    dashes and tags out. A song line counts as saying nothing."""
    text = srt.strip_tags(" ".join(srt.strip_hi(c.lines, True)[0]))
    if "♪" in text or "♫" in text:
        return []
    return tokens(text)


def text_offsets(cues: list[srt.Cue], words: list[Word]) -> list[tuple[int, int]]:
    """(cue start, cue start minus speech start), in ms, for each cue whose
    first ANCHOR_WORDS words the transcript says exactly once within
    SYNC_SEARCH_MS of the cue's start, and which no other cue that near
    opens with."""
    flat = sorted(((round(w.start * 1000), t) for w in words for t in tokens(w.text)), key=lambda x: x[0])
    times = [ms for ms, _ in flat]
    anchors = sorted((c.start, tuple(ws[:ANCHOR_WORDS])) for c in cues if len(ws := cue_words(c)) >= ANCHOR_WORDS)
    starts = [s for s, _ in anchors]
    out = []
    for start, anchor in anchors:
        lo, hi = bisect.bisect_left(starts, start - SYNC_SEARCH_MS), bisect.bisect_right(starts, start + SYNC_SEARCH_MS)
        if sum(1 for _, a in anchors[lo:hi] if a == anchor) > 1:
            continue
        lo, hi = bisect.bisect_left(times, start - SYNC_SEARCH_MS), bisect.bisect_right(times, start + SYNC_SEARCH_MS)
        found = [
            flat[i][0]
            for i in range(lo, min(hi, len(flat) - ANCHOR_WORDS + 1))
            if tuple(t for _, t in flat[i : i + ANCHOR_WORDS]) == anchor
        ]
        if len(found) == 1:
            out.append((start, start - found[0]))
    return out


def sync_verdict(pairs: list[tuple[int, int]], spans: list[tuple[int, int]] | None = None, lead_ms: int | None = None) -> dict:
    """Judge the gaps from text_offsets. `spans` are the stretches
    transcribed, as (start, end) ms of the film; each with enough matches
    gets an offset of its own, so one that changes shows. `offset_ms` is
    the median gap less `lead_ms`; positive means the subtitles come late.
    `shift_ms` is what `srt.py shift` should move the file by: minus the
    offset, to the nearest 10 ms, when the verdict says late or early,
    else 0."""
    lead_ms = WHISPER_LEAD_MS if lead_ms is None else lead_ms
    gaps = [g for _, g in pairs]
    out: dict = {
        "matches": len(gaps),
        "median_gap_ms": None,
        "offset_ms": None,
        "spread_ms": None,
        "agreeing": None,
        "windows": [],
        "shift_ms": 0,
    }
    if len(gaps) < SYNC_MIN_MATCHES:
        return {**out, "verdict": f"too little speech matched: {len(gaps)} lines (needs {SYNC_MIN_MATCHES})"}
    med = round(statistics.median(gaps))
    q = statistics.quantiles(gaps, n=4)
    agreeing = sum(1 for g in gaps if abs(g - med) <= SYNC_AGREE_MS) / len(gaps)
    offset = med - lead_ms
    out |= {"median_gap_ms": med, "offset_ms": offset, "spread_ms": round(q[2] - q[0]), "agreeing": round(agreeing, 3)}
    offsets = []
    for a, b in spans or []:
        inside = [g for s, g in pairs if a <= s < b]
        entry = {"start_ms": a, "matches": len(inside), "offset_ms": None}
        if len(inside) >= SYNC_WINDOW_MIN_MATCHES:
            entry["offset_ms"] = round(statistics.median(inside)) - lead_ms
            offsets.append(entry["offset_ms"])
        out["windows"].append(entry)
    if agreeing < SYNC_MIN_AGREEING:
        return {**out, "verdict": f"no steady offset: {round(agreeing * 100)}% of {len(gaps)} lines lie near the median"}
    if len(offsets) >= 2 and max(offsets) - min(offsets) > SYNC_MAX_DRIFT_MS:
        verdict = f"offset changes through the film ({min(offsets)} to {max(offsets)} ms): a different cut or drift"
        return {**out, "verdict": verdict}
    if abs(offset) <= SYNC_MAX_IN_SYNC_MS:
        return {**out, "verdict": "in sync"}
    shift = -round(offset / 10) * 10
    return {**out, "shift_ms": shift, "verdict": f"subtitles are {abs(offset)} ms {'late' if offset > 0 else 'early'}"}


T = TypeVar("T")


def on_gpu_or_cpu(attempt: Callable[[str], T]) -> tuple[T, str]:
    """attempt(device) on the GPU when there is one, and on the CPU when the
    GPU's libraries fail; any other error is raised. Returns the result and
    the device used."""
    if speakers._device() == "cuda":
        try:
            return attempt("cuda"), "cuda"
        except Exception as e:
            if not any(w in str(e).lower() for w in speakers.CUDA_WORDS):
                raise
            speakers._say(f"GPU transcription failed ({type(e).__name__}); trying the CPU")
    return attempt("cpu"), "cpu"


def transcribe(wav: Path, model_name: str, language: str | None) -> tuple[list[Word], str, float, str]:
    from faster_whisper import WhisperModel

    audio = speakers.read_wav(wav)

    def attempt(device: str) -> tuple[list[Word], str, float]:
        model = WhisperModel(model_name, device=device, compute_type="float16" if device == "cuda" else "int8")
        segments, info = model.transcribe(
            audio,
            language=language,
            vad_filter=True,
            word_timestamps=True,
            # Each window starts fresh, so one misheard line cannot drag
            # the next ones into a loop.
            condition_on_previous_text=False,
        )
        # segments is lazy: CUDA library errors surface here, inside the try.
        words = [Word(w.start, w.end, w.word) for s in segments for w in (s.words or [])]
        return words, info.language, info.language_probability

    found, device = on_gpu_or_cpu(attempt)
    return (*found, device)


def run(video: Path, work: Path, language: str | None, model_name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        speakers._say("transcribe: extracting the audio")
        wav = speakers.extract_audio(video, Path(tmp) / "audio.wav")
        speakers._say("transcribe: transcribing (a few minutes on a GPU, about the film's length or more on a CPU)")
        words, lang, prob, device = transcribe(wav, model_name, language)
    cues = to_srt_cues(drop_repeats(words_to_cues(words)))
    dest = work / "sources" / f"asr.{lang}.srt"
    srt.write(dest, cues)
    return {
        "path": str(dest),
        "language": lang,
        "language_probability": round(prob, 3),
        "language_given": language is not None,
        "cues": len(cues),
        "words": len(words),
        "model": model_name,
        "device": device,
    }


# The sync check transcribes this many stretches of this many seconds.
SYNC_WINDOWS = 6
SYNC_WINDOW_S = 180
# Words this close to a stretch's cut edge are left out: a word cut by the
# edge gets a wrong start.
EDGE_MS = 2000


def sync_spans(duration_ms: int, count: int = SYNC_WINDOWS, seconds: int = SYNC_WINDOW_S) -> list[tuple[int, int]]:
    """(start, end) ms of `count` stretches centred at even steps through
    the film, or the whole film when they would cover most of it."""
    size = seconds * 1000
    if count * size * 2 >= duration_ms:
        return [(0, duration_ms)]
    mids = [duration_ms * (2 * i + 1) // (2 * count) for i in range(count)]
    return [(mid - size // 2, mid + size // 2) for mid in mids]


def _cut(video: Path, a: int, b: int, dest: Path) -> Path:
    """The audio from a to b ms as 16 kHz mono wav. Seeking before -i is
    fast, and exact since the audio is decoded."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{a / 1000:.3f}", "-t", f"{(b - a) / 1000:.3f}", "-i", str(video)]
    subprocess.run([*cmd, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)], check=True)
    return dest


def window_words(video: Path, spans: list[tuple[int, int]], model_name: str, language: str | None) -> tuple[list[Word], str]:
    """The words said in each span, in film time, and the device used.
    With several spans, words near a span's cut edges are left out."""
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmp:
        audio = []
        for i, (a, b) in enumerate(spans):
            speakers._say(f"sync: cutting stretch {i + 1} of {len(spans)}")
            audio.append(speakers.read_wav(_cut(video, a, b, Path(tmp) / f"w{i}.wav")))

    def attempt(device: str) -> list[Word]:
        model = WhisperModel(model_name, device=device, compute_type="float16" if device == "cuda" else "int8")
        out = []
        for (a, b), part in zip(spans, audio):
            segments, _ = model.transcribe(
                part, language=language, vad_filter=True, word_timestamps=True, condition_on_previous_text=False
            )
            # segments is lazy: CUDA library errors surface here, inside the try.
            for s in segments:
                for w in s.words or []:
                    if len(spans) == 1 or EDGE_MS <= w.start * 1000 <= b - a - EDGE_MS:
                        out.append(Word(a / 1000 + w.start, a / 1000 + w.end, w.word))
        return out

    return on_gpu_or_cpu(attempt)


def sync(video: Path, timing: Path, language: str | None, model_name: str) -> dict:
    cues, _ = srt.parse(timing)
    duration = sources.probe(video)["duration_ms"] or max((c.end for c in cues), default=0)
    spans = sync_spans(duration)
    speakers._say(f"sync: transcribing {len(spans)} stretches (about a minute on a GPU, several on a CPU)")
    words, device = window_words(video, spans, model_name, language)
    out = sync_verdict(text_offsets(cues, words), spans)
    return {"timing": str(timing), **out, "words": len(words), "model": model_name, "device": device}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--video", type=result.path, required=True)
    r.add_argument("--work", type=result.path, required=True)
    r.add_argument("--language", help="the film's original language as a two-letter code; skips the guess")
    r.add_argument("--model", default=MODEL, help=f"faster-whisper model name (default {MODEL})")
    y = sub.add_parser("sync")
    y.add_argument("--video", type=result.path, required=True)
    y.add_argument("--timing", type=result.path, required=True)
    y.add_argument("--language", help="the timing file's language as a two-letter code")
    y.add_argument("--model", default=MODEL, help=f"faster-whisper model name (default {MODEL})")
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "sync":
        result.emit(sync(a.video, a.timing, a.language, a.model), a.result)
    else:
        result.emit(run(a.video, a.work, a.language, a.model), a.result)


if __name__ == "__main__":
    main()
