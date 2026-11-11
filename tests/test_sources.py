import json
from pathlib import Path

import opensubtitles
import sources


def test_find_matches_name_and_flags_extras(tmp_path: Path):
    d = tmp_path / "Movies" / "Anatomy of a Fall (2023)"
    d.mkdir(parents=True)
    (d / "Anatomy of a Fall (2023).mkv").write_bytes(b"x" * 2000)
    (d / "Anatomy of a Fall Trailer.mp4").write_bytes(b"x" * 10)
    (d / "notes.txt").write_text("x")
    (tmp_path / "Other.Film.mkv").write_bytes(b"x")
    hits = sources.find("anatomy of a fall", [tmp_path])
    assert [Path(h["path"]).name for h in hits] == ["Anatomy of a Fall (2023).mkv", "Anatomy of a Fall Trailer.mp4"]
    assert hits[1]["looks_like_extra"]


def test_sidecar_language():
    v = Path("Anatomy of a Fall.mkv")
    assert sources.sidecar_language(Path("Anatomy of a Fall.en.srt"), v) == "en"
    assert sources.sidecar_language(Path("Anatomy of a Fall.French.forced.srt"), v) == "fr"
    assert sources.sidecar_language(Path("Anatomy of a Fall.srt"), v) == "und"


def test_slug():
    assert sources.slug("Anatomie d'une chute (2023)") == "anatomie-d-une-chute-2023"


def test_validate_flags_partial_file(tmp_path: Path):
    p = tmp_path / "x.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n", encoding="utf-8")
    r = sources.validate(p, duration_ms=6_000_000)
    assert any("only 1 cues" in i for i in r["issues"])
    assert any("under 60%" in i for i in r["issues"])


def test_moviehash_known_value(tmp_path: Path):
    # Reference value computed independently: size + sum of first and last
    # 64 KiB as little-endian uint64, for a file of 131072 bytes of 0x01.
    p = tmp_path / "v.bin"
    p.write_bytes(b"\x01" * 131072)
    word = int.from_bytes(b"\x01" * 8, "little")
    expected = (131072 + 2 * 8192 * word) & 0xFFFFFFFFFFFFFFFF
    assert opensubtitles.moviehash(p) == f"{expected:016x}"


def _srt(n: int) -> str:
    return "".join(
        f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},500\nLine {i}\n\n" for i in range(1, n + 1)
    )


def test_local_lists_tracks_and_sidecars(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    film.mkdir()
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    (film / "Film.tr.srt").write_text(_srt(3), encoding="utf-8")
    (film / "Film.en.srt").write_text(_srt(60), encoding="utf-8")
    streams = [
        {"codec_type": "video", "codec_name": "h264"},
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "fre"}},
        {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "eng"}},
    ]
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            return json.dumps({"format": {"duration": "70.0"}, "streams": streams})
        Path(cmd[-1]).write_text(_srt(60), encoding="utf-8")
        return ""

    monkeypatch.setattr(sources, "_run", fake_run)
    r = sources.local(video, tmp_path / "work")
    by = {(c["source"], c["language"]): c for c in r["candidates"]}
    assert r["duration_ms"] == 70_000
    track = by[("built-in track", "fr")]
    assert track["confidence"] == "certain" and Path(track["path"]).name == "track0.fr.srt"
    assert track["check"]["cues"] == 60
    assert by[("built-in track", "en")]["confidence"] == "skipped: image subtitles"
    assert by[("file next to video", "tr")]["confidence"] == "existing Turkish file, not a source"
    en = by[("file next to video", "en")]
    assert en["confidence"] == "likely" and en["check"]["cues"] == 60
    # One ffprobe and one extraction: the image track and the .srt sidecars need no ffmpeg.
    assert [c[0] for c in calls] == ["ffprobe", "ffmpeg"]


def _item(file_id, **attrs):
    return {"attributes": {"files": [{"file_id": file_id}], "download_count": 10, **attrs}}


def test_search_filters_and_ranks(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_request(method, url, creds, body=None, auth=False):
        seen["url"] = url
        return {
            "data": [
                _item(1, download_count=900),
                _item(2, machine_translated=True),
                _item(3, ai_translated=True),
                _item(4, foreign_parts_only=True),
                {"attributes": {"files": [{"file_id": 5}, {"file_id": 6}]}},
                _item(7, moviehash_match=True),
                _item(8, from_trusted=True),
            ]
        }

    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds, force=False: creds)
    monkeypatch.setattr(opensubtitles, "_request", fake_request)
    r = opensubtitles.search(tmp_path, None, "Film", "tt0123", None, "FR, en")
    assert [x["file_id"] for x in r] == [7, 8, 1]
    assert "imdb_id=123" in seen["url"] and "languages=en%2Cfr" in seen["url"] and "query" not in seen["url"]


def test_download_uses_cache_without_a_request(tmp_path: Path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "os_42.srt").write_bytes(b"cached")

    def no_request(*a, **k):
        raise AssertionError("a cached download must not call the API")

    monkeypatch.setattr(opensubtitles, "_request", no_request)
    monkeypatch.setattr(opensubtitles, "login", no_request)
    r = opensubtitles.download(tmp_path, 42, tmp_path / "out" / "x.srt", cache)
    assert r["from_cache"] and (tmp_path / "out" / "x.srt").read_bytes() == b"cached"
