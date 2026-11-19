"""On-screen text read from the picture: the one extra download
(sources.others), the frames (screen.plan_frames, screen.frames), the
readers' lines (screen.collect) and the build that uses them
(prepare.build --screen). No images and no film text: the frames lists
and the readings are made up, and ffmpeg is faked (tests/test_ffmpeg.py
runs the real one)."""

import json
from pathlib import Path

import pytest

import assemble
import prepare
import screen
import sources
import srt

# Dialogue every 4 seconds from 0:10 to 5:28.5, as in test_on_screen.py.
LINES = 80
LAST_END = 10_000 + 4_000 * (LINES - 1) + 2_500
CARD = (1_000, 3_500)  # before the first line
MIDDLE = (152_600, 153_800)  # between two lines, 1.5 s free
TAIL_TEXT = (340_000, 343_000)  # after the story


def _film(tmp: Path, name: str, word: str, extra=(), offset: int = 0) -> Path:
    cues = [(10_000 + k * 4_000 + offset, 12_500 + k * 4_000 + offset, f"{word} {k + 1}, here.") for k in range(LINES)]
    cues += [(a + offset, b + offset, text) for a, b, text in extra]
    cues.sort()
    body = "".join(f"{i}\n{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(cues, 1))
    path = tmp / name
    path.write_text(body, encoding="utf-8")
    return path


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _entries(w: Path) -> dict[str, dict]:
    return {e["id"]: e for e in _json(w / prepare.ON_SCREEN_FILE)}


# --- the one extra download --------------------------------------------------


def test_other_languages_leave_out_turkish_und_and_the_timing_language():
    assert srt.other_languages(["pt-br", "pt", "tr", "und", "en", "FR"], "en") == ["fr", "pt"]
    assert srt.other_languages(["en-gb"], "en") == []


def _cand(lang: str, issues=(), forced_only=False) -> dict:
    return {"language": lang, "check": {"issues": list(issues)}, "forced_only": forced_only}


@pytest.mark.parametrize(
    "cands, also, timing, langs, download",
    [
        ([], [], "en", [], "fr"),
        ([_cand("en"), _cand("fr")], [], "en", ["fr"], "es"),
        ([_cand("es")], [], "en", ["es"], "fr"),
        ([_cand("fr"), _cand("de")], [], "en", ["de", "fr"], None),
        ([_cand("fr")], ["pt-br"], "en", ["fr", "pt"], None),
        # A forced track's few lines, a file with issues and Turkish do not count.
        ([_cand("de", forced_only=True), _cand("it", ["only 12 cues"]), _cand("tr")], [], "en", [], "fr"),
        # The timing file's own language is never downloaded.
        ([_cand("es")], [], "fr", ["es"], None),
        ([], [], "fr", [], "es"),
    ],
)
def test_others_names_the_one_extra_download(cands, also, timing, langs, download):
    out = sources.others({"candidates": cands}, timing, also)
    assert out == {"languages": langs, "count": len(langs), "download": download}


def test_others_leaves_out_a_candidate_that_does_not_fit(tmp_path: Path):
    cands = [
        {"language": "fr", "path": str(tmp_path / "fr.srt"), "check": {"issues": []}},
        {"language": "es", "path": str(tmp_path / "es.srt"), "check": {"issues": []}},
    ]
    assert sources.others({"candidates": cands}, "en", [])["download"] is None
    out = sources.others({"candidates": cands}, "en", [], [str(tmp_path / "es.srt")])
    assert out["languages"] == ["fr"] and out["download"] == "es"


def test_build_counts_only_the_tracks_that_fit(tmp_path: Path):
    w = tmp_path / "work"
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "UN JOUR")])
    # Ten minutes late from the middle on: a different cut, so it does not fit.
    es = tmp_path / "es.srt"
    cues = [
        (10_000 + k * 4_000 + (600_000 if k >= 40 else 0), 12_500 + k * 4_000 + (600_000 if k >= 40 else 0)) for k in range(LINES)
    ]
    es.write_text(
        "".join(f"{i}\n{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}\nLínea {i}.\n\n" for i, (a, b) in enumerate(cues, 1)), encoding="utf-8"
    )
    summary = prepare.build(
        w, _film(tmp_path, "en.srt", "Line"), None, None, tracks=[("fr", fr), ("es", es)], timing_language="en"
    )
    info = summary["on_screen"]
    assert [t["fits"] for t in info["tracks"]] == [True, False]
    assert info["other_languages"] == ["fr"]


def test_others_reads_the_local_result_file(tmp_path: Path, capsys):
    local = tmp_path / "sources-local.json"
    local.write_text(json.dumps({"candidates": [_cand("en"), _cand("fr")]}), encoding="utf-8")
    sources.main(["others", "--local", str(local), "--timing-language", "en", "--also", "es"])
    assert json.loads(capsys.readouterr().out)["download"] is None


# --- which frames ------------------------------------------------------------


def _one_language_build(tmp: Path, tracks_extra=((*CARD, "UN JOUR"), (*MIDDLE, "Hé!"))) -> Path:
    w = tmp / "work"
    fr = _film(tmp, "fr.srt", "Ligne", list(tracks_extra))
    prepare.build(w, _film(tmp, "en.srt", "Line"), None, None, tracks=[("fr", fr)], timing_language="en")
    return w


def test_build_records_the_other_languages_of_its_tracks(tmp_path: Path):
    w = _one_language_build(tmp_path)
    info = _json(w / "build.json")["on_screen"]
    assert info["other_languages"] == ["fr"] and info["timing_language"] == "en"
    assert {e["reason"] for e in _entries(w).values()} == {prepare.ONE_LANGUAGE}


def test_frames_cover_the_head_the_tail_and_each_unsure_entry(tmp_path: Path):
    w = _one_language_build(tmp_path)
    rows, entries = _json(w / "cues.json"), list(_entries(w).values())
    plan = screen.plan_frames(rows, entries, ["fr"], 600_000)
    assert plan["head"] == [0, 10_000] and plan["tail"] == [LAST_END, LAST_END + 150_000]
    head = [ms for ms, why in plan["picks"] if why == "head"]
    tail = [ms for ms, why in plan["picks"] if why == "tail"]
    assert head == list(range(0, 10_000, 1_500)) and len(tail) == 100 and tail[1] - tail[0] == 1_500
    # Both entries are unsure; the card lies in the head, so only the sign
    # in the middle gets frames of its own: 5, across its time widened by 2 s.
    assert sorted(plan["unsure"]) == sorted(entries[i]["id"] for i in range(2))
    middle = next(e["id"] for e in entries if e["start"] == MIDDLE[0])
    own = [ms for ms, why in plan["picks"] if why == f"entry {middle}"]
    assert own == [150_600, 151_900, 153_200, 154_500, 155_800]
    assert plan["notes"] == []
    # With two other languages nothing is unsure.
    plan = screen.plan_frames(rows, entries, ["es", "fr"], 600_000)
    assert plan["unsure"] == [] and {why for _, why in plan["picks"]} == {"head", "tail"}
    # The tail ends with the video.
    assert screen.plan_frames(rows, entries, [], LAST_END + 3_000)["tail"] == [LAST_END, LAST_END + 3_000]


def _row(n: int, a: int, b: int, **kw) -> dict:
    return {"n": n, "start": a, "end": b, "ts": f"{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}", "timing_lines": ["Hi."], **kw}


def test_spoken_cues_leave_out_cards_songs_and_sounds():
    rows = [
        _row(1, 0, 1_000, on_screen={"fr": ["X"]}),
        _row(2, 2_000, 3_000, song=True),
        _row(3, 4_000, 5_000, timing_lines=["[door slams]"]),
        _row(4, 6_000, 7_000, sound_only=True, timing_lines=[]),
        _row(5, 8_000, 9_000),
        _row(6, 10_000, 11_000, timing_lines=["♪ la la ♪"]),
    ]
    assert screen.spoken_spans(rows) == [(8_000, 9_000)]


def _unsure_entry(k: int) -> dict:
    a = 400_000 + k * 10_000
    return {
        "id": f"1:{k + 1}",
        "start": a,
        "end": a + 1_000,
        "texts": {"fr": ["x"]},
        "state": "left_out",
        "reason": prepare.ONE_LANGUAGE,
    }


def test_the_cap_thins_the_unsure_frames_then_drops_the_latest():
    # A spoken cue at 2:30: 100 head frames, 100 tail frames, room for 100.
    rows = [_row(1, 150_000, 151_000)]
    plan = screen.plan_frames(rows, [_unsure_entry(k) for k in range(30)], ["fr"], None)
    assert len(plan["picks"]) == 300
    per = [sum(1 for _, why in plan["picks"] if why == f"entry 1:{k + 1}") for k in range(30)]
    assert per == [4] * 10 + [3] * 20
    assert "thinned to 3 or 4 each" in plan["notes"][0]
    plan = screen.plan_frames(rows, [_unsure_entry(k) for k in range(150)], ["fr"], None)
    assert len(plan["picks"]) == 300
    per = [sum(1 for _, why in plan["picks"] if why == f"entry 1:{k + 1}") for k in range(150)]
    assert per == [1] * 100 + [0] * 50
    assert "1:101" in plan["notes"][0] and "1:150" in plan["notes"][0]
    # The head and the tail are never thinned.
    assert sum(1 for _, why in plan["picks"] if why in ("head", "tail")) == 200


def test_the_head_stops_at_two_and_a_half_minutes():
    plan = screen.plan_frames([_row(1, 200_000, 201_000)], [], [], None)
    assert plan["head"] == [0, 150_000] and sum(1 for _, why in plan["picks"] if why == "head") == 100


def test_a_frame_lists_the_entries_within_3_s():
    entries = [{"id": "a", "start": 10_000, "end": 11_000, "texts": {"fr": ["Un", "deux"]}}]
    assert screen.near(entries, 7_000) == [{"id": "a", "texts": {"fr": "Un / deux"}}]
    assert screen.near(entries, 14_000) == [{"id": "a", "texts": {"fr": "Un / deux"}}]
    assert screen.near(entries, 14_001) == []


# --- saving the frames, ffmpeg faked ------------------------------------------


def _fake_ffmpeg(monkeypatch, duration=600_000, hdr=False, zscale=True, tone_fails=False, short=0) -> list:
    """`tone_fails`: a window with the tone map saves nothing. `short`: each
    window saves that many files fewer than asked."""
    calls = []

    def window(exe, video, a, b, vf, pattern):
        calls.append(("window", a, b, vf))
        files = [Path(str(pattern) % (k + 1)) for k in range(-(-(b - a) // screen.FRAME_STEP_MS))]
        if tone_fails and screen.TONE_MAP in vf:
            return files
        for f in files[: len(files) - short]:
            f.write_bytes(b"jpg")
        return files

    def one(exe, video, ms, vf, dest):
        calls.append(("one", ms, vf))
        dest.write_bytes(b"jpg")

    monkeypatch.setattr(screen.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(screen, "_probe", lambda exe, video: (duration, hdr))
    monkeypatch.setattr(screen, "_has_zscale", lambda exe: zscale)
    monkeypatch.setattr(screen, "_save_window", window)
    monkeypatch.setattr(screen, "_save_one", one)
    return calls


def test_frames_writes_the_list_the_batches_and_marks_the_unsure_entries(tmp_path: Path, monkeypatch):
    w = _one_language_build(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)
    out = screen.frames(w, tmp_path / "Film.mkv")
    assert out["frames"] == 7 + 100 + 5 and out["head"] == 7 and out["tail"] == 100 and out["unsure"] == 2
    assert out["hdr"] is False and out["tone_mapped"] is None and out["notes"] == []
    data = _json(w / prepare.FRAMES_FILE)
    files = [f["file"] for f in data["frames"]]
    assert files == [f"frame_{k:04d}.jpg" for k in range(1, 113)]
    assert [f["ms"] for f in data["frames"]] == sorted(f["ms"] for f in data["frames"])
    assert all((w / screen.FRAMES_DIR / name).exists() for name in files)
    assert sorted(p.name for p in (w / screen.FRAMES_DIR).iterdir()) == files
    # The card's id travels with the head frames near it.
    card = next(e for e in _entries(w).values() if e["start"] == CARD[0])
    assert data["frames"][0]["entries"] == [{"id": card["id"], "texts": {"fr": "UN JOUR"}}]
    assert {e["state"] for e in _entries(w).values()} == {"unsure"}
    assert all("reason" not in e for e in _entries(w).values())
    # 112 frames: one reader, 6 batches of 20 at most.
    [reader] = data["readers"]
    assert reader["frames"] == 112 and len(reader["batches"]) == 6
    batch = _json(Path(reader["batches"][-1]))
    assert len(batch["frames"]) == 12 and batch["out"] == str(w / "screen" / "read_06.jsonl")
    assert [c[0] for c in calls].count("one") == 5
    # Fitted into 960x540, nothing else: no frame is dropped as black.
    assert all(c[-1] == screen.SCALE for c in calls)


def test_frames_split_readers_at_150_frames(tmp_path: Path, monkeypatch):
    w = tmp_path / "work"
    timing = _film(tmp_path, "en.srt", "Line", offset=140_000)  # a 2.5-minute head
    prepare.build(w, timing, None, None)
    _fake_ffmpeg(monkeypatch, duration=10_000_000)
    out = screen.frames(w, tmp_path / "Film.mkv")
    assert out["frames"] == 200
    assert [(r["frames"], len(r["batches"])) for r in out["readers"]] == [(150, 8), (50, 3)]


def test_frames_tone_map_hdr_or_say_why_not(tmp_path: Path, monkeypatch):
    w = _one_language_build(tmp_path)
    calls = _fake_ffmpeg(monkeypatch, hdr=True)
    out = screen.frames(w, tmp_path / "Film.mkv")
    assert out["tone_mapped"] is True and screen.TONE_MAP in calls[0][-1]
    calls = _fake_ffmpeg(monkeypatch, hdr=True, zscale=False)
    out = screen.frames(w, tmp_path / "Film.mkv")
    assert out["tone_mapped"] is False and "without tone mapping" in out["notes"][0]
    assert _json(w / prepare.FRAMES_FILE)["notes"] == out["notes"]


def test_frames_save_again_without_the_tone_map_when_it_saves_nothing(tmp_path: Path, monkeypatch):
    w = _one_language_build(tmp_path)
    calls = _fake_ffmpeg(monkeypatch, hdr=True, tone_fails=True)
    out = screen.frames(w, tmp_path / "Film.mkv")
    assert out["tone_mapped"] is False and out["frames"] == 7 + 100 + 5
    assert out["notes"] == ["HDR video: tone mapping failed, so the frames were saved without it"]
    # Tried once with the tone map, then every window and frame without it.
    windows = [c[-1] for c in calls if c[0] == "window"]
    assert screen.TONE_MAP in windows[0] and all(vf == screen.SCALE for vf in windows[1:]) and len(windows) == 3
    assert all(c[-1] == screen.SCALE for c in calls if c[0] == "one")


def test_frames_name_the_frames_that_could_not_be_saved(tmp_path: Path, monkeypatch):
    w = _one_language_build(tmp_path)
    _fake_ffmpeg(monkeypatch, short=2)
    out = screen.frames(w, tmp_path / "Film.mkv")
    assert out["frames"] == 7 + 100 + 5 - 4
    assert out["notes"] == ["4 frames could not be saved (past the end of the video or unreadable)"]


def test_frames_never_fail_a_run(tmp_path: Path, monkeypatch):
    w = _one_language_build(tmp_path)
    before = (w / prepare.ON_SCREEN_FILE).read_text(encoding="utf-8")
    monkeypatch.setattr(screen.shutil, "which", lambda name: None)
    assert screen.frames(w, tmp_path / "Film.mkv")["error"] == "ffmpeg not found on PATH"
    _fake_ffmpeg(monkeypatch)
    monkeypatch.setattr(screen, "_save_window", lambda *a: [])
    monkeypatch.setattr(screen, "_save_one", lambda *a: None)
    assert screen.frames(w, tmp_path / "Film.mkv")["error"] == "ffmpeg saved no frame from this video"
    assert not (w / prepare.FRAMES_FILE).exists()
    assert (w / prepare.ON_SCREEN_FILE).read_text(encoding="utf-8") == before


# --- the readers' lines ------------------------------------------------------


def _frames_file(w: Path, frames: list[tuple[int, list[str]]], per_batch: int = 20) -> list[str]:
    """frames.json and its batch files for frames at these times, listing
    these entry ids; returns the batch out files."""
    listed = [
        {
            "file": f"frame_{k:04d}.jpg",
            "ms": ms,
            "at": srt.fmt_ms(ms),
            "why": "head",
            "entries": [{"id": i, "texts": {}} for i in ids],
        }
        for k, (ms, ids) in enumerate(frames, 1)
    ]
    (w / "screen").mkdir(parents=True, exist_ok=True)
    outs = []
    for b in range(0, len(listed), per_batch):
        no = b // per_batch + 1
        out = str(w / "screen" / f"read_{no:02d}.jsonl")
        (w / "screen" / f"batch_{no:02d}.json").write_text(
            json.dumps({"batch": no, "out": out, "frames": listed[b : b + per_batch]}), encoding="utf-8"
        )
        outs.append(out)
    data = {"frames": listed, "unsure": [], "notes": []}
    (w / prepare.FRAMES_FILE).write_text(json.dumps(data), encoding="utf-8")
    return outs


def _line(frame: int, text: str = "", kind: str = "background", wants: bool = False, shows=None) -> str:
    return json.dumps({"frame": f"frame_{frame:04d}.jpg", "text": text, "kind": kind, "wants_read": wants, "shows_entry": shows})


def test_collect_sends_missing_doubled_and_bad_frames_back_once(tmp_path: Path):
    w = tmp_path / "work"
    outs = _frames_file(w, [(k * 1_500, ["2:5"] if k == 3 else []) for k in range(6)], per_batch=3)
    Path(outs[0]).write_text(
        "\n".join([_line(1), _line(2), _line(2), "not json", _line(3, kind="poster")]) + "\n", encoding="utf-8"
    )
    # Frame 6 is missing; frame 5 names an entry its frame does not list.
    Path(outs[1]).write_text(
        "\n".join([_line(4, "A", "sign", True, "2:5"), _line(5, "B", "sign", True, "9:9")]), encoding="utf-8"
    )
    first = screen.collect(w)
    assert first["missing"] == ["frame_0002.jpg", "frame_0003.jpg", "frame_0005.jpg", "frame_0006.jpg"]
    assert first["redo"] == str(w / "screen" / "batch_redo.json")
    redo = _json(Path(first["redo"]))
    assert [f["file"] for f in redo["frames"]] == first["missing"] and redo["out"].endswith("read_redo.jsonl")
    Path(redo["out"]).write_text("\n".join([_line(2), _line(3), _line(5, "B", "sign", True)]), encoding="utf-8")
    second = screen.collect(w)
    # Once only: frame 6 is still missing, and no second redo is asked.
    assert second["missing"] == ["frame_0006.jpg"] and second["redo"] is None and second["read"] == 5
    assert _json(w / screen.READINGS_FILE)["missing"] == ["frame_0006.jpg"]


def test_collect_sends_back_a_line_with_a_list_where_a_name_belongs(tmp_path: Path):
    w = tmp_path / "work"
    outs = _frames_file(w, [(0, ["1:1"]), (1_500, ["1:1"]), (3_000, [])])
    bad_frame = json.dumps({"frame": ["frame_0003.jpg"], "text": "", "kind": "background", "wants_read": False})
    Path(outs[0]).write_text("\n".join([_line(1), _line(2, "A", "sign", True, ["1:1"]), bad_frame]), encoding="utf-8")
    out = screen.collect(w)
    assert out["missing"] == ["frame_0002.jpg", "frame_0003.jpg"] and out["redo"]
    assert [f["file"] for f in _json(Path(out["redo"]))["frames"]] == out["missing"]


def test_collect_joins_neighbouring_frames_with_the_same_text(tmp_path: Path):
    w = tmp_path / "work"
    times = [0, 1_500, 3_000, 4_500, 6_000, 12_000, 13_500]
    outs = _frames_file(w, [(ms, ["1:1"]) for ms in times])
    lines = [
        _line(1, "THE  CARD", "title card", True),
        _line(2, "THE CARD", "title card", True, "1:1"),
        _line(3, "THE CARD", "title card", True),
        _line(4),  # empty: ends the reading
        _line(5, "THE CARD", "title card", True),
        _line(6, "THE CARD", "title card", True),  # 6 s later: its own reading
        _line(7, "Studio", "logo", True),
    ]
    Path(outs[0]).write_text("\n".join(lines), encoding="utf-8")
    out = screen.collect(w)
    assert out["missing"] == [] and out["readings"] == 4 and out["story_readings"] == 3
    readings = _json(w / screen.READINGS_FILE)["readings"]
    assert [(r["first_ms"], r["last_ms"], r["shows_entry"], r["story"]) for r in readings] == [
        (0, 3_000, ["1:1"], True),
        (6_000, 6_000, [], True),
        (12_000, 12_000, [], True),
        (13_500, 13_500, [], False),
    ]
    assert readings[0]["frames"] == ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"] and readings[0]["text"] == "THE CARD"


# --- the build with what the picture showed ---------------------------------


def _picture(w: Path, frames: list[tuple[int, list[str]]], unsure: list[str], readings: list[dict], missing=()) -> Path:
    listed = [
        {"file": f"frame_{k:04d}.jpg", "ms": ms, "entries": [{"id": i} for i in ids]} for k, (ms, ids) in enumerate(frames, 1)
    ]
    (w / "screen").mkdir(exist_ok=True)
    (w / prepare.FRAMES_FILE).write_text(json.dumps({"frames": listed, "unsure": unsure, "notes": ["a note"]}), encoding="utf-8")
    path = w / screen.READINGS_FILE
    path.write_text(json.dumps({"frames": len(listed), "missing": list(missing), "readings": readings}), encoding="utf-8")
    return path


def _reading(text: str, a: int, b: int, kind: str = "title card", wants: bool = True, shows=()) -> dict:
    return {
        "text": text,
        "kind": kind,
        "wants_read": wants,
        "first_ms": a,
        "last_ms": b,
        "frames": [],
        "shows_entry": list(shows),
    }


SIGN = (200_600, 201_800)  # between two lines, 1.5 s free


def _screen_film(tmp: Path) -> tuple[Path, dict]:
    extra = [(*CARD, "UN JOUR"), (*MIDDLE, "Hé!"), (*SIGN, "Sortie"), (5_000, 6_000, "Sous-titres : Jean")]
    w = _one_language_build(tmp, extra)
    ids = {e["lines"][0]: e["id"] for e in _entries(w).values()}
    return w, ids


def _build_screen(tmp: Path, w: Path, readings: Path, **kw) -> dict:
    fr = tmp / "fr.srt"
    return prepare.build(w, tmp / "en.srt", None, None, tracks=[("fr", fr)], timing_language="en", screen_path=readings, **kw)


def test_a_reading_joins_only_the_entry_it_names(tmp_path: Path):
    w, ids = _screen_film(tmp_path)
    card, middle, sign, credit = ids["UN JOUR"], ids["Hé!"], ids["Sortie"], ids["Sous-titres : Jean"]
    frames = [(1_500, [card, credit]), (5_500, [card, credit]), (152_000, [middle]), (153_000, [middle])]
    frames += [(200_000, [sign]), (201_000, [sign])]
    readings = [
        _reading("ONE DAY", 1_500, 1_500, shows=[card]),
        # A logo at the time of the subtitle credit: time alone never joins.
        _reading("Studio", 5_500, 5_500, kind="logo"),
        _reading("Hey!", 152_000, 153_000, kind="sign", wants=False, shows=[middle]),
    ]
    (w / "screen" / "ends.json").parent.mkdir(exist_ok=True)
    (w / "screen" / "ends.json").write_text("{}", encoding="utf-8")
    path = _picture(w, frames, [card, middle, sign], readings, missing=["frame_0006.jpg"])
    summary = _build_screen(tmp_path, w, path)
    e = _entries(w)
    assert (e[card]["state"], e[card]["picture"]) == ("cue", "shown") and e[card]["n"] == 1
    # Named, but not as story text: not confirmed.
    assert (e[middle]["state"], e[middle]["reason"], e[middle]["picture"]) == (
        "left_out",
        prepare.NOT_CONFIRMED,
        "shown, not story text",
    )
    # One of its frames was not read.
    assert (e[sign]["state"], e[sign]["reason"], e[sign]["picture"]) == ("left_out", prepare.NOT_CHECKED, "not read")
    assert (e[credit]["state"], e[credit]["reason"], e[credit]["picture"]) == ("left_out", prepare.CREDIT, "not shown")
    assert not any(x["state"] == "unsure" for x in e.values())
    info = summary["on_screen"]["picture"]
    assert info["frames"] == 6 and info["frames_not_read"] == ["frame_0006.jpg"] and info["unsure"] == 3
    assert info["found"] == 0 and info["looked_at"] == 4 and info["notes"] == ["a note"]
    # --screen keeps the folder it reads.
    assert (w / "screen" / "ends.json").exists() and (w / prepare.FRAMES_FILE).exists()


def test_a_named_left_out_entry_is_added_only_for_three_reasons(tmp_path: Path):
    w, ids = _screen_film(tmp_path)
    credit = ids["Sous-titres : Jean"]
    path = _picture(w, [(5_500, [credit])], [], [_reading("Subtitles: Jean", 5_500, 5_500, kind="caption", shows=[credit])])
    _build_screen(tmp_path, w, path)
    assert _entries(w)[credit]["state"] == "cue"
    # Unsure entries the frames never listed are not checked.
    _picture(w, [], [ids["Hé!"]], [])
    _build_screen(tmp_path, w, path)
    assert _entries(w)[ids["Hé!"]]["reason"] == prepare.NOT_CHECKED


def test_a_story_text_no_entry_holds_becomes_a_picture_entry(tmp_path: Path):
    w, _ = _screen_film(tmp_path)
    readings = [
        _reading("THE END", *TAIL_TEXT, kind="closing text"),
        # Over speech: already in the timing file.
        _reading("LOUD SIGN", 20_000, 21_000, kind="sign"),
        # One frame 0.6 s before a line: too short a slot, and too little
        # of it under speech to count as in the timing file.
        _reading("FAST", 13_400, 13_400, kind="caption"),
        # Never added: credits, a logo, and text the film does not want read.
        _reading("Director", 345_000, 346_000, kind="credits"),
        _reading("A shop", 347_000, 348_000, kind="sign", wants=False),
    ]
    path = _picture(w, [(ms, []) for ms in (340_000, 343_000)], [], readings)
    summary = _build_screen(tmp_path, w, path)
    found = [e for e in _entries(w).values() if e.get("evidence") == prepare.PICTURE]
    assert [(e["id"], e["state"], e.get("reason"), e["lines"]) for e in found] == [
        ("picture:13400", "left_out", prepare.NO_ROOM, ["FAST"]),
        ("picture:20000", "left_out", prepare.UNDER_TIMING, ["LOUD SIGN"]),
        (f"picture:{TAIL_TEXT[0]}", "cue", None, ["THE END"]),
    ]
    # Each has a number, so a sync rebuild can place it again; the two
    # left out are rows left out, with their reading's own times kept.
    assert [e["n"] for e in found] == [2, 5, LINES + 3]
    assert [e["found"] for e in found] == [[13_400, 14_100], [20_000, 21_000], list(TAIL_TEXT)]
    rows = {r["n"]: r for r in _json(w / "cues.json")}
    assert (rows[2]["left_out"], rows[5]["left_out"]) == (prepare.NO_ROOM, prepare.UNDER_TIMING)
    assert {prepare.NO_ROOM, prepare.UNDER_TIMING} <= set(assemble.LEFT_OUT_NOTES)
    assert [r["n"] for r in rows.values()] == list(range(1, LINES + 4))
    end = found[2]
    assert (end["start"], end["end"], end["picture"]) == (*TAIL_TEXT, "found")
    info = summary["on_screen"]["picture"]
    assert info["readings_already_in_timing"] == 1 and info["found"] == 2
    prepare.chunks(w, target=250)
    chunk = (w / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    assert f"#{LINES + 3} 00:05:40 [on-screen text]\nsrc: THE END\n\n" in chunk
    assert "or the picture" in chunk.splitlines()[3]


def test_a_single_frame_reading_lasts_the_shortest_cue():
    assert prepare.picture_span(_reading("X", 5_000, 5_000)) == (5_000, 5_000 + prepare.ON_SCREEN_MIN_MS)


def _next(r: dict, next_ms: int | None) -> dict:
    return {**r, "next_ms": next_ms}


def test_a_picture_cue_stays_up_until_the_next_saved_frame():
    # Die My Love: the cake on two frames 1.5 s apart, the next frame 1.5 s
    # later. The cue lasts until that frame: 01:51:19.458 to 01:51:22.458.
    cake = _next(_reading("Mommy's / home", 6_679_458, 6_680_958, kind="sign"), 6_682_458)
    assert prepare.picture_shown_end(cake) == 6_682_458
    # Frames 1 s apart in the middle of the film: until the next one; one
    # frame alone still lasts 1.5 s.
    assert prepare.picture_shown_end(_next(_reading("X", 0, 2_000), 3_000)) == 3_000
    assert prepare.picture_shown_end(_next(_reading("X", 0, 0), 1_000)) == 1_500
    # Frames far apart: 1.5 s after the last one at most; after the last
    # saved frame too.
    assert prepare.picture_shown_end(_next(_reading("X", 0, 3_000), 60_000)) == 4_500
    assert prepare.picture_shown_end(_next(_reading("X", 0, 3_000), None)) == 4_500
    # A reading from an older work folder has no next_ms: its seen span.
    assert prepare.picture_shown_end(_reading("X", 0, 3_000)) == 3_000
    assert prepare.picture_shown_end(_reading("X", 0, 0)) == prepare.ON_SCREEN_MIN_MS


def test_collect_joins_frames_whose_text_differs_only_in_case_or_punctuation(tmp_path: Path):
    w = tmp_path / "work"
    times = [0, 1_500, 3_000, 4_500, 6_000, 7_500, 9_000, 10_500, 12_000, 13_500]
    outs = _frames_file(w, [(ms, []) for ms in times])
    lines = [
        _line(1, "Mommy's / home", "sign", True),
        _line(2, "mommy's home", "sign", True),
        _line(3),
        # Two story kinds are one text; wants_read when any frame says so.
        _line(4, "EXIT", "sign", False),
        _line(5, "Exit.", "caption", True),
        _line(6, "exit", "caption", True),
        # A story kind and credits are not.
        _line(7, "EXIT", "credits", False),
        # Really different texts stay apart.
        _line(8, "OPEN", "sign", True),
        _line(9, "CLOSED", "sign", True),
        _line(10, "CLOSED", "sign", True),
    ]
    Path(outs[0]).write_text("\n".join(lines), encoding="utf-8")
    out = screen.collect(w)
    readings = _json(w / screen.READINGS_FILE)["readings"]
    got = [(r["text"], r["kind"], r["wants_read"], r["story"], r["first_ms"], r["last_ms"], r["next_ms"]) for r in readings]
    assert got == [
        # On a tie, the first frame's text.
        ("Mommy's / home", "sign", True, True, 0, 1_500, 3_000),
        ("EXIT", "caption", True, True, 4_500, 7_500, 9_000),
        ("EXIT", "credits", False, False, 9_000, 9_000, 10_500),
        ("OPEN", "sign", True, True, 10_500, 10_500, 12_000),
        # After the last saved frame: null.
        ("CLOSED", "sign", True, True, 12_000, 13_500, None),
    ]
    assert out["readings"] == 5 and out["story_readings"] == 4
    assert readings[1]["frames"] == ["frame_0004.jpg", "frame_0005.jpg", "frame_0006.jpg"]


def _forced(tmp: Path, *lines: tuple[int, int, str]) -> Path:
    path = tmp / "forced.srt"
    srt.write(
        path,
        [
            srt.Cue(n=k, start=a, end=b, ts=f"{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}", lines=[t])
            for k, (a, b, t) in enumerate(lines, 1)
        ],
    )
    return path


def _two_timing_cues(end_of_gap: int) -> list[srt.Cue]:
    return [
        srt.Cue(n=1, start=10_000, end=12_000, ts="", lines=["Line one."]),
        srt.Cue(n=2, start=end_of_gap, end=end_of_gap + 2_000, ts="", lines=["Line two."]),
    ]


def test_a_picture_cue_never_pushes_the_next_item_out(tmp_path: Path):
    # A one-frame card at 50 s aims to stay up to 51.5 s, but a forced
    # track's 0.8 s sign starts at 51 s: the card ends there and the sign
    # still shows.
    timing = _two_timing_cues(80_000)
    forced = _forced(tmp_path, (51_000, 51_800, "SORTIE"))
    picture = {"readings": [_next(_reading("CARD", 50_000, 50_000), 51_000)]}
    entries, _ = prepare.on_screen(timing, [], [("fr", forced)], picture)
    shown = [(e["lines"], e["start"], e["end"]) for e in entries if e["state"] == "cue"]
    assert shown == [(["CARD"], 50_000, 51_000), (["SORTIE"], 51_000, 51_800)]
    # Two one-frame cards 1 s apart before a line at 52 s: both show.
    timing = _two_timing_cues(52_000)
    picture = {"readings": [_next(_reading("ONE", 50_000, 50_000), 51_000), _next(_reading("TWO", 51_000, 51_000), 52_000)]}
    entries, _ = prepare.on_screen(timing, [], [], picture)
    assert [(e["lines"], e["state"], e["start"], e["end"]) for e in entries] == [
        (["ONE"], "cue", 50_000, 51_000),
        (["TWO"], "cue", 51_000, 52_000),
    ]


def test_a_sync_rebuild_never_lets_a_picture_cue_push_the_next_one_out():
    cue = lambda n, a, b: srt.Cue(n=n, start=a, end=b, ts="", lines=["x"])  # noqa: E731

    def entry(a: int, seen: int, shown: int) -> dict:
        return {"evidence": prepare.PICTURE, "state": "cue", "start": a, "end": shown, "found": [a, seen], "shown_end": shown}

    one, two = entry(50_000, 50_700, 51_500), entry(51_000, 51_700, 52_500)
    merged = [(cue(1, 10_000, 12_000), None), (None, one), (None, two), (cue(2, 52_000, 54_000), None)]
    prepare._fit_picture_entries(merged, True, {1, 2})
    assert (one["state"], one["start"], one["end"]) == ("cue", 50_000, 51_000)
    assert (two["state"], two["start"], two["end"]) == ("cue", 51_000, 52_000)


def test_a_sync_rebuild_keeps_where_a_picture_cue_aims_to_end(tmp_path: Path):
    w, _ = _screen_film(tmp_path)
    reading = _next(_reading("THE END", *TAIL_TEXT, kind="closing text"), TAIL_TEXT[1] + 1_500)
    _build_screen(tmp_path, w, _picture(w, [(TAIL_TEXT[0], [])], [], [reading]))
    e = _entries(w)[f"picture:{TAIL_TEXT[0]}"]
    assert (e["start"], e["end"], e["found"], e["shown_end"]) == (
        TAIL_TEXT[0],
        TAIL_TEXT[1] + 1_500,
        list(TAIL_TEXT),
        TAIL_TEXT[1] + 1_500,
    )
    timing = tmp_path / "en.srt"
    prepare.build(w, _shifted(tmp_path, timing, 2_000), None, None, keep_bible_check=True, shift_ms=2_000)
    e = _entries(w)[f"picture:{TAIL_TEXT[0]}"]
    assert (e["state"], e["start"], e["end"], e["found"]) == ("cue", TAIL_TEXT[0], TAIL_TEXT[1] + 1_500, list(TAIL_TEXT))
    # An entry from an older work folder has no shown_end: its seen span.
    rows = _json(w / prepare.ON_SCREEN_FILE)
    for r in rows:
        r.pop("shown_end", None)
    (w / prepare.ON_SCREEN_FILE).write_text(json.dumps(rows), encoding="utf-8")
    prepare.build(w, _shifted(tmp_path, timing, 2_000), None, None, keep_bible_check=True, shift_ms=2_000)
    e = _entries(w)[f"picture:{TAIL_TEXT[0]}"]
    assert (e["state"], e["start"], e["end"]) == ("cue", *TAIL_TEXT)


def test_screen_and_shift_do_not_go_together(tmp_path: Path):
    with pytest.raises(SystemExit):
        prepare.build(tmp_path / "w", _film(tmp_path, "en.srt", "Line"), None, None, shift_ms=10, screen_path=tmp_path / "r.json")


# --- the sync rebuild and the report -----------------------------------------


def _shifted(tmp: Path, path: Path, ms: int) -> Path:
    out = tmp / f"shifted_{ms}_{path.name}"
    srt.write(out, srt.shift(srt.parse(path)[0], ms))
    return out


def test_a_picture_entry_keeps_its_times_and_number_in_a_shift_rebuild(tmp_path: Path):
    w, _ = _screen_film(tmp_path)
    path = _picture(w, [(TAIL_TEXT[0], [])], [], [_reading("THE END", *TAIL_TEXT, kind="closing text")])
    _build_screen(tmp_path, w, path)
    before = _json(w / "cues.json")
    timing = tmp_path / "en.srt"
    for shift, state in ((12_000, "cue"), (14_000, "left_out"), (14_000, "left_out"), (2_000, "cue")):
        prepare.build(w, _shifted(tmp_path, timing, shift), None, None, keep_bible_check=True, shift_ms=shift)
        rows = _json(w / "cues.json")
        assert [r["n"] for r in rows] == [r["n"] for r in before]
        e = _entries(w)[f"picture:{TAIL_TEXT[0]}"]
        assert e["state"] == state and e["n"] == LINES + 1 and e["found"] == list(TAIL_TEXT)
        last_line = LAST_END + shift
        if state == "cue":
            assert (e["start"], e["end"]) == (max(TAIL_TEXT[0], last_line), TAIL_TEXT[1])
            assert "left_out" not in rows[-1]
        else:
            # The last line now covers it: clipped into its slot after that
            # line, and left out.
            assert e["reason"] == prepare.UNDER_TIMING and (e["start"], e["end"]) == (last_line, TAIL_TEXT[1])
            assert rows[-1]["left_out"] == prepare.UNDER_TIMING and rows[-1]["start"] >= rows[-2]["start"]
    # The track entries still move with the shift.
    card = next(e for e in _entries(w).values() if e["lines"] == ["UN JOUR"])
    assert card["start"] == CARD[0] + 2_000


def test_a_reading_under_the_unshifted_timing_is_placed_by_the_shift_rebuild(tmp_path: Path):
    # The timing file is 2 s late: before the sync rebuild its first line
    # (10.0-12.5 s) covers a card shown at 10.6-11.9 s on the video.
    w, _ = _screen_film(tmp_path)
    card = (10_600, 11_900)
    path = _picture(w, [(card[0], [])], [], [_reading("A CARD", *card, kind="title card")])
    _build_screen(tmp_path, w, path)
    e = _entries(w)[f"picture:{card[0]}"]
    assert (e["state"], e["reason"], e["n"], e["found"]) == ("left_out", prepare.UNDER_TIMING, 2, list(card))
    before = [r["n"] for r in _json(w / "cues.json")]
    timing = tmp_path / "en.srt"
    for shift, state in ((-2_000, "cue"), (0, "left_out"), (-2_000, "cue")):
        prepare.build(w, _shifted(tmp_path, timing, shift), None, None, keep_bible_check=True, shift_ms=shift)
        rows = _json(w / "cues.json")
        assert [r["n"] for r in rows] == before
        e = _entries(w)[f"picture:{card[0]}"]
        assert e["state"] == state and e["n"] == 2 and e["found"] == list(card)
        # The report's counts follow the rebuild.
        info = _json(w / "build.json")["on_screen"]["picture"]
        under = int(state == "left_out")
        assert (info["readings_already_in_timing"], info["found"]) == (under, 1 - under)
        if state == "cue":
            # Shifted, the first line ends at 10.5 s and the second starts
            # at 12.0 s: the card fits between them at its own times.
            assert (e["start"], e["end"]) == card and "left_out" not in rows[1]
        else:
            assert e["reason"] == prepare.UNDER_TIMING and rows[1]["left_out"] == prepare.UNDER_TIMING


def test_an_early_timing_file_shows_a_card_at_its_own_time_before_a_lower_number(tmp_path: Path):
    # The timing file is 2 s early. Before the shift, line A (11.5-13.5 s)
    # covers a card shown at 12.0-13.0 s on the video, so the card's number
    # comes after A's. After the +2 s shift A is at 13.5-15.5 s and the card
    # has room at its own time: it is shown there, before A, and every cue
    # keeps its number.
    w = tmp_path / "work"
    lines = [(11_500, 13_500, "Line A.")] + [(20_000 + k * 4_000, 22_500 + k * 4_000, f"Line {k + 2}.") for k in range(40)]
    timing = tmp_path / "en.srt"
    timing.write_text(
        "".join(f"{i}\n{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(lines, 1)), encoding="utf-8"
    )
    (w / "screen").mkdir(parents=True)
    card = (12_000, 13_000)
    path = _picture(w, [(card[0], [])], [], [_reading("THREE YEARS LATER", *card, kind="caption")])
    prepare.build(w, timing, None, None, timing_language="en", screen_path=path)
    e = _entries(w)[f"picture:{card[0]}"]
    assert (e["state"], e["reason"], e["n"]) == ("left_out", prepare.UNDER_TIMING, 2)
    before = [(r["n"], r["source"]) for r in _json(w / "cues.json")]
    # The bible's files cite cue numbers: the rebuild keeps them as they are.
    cited = {"decisions.json": '[{"cues": [1, 2, 3]}]', prepare.SONGS_FILE: '{"songs": [[3, 4]]}', "judged.json": "[2]"}
    for name, text in cited.items():
        (w / name).write_text(text, encoding="utf-8")
    prepare.build(w, _shifted(tmp_path, timing, 2_000), None, None, keep_bible_check=True, shift_ms=2_000)
    rows = _json(w / "cues.json")
    assert [(r["n"], r["source"]) for r in rows] == before
    assert all((w / name).read_text(encoding="utf-8") == text for name, text in cited.items())
    assert (rows[0]["start"], rows[0]["end"]) == (13_500, 15_500)
    e = _entries(w)[f"picture:{card[0]}"]
    assert (e["state"], e["n"], e["found"], (e["start"], e["end"])) == ("cue", 2, list(card), card) and "reason" not in e
    assert "left_out" not in rows[1] and (rows[1]["start"], rows[1]["end"]) == card
    info = _json(w / "build.json")["on_screen"]["picture"]
    assert (info["readings_already_in_timing"], info["found"]) == (0, 1)
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{r['n']}\n{r['n']}. satır.\n\n" for r in rows if not prepare.left_out(r))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0

    def in_time_order(cues: list[srt.Cue]) -> bool:
        return all(a.end <= b.start for a, b in zip(cues, cues[1:]))

    # The draft is in time order: the card, then A, then the rest.
    draft = srt.parse(w / "draft.tr.srt")[0]
    assert in_time_order(draft) and (draft[0].start, draft[0].end, draft[0].lines) == (*card, ["2. satır."])
    assert (draft[1].start, draft[1].lines) == (13_500, ["1. satır."])
    cue_map = _json(w / assemble.MAP_FILE)["cues"]
    assert (cue_map["1"], cue_map["2"], cue_map["3"]) == ({"cue": 2}, {"cue": 1}, {"cue": 3})
    assert [(x["cue"], x["delivered"], x["at"]) for x in assemble.where(w, [1, 2])] == [
        (1, [2], ["00:00:13,500"]),
        (2, [1], ["00:00:12,000"]),
    ]
    report = assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False)["on_screen"]
    shown = srt.parse(tmp_path / "Film.srt")[0]
    assert in_time_order(shown)
    # The opening credit ends before the card, the first cue shown.
    [hello] = [c for c in shown if c.start < card[0]]
    assert hello.end <= card[0] and shown[1].lines == ["2. satır."] and shown[2].lines == ["1. satır."]
    delivered_map = _json(w / assemble.DELIVERED_MAP_FILE)["cues"]
    assert (delivered_map["2"], delivered_map["3"]) == ({"cue": 2}, {"cue": 1})
    assert [(x["cue"], x["delivered"], x["at"]) for x in assemble.where(w, [1, 2])] == [
        (1, [3], ["00:00:13,500"]),
        (2, [2], ["00:00:12,000"]),
    ]
    assert report["no_room_after_shift"] == []
    assert report["delivered"] == [{"cue": [2], "at": "00:00:12,000", "text": "THREE YEARS LATER", "turkish": "2. satır."}]
    # The listeners read the cues in time order too, as check does: the
    # card runs on into line A, the cue shown after it, not into line 2.
    listen = Path(assemble.listen_parts(w, size=50)["parts"][0]["file"]).read_text(encoding="utf-8").splitlines()
    head = listen[0].split("\t")
    group = {r[0]: r[head.index("group")] for r in (x.split("\t") for x in listen[1:])}
    assert group["2"] == group["1"] == "2-1" and group["3"] == ""


def test_a_sound_only_cue_the_shift_moves_onto_a_card_leaves_it_its_room(tmp_path: Path):
    # The early-subtitles case with a sound description before line A.
    # After the +2 s shift "[door creaks]" sits at 11.6-12.4 s, on the
    # card's own time, but a cue that holds only sounds is never shown, so
    # the card keeps its room there, as in the first build.
    w = tmp_path / "work"
    lines = [(9_600, 10_400, "[door creaks]"), (11_500, 13_500, "Line A.")]
    lines += [
        (20_000 + k * 4_000, 22_500 + k * 4_000, f"[wind] Line {k + 3}." if k % 3 == 0 else f"Line {k + 3}.") for k in range(40)
    ]
    timing = tmp_path / "en.srt"
    timing.write_text(
        "".join(f"{i}\n{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(lines, 1)), encoding="utf-8"
    )
    (w / "screen").mkdir(parents=True)
    card = (12_000, 13_000)
    path = _picture(w, [(card[0], [])], [], [_reading("THREE YEARS LATER", *card, kind="caption")])
    prepare.build(w, timing, None, None, timing_language="en", screen_path=path)
    assert _entries(w)[f"picture:{card[0]}"]["reason"] == prepare.UNDER_TIMING
    before = [(r["n"], r["source"]) for r in _json(w / "cues.json")]
    prepare.build(w, _shifted(tmp_path, timing, 2_000), None, None, keep_bible_check=True, shift_ms=2_000)
    rows = _json(w / "cues.json")
    assert [(r["n"], r["source"]) for r in rows] == before
    assert rows[0]["sound_only"] and (rows[0]["start"], rows[0]["end"]) == (11_600, 12_400)
    e = _entries(w)[f"picture:{card[0]}"]
    assert (e["state"], e["n"], (e["start"], e["end"])) == ("cue", 3, card) and "reason" not in e
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{r['n']}\n{r['n']}. satır.\n\n" for r in rows if not prepare.left_out(r))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    draft = srt.parse(w / "draft.tr.srt")[0]
    assert [(c.start, c.lines) for c in draft[:2]] == [(card[0], ["3. satır."]), (13_500, ["2. satır."])]


def test_an_early_timing_file_leaves_a_card_with_no_room_at_its_own_time_out_and_lists_it(tmp_path: Path):
    # The timing file is 2 s early. Before the shift, line A (10.65-12.65 s)
    # covers a card shown at 12.0-12.8 s. After the +2 s shift A starts at
    # 12.65 s: too little of the card under it to cover it, and 0.65 s of
    # room at the card's own time, under the shortest a cue is shown.
    w = tmp_path / "work"
    lines = [(10_650, 12_650, "Line A.")] + [(20_000 + k * 4_000, 22_500 + k * 4_000, f"Line {k + 2}.") for k in range(40)]
    timing = tmp_path / "en.srt"
    timing.write_text(
        "".join(f"{i}\n{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(lines, 1)), encoding="utf-8"
    )
    (w / "screen").mkdir(parents=True)
    card = (12_000, 12_800)
    path = _picture(w, [(card[0], [])], [], [_reading("THREE YEARS LATER", *card, kind="caption")])
    prepare.build(w, timing, None, None, timing_language="en", screen_path=path)
    assert _entries(w)[f"picture:{card[0]}"]["reason"] == prepare.UNDER_TIMING
    before = [(r["n"], r["source"]) for r in _json(w / "cues.json")]
    prepare.build(w, _shifted(tmp_path, timing, 2_000), None, None, keep_bible_check=True, shift_ms=2_000)
    rows = _json(w / "cues.json")
    assert [(r["n"], r["source"]) for r in rows] == before
    e = _entries(w)[f"picture:{card[0]}"]
    assert (e["state"], e["reason"], e["n"], e["found"]) == ("left_out", prepare.NO_ROOM_SHIFT, 2, list(card))
    assert rows[1]["left_out"] == prepare.NO_ROOM_SHIFT
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{r['n']}\n{r['n']}. satır.\n\n" for r in rows if not prepare.left_out(r))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    report = assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False)["on_screen"]
    assert report["no_room_after_shift"] == [{"at": "00:00:12,000", "text": "THREE YEARS LATER"}]
    # One time for the card everywhere in the report: the video's.
    [looked] = [x for x in report["picture"]["looked_at"] if x["text"] == "THREE YEARS LATER"]
    assert (looked["at"], looked["reason"]) == ("00:00:12,000", prepare.NO_ROOM_SHIFT)
    assert prepare.NO_ROOM_SHIFT not in report["left_out"] and report["delivered"] == []
    assert all(x["text"] != "THREE YEARS LATER" for x in report["left_out_at_ends"])


def test_every_left_out_value_a_row_can_hold_has_a_note(tmp_path: Path):
    w, _ = _screen_film(tmp_path)
    # One frame: 0.7 s on screen. Shifted 11.6 s, the last line ends 0.1 s
    # into it: too little to cover it, too much to leave it room.
    path = _picture(w, [(TAIL_TEXT[0], [])], [], [_reading("THE END", TAIL_TEXT[0], TAIL_TEXT[0], kind="closing text")])
    _build_screen(tmp_path, w, path)
    prepare.build(w, _shifted(tmp_path, tmp_path / "en.srt", 11_600), None, None, keep_bible_check=True, shift_ms=11_600)
    rows = _json(w / "cues.json")
    assert {r["left_out"] for r in rows if r.get("left_out")} <= set(assemble.LEFT_OUT_NOTES)
    # A Turkish line for the left-out card is rejected with its note.
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{r['n']}\n{r['n']}. satır.\n\n" for r in rows)
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0, r["hard"]
    [note] = [x for x in r["warnings"] if x["cue"] == LINES + 1]
    assert "no room after the timing shift" in note["detail"]


def test_deliver_reports_what_the_picture_looked_at(tmp_path: Path):
    w, ids = _screen_film(tmp_path)
    card, middle = ids["UN JOUR"], ids["Hé!"]
    frames = [(1_500, [card]), (152_000, [middle]), (TAIL_TEXT[0], [])]
    readings = [_reading("ONE DAY", 1_500, 1_500, shows=[card]), _reading("THE END", *TAIL_TEXT, kind="closing text")]
    path = _picture(w, frames, [card, middle, ids["Sortie"]], readings)
    _build_screen(tmp_path, w, path)
    rows = _json(w / "cues.json")
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{r['n']}\n{r['n']}. satır.\n\n" for r in rows if not prepare.left_out(r))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    report = assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False)["on_screen"]
    pic = report["picture"]
    assert pic["frames"] == 3 and pic["frames_not_read"] == [] and pic["notes"] == ["a note"]
    assert [(x["text"], x["state"], x["reason"], x["picture"]) for x in pic["looked_at"]] == [
        ("UN JOUR", "cue", None, "shown"),
        ("Hé!", "left_out", prepare.NOT_CONFIRMED, "not shown"),
        ("Sortie", "left_out", prepare.NOT_CHECKED, "not read"),
        ("THE END", "cue", None, "found"),
    ]
    assert [x["text"] for x in report["delivered"]] == ["UN JOUR", "THE END"]


# --- too few languages: the picture decides ----------------------------------


def test_entries_shown_in_too_few_languages_are_unsure_whatever_the_count():
    few = {**_unsure_entry(0), "texts": {"fr": ["x"], "es": ["x"]}, "reason": prepare.FEW_LANGUAGES}
    one = _unsure_entry(1)
    many = ["de", "es", "fr", "it", "nl", "pl"]
    assert screen.unsure_ids([few, one], many) == [few["id"]]
    assert screen.unsure_ids([few, one], ["fr"]) == [few["id"], one["id"]]
    # Marked unsure by an earlier run, it stays unsure.
    again = {k: v for k, v in few.items() if k != "reason"} | {"state": "unsure"}
    assert screen.unsure_ids([again], many) == [few["id"]]


MANY = ["fr", "es", "de", "it", "nl", "pl", "sv", "fi"]


def _many_build(tmp: Path, picture: Path | None = None) -> Path:
    """Eight other languages, five of which show a sign mid-film."""
    w = tmp / "work"
    tracks = [(lang, _film(tmp, f"{lang}.srt", "Ligne", [(*SIGN, "FARMACIA")] if k < 5 else [])) for k, lang in enumerate(MANY)]
    prepare.build(w, _film(tmp, "en.srt", "Line"), None, None, tracks=tracks, timing_language="en", screen_path=picture)
    return w


@pytest.mark.parametrize(
    "kind, wants, state",
    [("sign", True, "cue"), ("background", False, "left_out")],
)
def test_the_picture_brings_back_a_story_sign_too_few_languages_show(tmp_path: Path, kind: str, wants: bool, state: str):
    w = _many_build(tmp_path)
    (sign,) = _entries(w).values()
    assert sign["reason"] == prepare.FEW_LANGUAGES
    rows = _json(w / "cues.json")
    plan = screen.plan_frames(rows, [sign], _json(w / "build.json")["on_screen"]["other_languages"], 600_000)
    assert plan["unsure"] == [sign["id"]]
    path = _picture(
        w,
        [(201_000, [sign["id"]])],
        [sign["id"]],
        [_reading("PHARMACY", 201_000, 201_000, kind=kind, wants=wants, shows=[sign["id"]])],
    )
    _many_build(tmp_path, path)
    assert _entries(w)[sign["id"]]["state"] == state


def test_a_story_reading_of_a_credit_group_takes_the_cards_text(tmp_path: Path):
    # The first track shows its subtitle credit while six others show a
    # sign at the same time: the group is a credit, and when the frames
    # show the sign as story text the cue carries the sign, not the credit.
    timing = srt.parse(_film(tmp_path, "en.srt", "Line"))[0]
    eu = _film(tmp_path, "eu.srt", "Lerroa", [(*SIGN, "Azpitituluak: Jon")])
    signs = [(lang, _film(tmp_path, f"{lang}.srt", "Ligne", [(*SIGN, "FARMACIA")])) for lang in MANY[:6]]
    (credit,), _ = prepare.on_screen(timing, [("eu", eu), *signs], [], timing_language="en")
    assert credit["reason"] == prepare.CREDIT and credit["lines"] == ["FARMACIA"]
    (cue,), _ = prepare.on_screen(timing, [("eu", eu), *signs], [], picture={"story": [credit["id"]]}, timing_language="en")
    assert cue["state"] == "cue" and cue["lines"] == ["FARMACIA"]
