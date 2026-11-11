# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Find the film and its candidate source subtitles on disk.

    uv run sources.py find     --query "Anatomy of a Fall" --dirs D1 [D2 ...]
    uv run sources.py local    --video V --work W
    uv run sources.py validate --file F [--duration-ms N]

`find` lists video and subtitle files whose names match the query.
`local` probes the video with ffprobe, extracts every text subtitle track
into W/sources/, lists subtitle files next to the video, and validates each
candidate. Image tracks (PGS, VobSub, DVB) are listed but not extracted.
Needs ffmpeg and ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import srt  # noqa: E402

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".wmv"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt"}
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
IMAGE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
SKIP_WORDS = {"trailer", "sample", "teaser", "featurette"}

# Common language codes seen in file names and track tags -> ISO 639-1
LANG = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "fr": "fr",
    "fre": "fr",
    "fra": "fr",
    "french": "fr",
    "de": "de",
    "ger": "de",
    "deu": "de",
    "german": "de",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "it": "it",
    "ita": "it",
    "italian": "it",
    "pt": "pt",
    "por": "pt",
    "portuguese": "pt",
    "tr": "tr",
    "tur": "tr",
    "turkish": "tr",
    "ja": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "ko": "ko",
    "kor": "ko",
    "korean": "ko",
    "zh": "zh",
    "chi": "zh",
    "zho": "zh",
    "chinese": "zh",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "ar": "ar",
    "ara": "ar",
    "arabic": "ar",
    "nl": "nl",
    "dut": "nl",
    "nld": "nl",
    "dutch": "nl",
    "sv": "sv",
    "swe": "sv",
    "da": "da",
    "dan": "da",
    "no": "no",
    "nor": "no",
    "pl": "pl",
    "pol": "pl",
    "fa": "fa",
    "per": "fa",
    "fas": "fa",
    "hi": "hi",
    "hin": "hi",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return norm(s).replace(" ", "-")[:60] or "film"


def find(query: str, dirs: list[Path]) -> list[dict]:
    words = norm(query).split()
    hits = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            ext = p.suffix.lower()
            if ext not in VIDEO_EXT | SUB_EXT or not p.is_file():
                continue
            name = norm(str(p.relative_to(d)))
            if all(w in name.split() or w in name for w in words):
                hits.append(
                    {
                        "path": str(p),
                        "kind": "video" if ext in VIDEO_EXT else "subtitle",
                        "size_mb": round(p.stat().st_size / 1e6, 1),
                        "looks_like_extra": any(w in name.split() for w in SKIP_WORDS),
                    }
                )
    hits.sort(key=lambda h: (h["kind"] != "video", h["looks_like_extra"], -h["size_mb"]))
    return hits


def _run(cmd: list[str]) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        raise SystemExit(f"{cmd[0]} not found on PATH; install ffmpeg (see README)")
    return subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def probe(video: Path) -> dict:
    data = json.loads(_run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)]))
    duration = float(data.get("format", {}).get("duration") or 0)
    tracks = []
    sub_index = 0
    for s in data.get("streams", []):
        if s.get("codec_type") != "subtitle":
            continue
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        disp = s.get("disposition") or {}
        title = tags.get("title", "")
        lang = LANG.get(tags.get("language", "").lower(), tags.get("language", "und").lower())
        tracks.append(
            {
                "sub_index": sub_index,
                "codec": s.get("codec_name"),
                "text": s.get("codec_name") in TEXT_CODECS,
                "language": lang,
                "title": title,
                "forced": bool(disp.get("forced")) or "forced" in title.lower(),
                "hearing_impaired": bool(disp.get("hearing_impaired")) or bool(re.search(r"\b(sdh|hi|cc)\b", title.lower())),
            }
        )
        sub_index += 1
    return {"duration_ms": int(duration * 1000), "tracks": tracks}


def sidecar_language(sub: Path, video: Path) -> str:
    rest = sub.name[len(video.stem) :] if sub.name.startswith(video.stem) else sub.stem
    for part in reversed(norm(rest).split()):
        if part in LANG:
            return LANG[part]
    return "und"


def validate(path: Path, duration_ms: int | None) -> dict:
    cues, enc = srt.parse(path)
    issues = []
    if len(cues) < 50:
        issues.append(f"only {len(cues)} cues")
    if cues and duration_ms and cues[-1].end > duration_ms + 30_000:
        issues.append(f"last cue ends at {srt.fmt_ms(cues[-1].end)}, after the video ends ({srt.fmt_ms(duration_ms)})")
    if cues and duration_ms and cues[-1].end < duration_ms * 0.6:
        issues.append(f"last cue at {srt.fmt_ms(cues[-1].end)} covers under 60% of the video; may be partial or forced-only")
    overlaps = sum(1 for a, b in zip(cues, cues[1:]) if b.start < a.start)
    if overlaps:
        issues.append(f"{overlaps} cues out of time order")
    mid = len(cues) // 2
    return {
        "file": str(path),
        "encoding": enc,
        "cues": len(cues),
        "last_end": srt.fmt_ms(cues[-1].end) if cues else None,
        "issues": issues,
        "sample": [c.text for c in cues[mid : mid + 4]],
    }


def to_srt(src: Path, dest: Path) -> Path:
    """Convert .ass/.vtt to .srt with ffmpeg; copy .srt unchanged."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".srt":
        shutil.copyfile(src, dest)
    else:
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:s", "srt", str(dest)])
    return dest


def local(video: Path, work: Path) -> dict:
    info = probe(video)
    out = work / "sources"
    out.mkdir(parents=True, exist_ok=True)
    candidates = []
    for t in info["tracks"]:
        if not t["text"]:
            candidates.append({**t, "source": "built-in track", "confidence": "skipped: image subtitles"})
            continue
        dest = out / f"track{t['sub_index']}.{t['language']}.srt"
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", f"0:s:{t['sub_index']}", "-c:s", "srt", str(dest)])
        candidates.append(
            {
                **t,
                "source": "built-in track",
                "confidence": "certain",
                "path": str(dest),
                "check": validate(dest, info["duration_ms"]),
            }
        )
    for p in sorted(video.parent.iterdir()):
        if p.suffix.lower() in SUB_EXT and p.is_file() and norm(p.name).startswith(norm(video.stem)):
            lang = sidecar_language(p, video)
            name = p.name.lower()
            if ".tr." in name and lang == "tr":
                candidates.append(
                    {
                        "source": "file next to video",
                        "language": "tr",
                        "path": str(p),
                        "confidence": "existing Turkish file, not a source",
                    }
                )
                continue
            dest = to_srt(p, out / f"sidecar.{slug(p.stem)}.srt")
            candidates.append(
                {
                    "source": "file next to video",
                    "language": lang,
                    "hearing_impaired": bool(re.search(r"\b(sdh|hi|cc)\b", norm(p.stem))),
                    "forced": "forced" in name,
                    "confidence": "likely",
                    "original": str(p),
                    "path": str(dest),
                    "check": validate(dest, info["duration_ms"]),
                }
            )
    return {"video": str(video), "duration_ms": info["duration_ms"], "candidates": candidates}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--query", required=True)
    f.add_argument("--dirs", type=Path, nargs="+", required=True)
    lo = sub.add_parser("local")
    lo.add_argument("--video", type=Path, required=True)
    lo.add_argument("--work", type=Path, required=True)
    v = sub.add_parser("validate")
    v.add_argument("--file", type=Path, required=True)
    v.add_argument("--duration-ms", type=int)
    s = sub.add_parser("slug")
    s.add_argument("name")
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "find":
        out = find(a.query, a.dirs)
    elif a.cmd == "local":
        out = local(a.video, a.work)
    elif a.cmd == "validate":
        out = validate(a.file, a.duration_ms)
    else:
        out = {"slug": slug(a.name)}
    result.emit(out, a.result)


if __name__ == "__main__":
    main()
