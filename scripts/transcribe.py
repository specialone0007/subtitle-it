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

    uv run transcribe.py run --video V --work W [--language xx] [--model NAME]

`run` extracts the audio with ffmpeg and transcribes it with faster-whisper
(default model large-v3-turbo) on the GPU when there is one, else on the
CPU. Words are grouped into cues of at most two lines, split at pauses and
sentence ends, and written to W/sources/asr.<language>.srt in the film's
own language. --language skips the language guess; without it Whisper
detects the language from the first 30 seconds. The timing comes from the
audio itself, so no sync check is needed. Nothing leaves the machine except
the one-time model download from Hugging Face, which needs no token.
Progress goes to stderr.

PyTorch is listed only so that its CUDA libraries are on hand for the GPU;
it is the same download the audio hints use.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
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
    """One line when it fits in LINE characters, else two. The break goes
    after a sentence end, then after a comma, as long as both lines fit;
    otherwise at the space nearest the middle."""
    if len(text) <= LINE or " " not in text:
        return [text]
    mid = len(text) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    fits = [i for i in spaces if i <= LINE and len(text) - i - 1 <= LINE]
    for marks in (".!?…", ",;:"):
        after = [i for i in fits if text[i - 1] in marks]
        if after:
            cut = min(after, key=lambda i: abs(i - mid))
            break
    else:
        cut = min(spaces, key=lambda i: abs(i - mid))
    return [text[:cut], text[cut + 1 :]]


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

    device = speakers._device()
    if device == "cuda":
        try:
            return (*attempt("cuda"), "cuda")
        except Exception as e:
            if not any(w in str(e).lower() for w in speakers.CUDA_WORDS):
                raise
            speakers._say(f"GPU transcription failed ({type(e).__name__}); trying the CPU")
    return (*attempt("cpu"), "cpu")


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


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--video", type=result.path, required=True)
    r.add_argument("--work", type=result.path, required=True)
    r.add_argument("--language", help="the film's original language as a two-letter code; skips the guess")
    r.add_argument("--model", default=MODEL, help=f"faster-whisper model name (default {MODEL})")
    result.add_argument(p)
    a = result.parse(p, argv)
    result.emit(run(a.video, a.work, a.language, a.model), a.result)


if __name__ == "__main__":
    main()
