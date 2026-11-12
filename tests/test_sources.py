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


TEMPLATE = """# Subtitle It preferences

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
    prefs.write_text("# Subtitle It preferences\n", encoding="utf-8")
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


def _no_tools(monkeypatch):
    def fake_run(cmd):
        assert cmd[0] == "ffprobe", "no track or .ass here, so only ffprobe runs"
        return json.dumps({"format": {"duration": "70.0"}, "streams": []})

    monkeypatch.setattr(sources, "_run", fake_run)


def test_local_reads_a_subs_folder_named_by_language(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film (2019)"
    (film / "Subs").mkdir(parents=True)
    video = film / "Film (2019).mkv"
    video.write_bytes(b"x")
    (film / "Subs" / "English.srt").write_text(_srt(60), encoding="utf-8")
    (film / "Subs" / "French.SDH.srt").write_text(_srt(60), encoding="utf-8")
    (film / "Subs" / "Turkish.srt").write_text(_srt(60), encoding="utf-8")
    (film / "Subs" / "notes.txt").write_text("x", encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(video, tmp_path / "work")
    by = {c["language"]: c for c in r["candidates"]}
    assert set(by) == {"en", "fr", "tr"}
    assert all(c["source"] == "file in a subtitle folder" for c in by.values())
    assert by["en"]["confidence"] == "likely" and by["en"]["check"]["cues"] == 60
    assert by["fr"]["hearing_impaired"]
    assert by["tr"]["confidence"] == "existing Turkish file, not a source"
    assert Path(by["en"]["path"]).parent == tmp_path / "work" / "sources"


def test_local_reads_a_folder_named_after_the_video_inside_subs(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    inner = film / "Subtitles" / "Film (2019)"
    inner.mkdir(parents=True)
    video = film / "Film (2019).mp4"
    video.write_bytes(b"x")
    (inner / "2_English.srt").write_text(_srt(60), encoding="utf-8")
    (inner / "3_English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(video, tmp_path / "work")
    paths = {Path(c["path"]).name for c in r["candidates"]}
    assert len(paths) == 2, "two files with the same language keep separate copies"
    assert {c["language"] for c in r["candidates"]} == {"en"}


def test_local_keeps_files_apart_under_a_long_folder_name(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    inner = film / "Subs" / "Film (2019) subtitles in several languages, with notes"
    inner.mkdir(parents=True)
    video = film / "Film (2019).mkv"
    video.write_bytes(b"x")
    (inner / "2_English.srt").write_text(_srt(60), encoding="utf-8")
    (inner / "3_French.srt").write_text(_srt(70), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(video, tmp_path / "work")
    by = {c["language"]: c for c in r["candidates"]}
    assert set(by) == {"en", "fr"}
    assert by["en"]["path"] != by["fr"]["path"]
    assert by["en"]["check"]["cues"] == 60 and by["fr"]["check"]["cues"] == 70


def test_local_keeps_any_inner_folder_when_this_is_the_only_video(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    inner = film / "Subs" / "Extras"
    inner.mkdir(parents=True)
    video = film / "Film (2019).mkv"
    video.write_bytes(b"x")
    (inner / "2_English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(video, tmp_path / "work")
    assert [c["language"] for c in r["candidates"]] == ["en"]


def test_local_skips_another_episodes_file_directly_in_subs(tmp_path: Path, monkeypatch):
    show = tmp_path / "Show S01"
    (show / "Subs").mkdir(parents=True)
    for ep in ("Show.S01E01", "Show.S01E02"):
        (show / f"{ep}.mkv").write_bytes(b"x")
        (show / "Subs" / f"{ep}.English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(show / "Show.S01E01.mkv", tmp_path / "work")
    assert [Path(c["original"]).name for c in r["candidates"]] == ["Show.S01E01.English.srt"]


def test_local_skips_another_episodes_file_named_only_by_episode(tmp_path: Path, monkeypatch):
    show = tmp_path / "Show S01"
    (show / "Subs").mkdir(parents=True)
    for ep in ("S01E01", "S01E02"):
        (show / f"Show {ep} (2020).mkv").write_bytes(b"x")
        (show / "Subs" / f"Show.{ep}.English.srt").write_text(_srt(60), encoding="utf-8")
    (show / "Subs" / "Show.1x02.French.srt").write_text(_srt(60), encoding="utf-8")
    (show / "Subs" / "English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(show / "Show S01E01 (2020).mkv", tmp_path / "work")
    names = sorted(Path(c["original"]).name for c in r["candidates"])
    assert names == ["English.srt", "Show.S01E01.English.srt"], "a file with no episode code is still kept"


def test_episode_reads_the_usual_codes():
    assert sources.episode("Show.S01E02.English") == (1, 2)
    assert sources.episode("show 1x03 pilot") == (1, 3)
    assert sources.episode("Film.2019.1080p") is None


def test_local_reads_a_folder_spelled_the_turkish_way(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    (film / "Altyazılar").mkdir(parents=True)
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    (film / "Altyazılar" / "English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(video, tmp_path / "work")
    assert [c["language"] for c in r["candidates"]] == ["en"]


def test_local_reads_english_hi_as_hearing_impaired_english(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    (film / "Subs").mkdir(parents=True)
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    (film / "Subs" / "English.HI.srt").write_text(_srt(60), encoding="utf-8")
    (film / "Subs" / "hi.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(video, tmp_path / "work")
    by = {Path(c["original"]).name: c for c in r["candidates"]}
    assert by["English.HI.srt"]["language"] == "en" and by["English.HI.srt"]["hearing_impaired"]
    assert by["hi.srt"]["language"] == "hi", "a file named only hi is still Hindi"


def test_local_skips_another_episodes_subtitle_folder(tmp_path: Path, monkeypatch):
    show = tmp_path / "Show S01"
    for ep in ("Show.S01E01", "Show.S01E02"):
        (show / "Subs" / ep).mkdir(parents=True)
        (show / f"{ep}.mkv").write_bytes(b"x")
        (show / "Subs" / ep / "2_English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    r = sources.local(show / "Show.S01E01.mkv", tmp_path / "work")
    assert [Path(c["original"]).parent.name for c in r["candidates"]] == ["Show.S01E01"]


def test_local_ignores_folders_that_are_not_subtitle_folders(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    (film / "Extras").mkdir(parents=True)
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    (film / "Extras" / "English.srt").write_text(_srt(60), encoding="utf-8")
    _no_tools(monkeypatch)
    assert sources.local(video, tmp_path / "work")["candidates"] == []


def test_a_track_language_that_is_not_a_plain_code_becomes_und(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    film.mkdir()
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    streams = [
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "../../x"}},
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "EN-us"}},
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "ger"}},
    ]

    def fake_run(cmd):
        if cmd[0] == "ffprobe":
            return json.dumps({"format": {"duration": "70.0"}, "streams": streams})
        Path(cmd[-1]).write_text(_srt(60), encoding="utf-8")
        return ""

    monkeypatch.setattr(sources, "_run", fake_run)
    r = sources.local(video, tmp_path / "work")
    names = [Path(c["path"]).name for c in r["candidates"]]
    assert [c["language"] for c in r["candidates"]] == ["und", "und", "de"]
    assert names == ["track0.und.srt", "track1.und.srt", "track2.de.srt"]
    assert all(Path(c["path"]).parent == tmp_path / "work" / "sources" for c in r["candidates"])


def _hi_srt(n: int, every: int) -> str:
    def text(i: int) -> str:
        return f"[Man] Line {i}" if i % every == 0 else f"Line {i}"

    return "".join(
        f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},500\n{text(i)}\n\n" for i in range(1, n + 1)
    )


def test_validate_judges_hearing_impaired_by_content(tmp_path: Path):
    p = tmp_path / "x.srt"
    p.write_text(_hi_srt(60, every=10), encoding="utf-8")
    r = sources.validate(p, duration_ms=70_000)
    assert r["hearing_impaired"] is True and r["cues_with_tags_or_labels"] == 6
    p.write_text(_hi_srt(60, every=100), encoding="utf-8")
    assert sources.validate(p, duration_ms=70_000)["hearing_impaired"] is False


def test_local_marks_a_plainly_named_file_full_of_tags_as_hearing_impaired(tmp_path: Path, monkeypatch):
    film = tmp_path / "Film"
    film.mkdir()
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    (film / "Film.en.srt").write_text(_hi_srt(60, every=5), encoding="utf-8")
    (film / "Film.fr.srt").write_text(_srt(60), encoding="utf-8")
    monkeypatch.setattr(sources, "_run", lambda cmd: json.dumps({"format": {"duration": "70.0"}, "streams": []}))
    r = sources.local(video, tmp_path / "work")
    by = {c["language"]: c for c in r["candidates"]}
    assert by["en"]["hearing_impaired"] is True and by["fr"]["hearing_impaired"] is False
