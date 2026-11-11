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
