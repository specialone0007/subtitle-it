# /// script
# requires-python = ">=3.11"
# dependencies = ["charset-normalizer>=3.3"]
# ///
"""Find the film and its candidate source subtitles on disk.

    uv run sources.py find     --query "Anatomy of a Fall" --dirs D1 [D2 ...]
    uv run sources.py local    --video V --work W
    uv run sources.py validate --file F [--duration-ms N]
    uv run sources.py remember --file V --prefs CONFIG/preferences.md

`find` lists video and subtitle files whose names match the query, and
names any listed folder that is not there (an unplugged drive, say).
`remember` adds the folder of a film given by path to the media folders in
preferences.md, unless a listed folder already holds it or the folder is a
drive root or the home folder.
`local` probes the video with ffprobe, extracts every text subtitle track
into W/sources/, lists subtitle files next to the video, and validates each
candidate. It also reads subtitle files in a Subs or Subtitles folder beside
the video, up to two levels down. Image tracks (PGS, VobSub, DVB) are listed
but not extracted.
Needs ffmpeg and ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
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


def find(query: str, dirs: list[Path]) -> dict:
    """Matching files, biggest video first, and the folders that were not there to search."""
    words = norm(query).split()
    hits = []
    missing = []
    for listed in dirs:
        d = listed.expanduser()
        if not d.is_dir():
            missing.append(str(listed))
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
    return {"matches": hits, "missing_folders": missing}


MEDIA_HEADING = "## Media folders"


def media_folders(prefs: Path) -> list[str]:
    """The folders listed under "## Media folders" in preferences.md."""
    if not prefs.is_file():
        return []
    folders, inside = [], False
    for line in prefs.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == MEDIA_HEADING
        elif inside and line.startswith("-") and line[1:].strip():
            folders.append(line[1:].strip())
    return folders


_key = srt.path_key


def _inside(path: Path, folder: Path) -> bool:
    child, parent = _key(path), _key(folder).rstrip("\\/")
    return child == parent or child.startswith(parent + os.sep)


def _too_broad(folder: Path) -> bool:
    """A drive root or the home folder: searching all of it would be slow on every run."""
    return folder.parent == folder or _key(folder) == _key(Path.home())


def folder_to_remember(file: Path) -> Path:
    """The folder to add for a film found outside the media folders.

    A film in its own folder ("The Quiet Hour (2019)/The.Quiet.Hour.2019.mkv")
    gives that folder's parent, where the next film probably sits too. A film
    loose in a folder ("Films/Anatomy.of.a.Fall.2023.mkv") gives that folder.
    """
    film_dir = file.resolve().parent
    title = [w for w in norm(film_dir.name).split() if not re.fullmatch(r"(19|20)\d\d", w)]
    stem = norm(file.stem).split()
    if title and stem[: len(title)] == title and not _too_broad(film_dir.parent):
        return film_dir.parent
    return film_dir


def remember(file: Path, prefs: Path) -> dict:
    """Add the film's folder to "## Media folders" unless a listed folder already holds it.

    A film lying loose at a drive root or in the home folder adds nothing:
    searching all of that on every run would be slow. The result names the
    folder under `too_broad` instead.
    """
    listed = media_folders(prefs)
    for f in listed:
        if _inside(file, Path(f)):
            return {"added": None, "covered_by": f, "too_broad": None}
    folder = folder_to_remember(file)
    if _too_broad(folder):
        return {"added": None, "covered_by": None, "too_broad": str(folder)}
    lines = prefs.read_text(encoding="utf-8").splitlines() if prefs.is_file() else []
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == MEDIA_HEADING)
    except StopIteration:
        lines += ["", MEDIA_HEADING, ""]
        start = len(lines) - 2
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    bullets = [i for i in range(start + 1, end) if lines[i].startswith("-")]
    entry = f"- {folder}"
    blank = [i for i in bullets if not lines[i][1:].strip()]
    if blank:
        lines[blank[0]] = entry
    elif bullets:
        lines.insert(bullets[-1] + 1, entry)
    else:
        lines.insert(start + 1, entry)
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"added": str(folder), "covered_by": None, "too_broad": None}


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
        # The tag goes into a file name: keep only a plain language code.
        if not re.fullmatch(r"[a-z]{2,3}", lang):
            lang = "und"
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
    parts = norm(rest).split()
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] not in LANG:
            continue
        # "hi" is also the hearing-impaired tag: English.HI.srt is English.
        if parts[i] == "hi" and any(q in LANG for q in parts[:i]):
            continue
        return LANG[parts[i]]
    return "und"


def validate(path: Path, duration_ms: int | None) -> dict:
    repairs: list[str] = []
    cues, enc = srt.parse(path, repairs)
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
    hi = srt.hearing_impaired(cues)
    return {
        "file": str(path),
        "encoding": enc,
        "cues": len(cues),
        "last_end": srt.fmt_ms(cues[-1].end) if cues else None,
        # Read from the text, since names and track tags often leave it out.
        "hearing_impaired": hi["hearing_impaired"],
        "cues_with_tags_or_labels": hi["cues_with_tags_or_labels"],
        "issues": issues,
        # Faults the parser put right (a missing or a stray blank line): the
        # file is read as meant, so they are not issues and it still passes.
        "repairs": len(repairs),
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


EARLIER_DELIVERY = "this plugin's earlier delivery, not a source"


def delivered_here(work: Path) -> set[str]:
    """Every file this work folder delivered, as a `_key`: today's name
    (`Film.srt`) and an older one (`Film.tr.srt`) kept in
    `earlier_deliveries`. A run takes none of them as a source or as a
    Turkish file to polish, as long as it still holds Turkish."""
    info_file = work / "delivered.json"
    if not info_file.exists():
        return set()
    return {_key(p) for p in srt.delivered_paths(json.loads(info_file.read_text(encoding="utf-8")))}


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
    delivered = delivered_here(work)
    for p in sorted(video.parent.iterdir()):
        if p.suffix.lower() in SUB_EXT and p.is_file() and norm(p.name).startswith(norm(video.stem)):
            lang = sidecar_language(p, video)
            name = p.name.lower()
            # The path alone is not enough: the user may have put an
            # English file there since, which is a source like any other.
            if _key(p) in delivered and srt.looks_turkish(p):
                candidates.append(
                    {
                        "source": "file next to video",
                        "language": "tr",
                        "path": str(p),
                        "confidence": EARLIER_DELIVERY,
                    }
                )
                continue
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
            # `Film.srt` carries no language in its name: it may be a
            # Turkish file, this plugin's own delivery among them.
            if lang == "und" and srt.looks_turkish(dest):
                candidates.append(
                    {
                        "source": "file next to video",
                        "language": "tr",
                        "path": str(p),
                        "confidence": "existing Turkish file, not a source",
                    }
                )
                continue
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
    candidates += subfolder_candidates(video, out, info["duration_ms"])
    # A file full of sound descriptions and speaker labels is a
    # hearing-impaired one, whatever its name or track tag says.
    for c in candidates:
        if "check" in c:
            c["hearing_impaired"] = bool(c.get("hearing_impaired")) or c["check"]["hearing_impaired"]
    return {"video": str(video), "duration_ms": info["duration_ms"], "candidates": candidates}


SUB_DIRS = {"subs", "sub", "subtitles", "subtitle", "altyazi", "altyazilar"}

# "S01E02", "s1 e2" or "1x02" once a name has gone through norm().
EPISODE_RE = re.compile(r"(?:^| )(?:s(\d{1,2}) ?e(\d{1,3})|(\d{1,2})x(\d{2,3}))(?: |$)")


def episode(name: str) -> tuple[int, int] | None:
    m = EPISODE_RE.search(norm(name))
    if not m:
        return None
    season, ep = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return int(season), int(ep)


def folder_word(name: str) -> str:
    """A folder name folded for matching SUB_DIRS. The Turkish dotless ı has
    no ASCII form and norm() would drop it, so it becomes i first."""
    return norm(name.replace("ı", "i"))


def subfolder_files(video: Path) -> list[Path]:
    """Subtitle files in a Subs-like folder beside the video, up to two levels down.

    Such a folder often holds "Subs/English.srt" or numbered subtitle files in a subfolder,
    named after the language rather than the video. A file one level deeper is
    kept when that folder is named after this video, or when this is the only
    video in its folder, so another episode's subtitles are never picked up.
    For the same reason a file directly in the folder is skipped when it names
    another episode (S01E02 for a run on S01E01), or when its name starts with
    another video's name and not with this one's.
    """
    folder = video.parent
    videos = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT]
    only_video = len(videos) == 1
    stem = norm(video.stem)
    others = [norm(v.stem) for v in videos if v != video]
    this_episode = episode(video.stem)
    found = []
    for d in sorted(folder.iterdir()):
        if not d.is_dir() or folder_word(d.name) not in SUB_DIRS:
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in SUB_EXT:
                name = norm(p.stem)
                named = episode(p.stem)
                if this_episode and named and named != this_episode:
                    continue
                if not name.startswith(stem) and any(name.startswith(o) for o in others):
                    continue
                found.append(p)
            elif p.is_dir() and (only_video or norm(p.name).startswith(stem)):
                found += sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in SUB_EXT)
    return found


def subfolder_candidates(video: Path, out: Path, duration_ms: int) -> list[dict]:
    candidates = []
    for i, p in enumerate(subfolder_files(video), 1):
        lang = sidecar_language(p, video)
        if lang == "tr":
            candidates.append(
                {
                    "source": "file in a subtitle folder",
                    "language": "tr",
                    "path": str(p),
                    "confidence": "existing Turkish file, not a source",
                }
            )
            continue
        dest = to_srt(p, out / f"subfolder.{i}.{slug(p.stem)}.srt")
        candidates.append(
            {
                "source": "file in a subtitle folder",
                "language": lang,
                "hearing_impaired": bool(re.search(r"\b(sdh|hi|cc)\b", norm(p.stem))),
                "forced": "forced" in p.name.lower(),
                "confidence": "likely",
                "original": str(p),
                "path": str(dest),
                "check": validate(dest, duration_ms),
            }
        )
    return candidates


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--query", required=True)
    f.add_argument("--dirs", type=result.path, nargs="+", required=True)
    lo = sub.add_parser("local")
    lo.add_argument("--video", type=result.path, required=True)
    lo.add_argument("--work", type=result.path, required=True)
    v = sub.add_parser("validate")
    v.add_argument("--file", type=result.path, required=True)
    v.add_argument("--duration-ms", type=int)
    r = sub.add_parser("remember")
    r.add_argument("--file", type=result.path, required=True)
    r.add_argument("--prefs", type=result.path, required=True)
    s = sub.add_parser("slug")
    s.add_argument("name")
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "find":
        out = find(a.query, a.dirs)
    elif a.cmd == "local":
        out = local(a.video, a.work)
    elif a.cmd == "remember":
        out = remember(a.file, a.prefs)
    elif a.cmd == "validate":
        out = validate(a.file, a.duration_ms)
    else:
        out = {"slug": slug(a.name)}
    result.emit(out, a.result)


if __name__ == "__main__":
    main()
