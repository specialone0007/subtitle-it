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
    out = sources.find("anatomy of a fall", [tmp_path])
    hits = out["matches"]
    assert [Path(h["path"]).name for h in hits] == ["Anatomy of a Fall (2023).mkv", "Anatomy of a Fall Trailer.mp4"]
    assert hits[1]["looks_like_extra"]
    assert out["missing_folders"] == []


def test_find_names_folders_that_are_not_there(tmp_path: Path):
    gone = tmp_path / "unplugged"
    (tmp_path / "Anatomy.of.a.Fall.2023.mkv").write_bytes(b"x")
    out = sources.find("anatomy", [gone, tmp_path])
    assert out["missing_folders"] == [str(gone)]
    assert [Path(h["path"]).name for h in out["matches"]] == ["Anatomy.of.a.Fall.2023.mkv"]


TEMPLATE = """# Turkish subtitles preferences

## Media folders

Folders searched when you give a film name instead of a path, one per line.

-

## Translator model

session
"""


def test_remember_fills_the_empty_bullet_with_the_parent_of_a_film_folder(tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    prefs.write_text(TEMPLATE, encoding="utf-8")
    film = tmp_path / "E" / "Films" / "The Quiet Hour (2019)" / "The.Quiet.Hour.2019.2160p.mkv"
    film.parent.mkdir(parents=True)
    film.write_bytes(b"x")
    out = sources.remember(film, prefs)
    assert out == {"added": str((tmp_path / "E" / "Films").resolve()), "covered_by": None, "too_broad": None}
    assert sources.media_folders(prefs) == [out["added"]]
    text = prefs.read_text(encoding="utf-8")
    assert "\n-\n" not in text and "## Translator model\n\nsession" in text


def test_remember_adds_a_loose_film_folder_after_the_listed_ones(tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    films = tmp_path / "Films"
    films.mkdir()
    prefs.write_text(TEMPLATE.replace("\n-\n", f"\n- {films}\n"), encoding="utf-8")
    film = tmp_path / "Videos" / "Anatomy.of.a.Fall.2023.mkv"
    film.parent.mkdir()
    film.write_bytes(b"x")
    out = sources.remember(film, prefs)
    assert out["added"] == str(film.parent.resolve())
    assert sources.media_folders(prefs) == [str(films), out["added"]]


def test_remember_skips_a_film_already_inside_a_listed_folder(tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    prefs.write_text(TEMPLATE.replace("\n-\n", f"\n- {tmp_path}\n"), encoding="utf-8")
    film = tmp_path / "Anatomy of a Fall (2023)" / "Anatomy.of.a.Fall.2023.mkv"
    film.parent.mkdir()
    film.write_bytes(b"x")
    before = prefs.read_text(encoding="utf-8")
    assert sources.remember(film, prefs) == {"added": None, "covered_by": str(tmp_path), "too_broad": None}
    assert prefs.read_text(encoding="utf-8") == before


def test_a_media_folder_written_with_a_tilde_means_the_home_folder(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    prefs = tmp_path / "preferences.md"
    prefs.write_text(TEMPLATE.replace("\n-\n", "\n- ~/Films\n"), encoding="utf-8")
    film = tmp_path / "Films" / "Anatomy of a Fall (2023)" / "Anatomy.of.a.Fall.2023.mkv"
    film.parent.mkdir(parents=True)
    film.write_bytes(b"x")
    before = prefs.read_text(encoding="utf-8")
    assert sources.remember(film, prefs) == {"added": None, "covered_by": "~/Films", "too_broad": None}
    assert prefs.read_text(encoding="utf-8") == before
    out = sources.find("anatomy", [Path("~/Films")])
    assert out["missing_folders"] == [] and len(out["matches"]) == 1


def test_remember_creates_the_section_when_preferences_lack_it(tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    prefs.write_text("# Turkish subtitles preferences\n", encoding="utf-8")
    film = tmp_path / "Videos" / "Anatomy.of.a.Fall.2023.mkv"
    film.parent.mkdir()
    film.write_bytes(b"x")
    out = sources.remember(film, prefs)
    assert sources.media_folders(prefs) == [out["added"]]


def test_folder_to_remember_never_picks_a_drive_root_or_home(monkeypatch, tmp_path: Path):
    film_dir = tmp_path / "Anatomy of a Fall (2023)"
    film_dir.mkdir()
    film = film_dir / "Anatomy.of.a.Fall.2023.mkv"
    film.write_bytes(b"x")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert sources.folder_to_remember(film) == film_dir.resolve()


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


def test_remember_adds_nothing_for_a_loose_film_in_the_home_folder(monkeypatch, tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    prefs.write_text(TEMPLATE, encoding="utf-8")
    film = tmp_path / "Anatomy.of.a.Fall.2023.mkv"
    film.write_bytes(b"x")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    out = sources.remember(film, prefs)
    assert out == {"added": None, "covered_by": None, "too_broad": str(tmp_path.resolve())}
    assert prefs.read_text(encoding="utf-8") == TEMPLATE


def test_remember_adds_nothing_for_a_loose_film_at_a_drive_root(monkeypatch, tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    prefs.write_text(TEMPLATE, encoding="utf-8")
    root = Path(tmp_path.anchor)
    monkeypatch.setattr(sources, "folder_to_remember", lambda file: root)
    out = sources.remember(tmp_path / "Anatomy.of.a.Fall.2023.mkv", prefs)
    assert out == {"added": None, "covered_by": None, "too_broad": str(root)}
    assert prefs.read_text(encoding="utf-8") == TEMPLATE
