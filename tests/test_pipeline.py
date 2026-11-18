"""End-to-end over the scripts with a tiny fake film: build, chunk,
translate (by hand), check, review file, deliver, learn."""

import hashlib
import json
import os
from pathlib import Path

import pytest

import assemble
import learn
import prepare
import srt

FR = """1
00:00:01,000 --> 00:00:03,000
SANDRA: Viens.

2
00:00:03,500 --> 00:00:06,000
<i>Il fait froid.</i>

3
00:00:07,000 --> 00:00:09,000
- Ça va ?
- Oui.

4
00:00:12,000 --> 00:00:14,000
D'accord.
"""

EN = """1
00:00:01,100 --> 00:00:02,900
SANDRA: Come.

2
00:00:03,600 --> 00:00:05,900
<i>It's cold.</i>

3
00:00:07,000 --> 00:00:09,000
- OK?
- Yes.

4
00:00:12,000 --> 00:00:14,000
Okay.
"""

GOOD = "1\nGel.\n\n2\n<i>Hava soğuk.</i>\n\n3\n- İyi misin?\n- Evet.\n\n4\nTamam.\n"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "fr.srt").write_text(FR, encoding="utf-8")
    (tmp_path / "en.srt").write_text(EN, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, tmp_path / "en.srt")
    prepare.chunks(w, target=250)
    return w


def test_build_pairs_english_and_finds_speaker(work: Path):
    rows = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    # The label leaves the text and stays as the speaker hint.
    assert rows[0]["source"] == ["Viens."]
    assert rows[0]["en"] == ["Come."]
    speakers = json.loads((work / "speakers.json").read_text(encoding="utf-8"))
    assert speakers["1"]["label"] == "Sandra"
    chunk = (work / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    assert "#1 00:00:01 [Sandra]" in chunk and "src: - Ça va ? / - Oui." in chunk


def test_check_passes_and_writes_draft(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["warning_count"] == 0, r["warnings"]
    back, _ = srt.parse(work / "draft.tr.srt")
    # No cue reads above 17 a second, so none is shown longer: every cue
    # keeps its timestamp line exactly as the timing file writes it.
    assert r["extended_cues"] == 0
    assert [c.ts for c in back] == [c.ts for c in srt.parse(work / "timing.srt")[0]]


def test_check_hard_fails_and_warnings(work: Path):
    bad = "1\nGelmek.\n\n2\nHava soğuk.\n\n3\nİyi misin? Evet.\n\n4\nTAMAM.\n"
    (work / "out" / "tr_01.txt").write_text(bad, encoding="utf-8")
    r = assemble.run_checks(work)
    hard = {(x["cue"], x["check"]) for x in r["hard"]}
    assert (2, "italic tags") in hard and (3, "dialogue dashes") in hard
    warns = {(x["cue"], x["check"]) for x in r["warnings"]}
    assert (1, "infinitive command") in warns and (4, "caps") in warns


def test_a_listing_slash_in_the_turkish_is_a_hard_fail(work: Path):
    # Love Of Your Life: the listener wrote "var ya… / Oysa" back, the
    # " / " its listing puts between a cue's lines.
    leak = GOOD.replace("<i>Hava soğuk.</i>", "<i>Hava / soğuk.</i>").replace("Gel.", "Gel /")
    (work / "out" / "tr_01.txt").write_text(leak, encoding="utf-8")
    hard = {(x["cue"], x["check"]) for x in assemble.run_checks(work)["hard"]}
    assert {(1, "line-join slash"), (2, "line-join slash")} <= hard
    # A slash inside a word or a number is no listing slash.
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "7/24 açık."), encoding="utf-8")
    assert not [x for x in assemble.run_checks(work)["hard"] if x["check"] == "line-join slash"]


@pytest.mark.parametrize("side", ["source", "en"])
def test_a_slash_the_source_or_english_line_has_is_no_listing_slash(tmp_path: Path, side: str):
    # A score written "1 / 2" on screen is kept as it is.
    fr = FR.replace("D'accord.", "Score : 1 / 2.") if side == "source" else FR
    en = EN.replace("Okay.", "Score: 1 / 2.") if side == "en" else EN
    (tmp_path / "fr.srt").write_text(fr, encoding="utf-8")
    (tmp_path / "en.srt").write_text(en, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, tmp_path / "en.srt")
    (w / "out").mkdir(exist_ok=True)
    (w / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "Skor: 1 / 2."), encoding="utf-8")
    assert not [x for x in assemble.run_checks(w)["hard"] if x["check"] == "line-join slash"]


def test_position_tags_never_reach_the_draft(work: Path):
    tagged = GOOD.replace("Gel.", "{\\an8}Gel.").replace("4\nTamam.", "4\n{\\an8}\nTamam.")
    (work / "out" / "tr_01.txt").write_text(tagged, encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    draft = (work / "draft.tr.srt").read_text(encoding="utf-8")
    assert "{\\" not in draft and "\nGel.\n" in draft and "\nTamam.\n" in draft


def test_a_musical_is_delivered_without_music_notes(work: Path):
    sung = GOOD.replace("<i>Hava soğuk.</i>", "<i>♪ Hava soğuk ♪</i>")
    (work / "out" / "tr_01.txt").write_text(sung, encoding="utf-8")
    assemble.run_checks(work)
    assert "♪ Hava soğuk ♪" in (work / "draft.tr.srt").read_text(encoding="utf-8")
    (work / "songs.json").write_text(json.dumps({"musical": True, "keep": []}), encoding="utf-8")
    assemble.run_checks(work)
    draft = (work / "draft.tr.srt").read_text(encoding="utf-8")
    assert "♪" not in draft and "\n<i>Hava soğuk</i>\n" in draft


@pytest.mark.parametrize(
    ("lines", "bare"),
    [
        (
            ["<i>♪ Çok eskidendi</i>", "<i>Düşündüğünüzden de eski ♪</i>"],
            ["<i>Çok eskidendi</i>", "<i>Düşündüğünüzden de eski</i>"],
        ),
        (["♪ ♪", "- Kapat şunu!"], ["- Kapat şunu!"]),
        (["- ♪ La la ♪", "- Kapat!"], ["- La la", "- Kapat!"]),
    ],
)
def test_drop_music_notes(lines, bare):
    assert srt.drop_music_notes(lines) == bare


def test_missing_cue_blocks_draft(work: Path):
    (work / "out" / "tr_01.txt").write_text("1\nGel.\n", encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["draft"] is None
    assert sum(1 for x in r["hard"] if x["detail"] == "missing") == 3
    # The summary names every missing cue, not only the first 30 hard fails.
    assert assemble._summary(r)["missing_cues"] == [2, 3, 4]


def test_fix_files_override(work: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "TAMAM."), encoding="utf-8")
    (work / "out" / "fix_r1.txt").write_text("4\nTamam.\n", encoding="utf-8")
    assert assemble.run_checks(work)["warning_count"] == 0


def test_glossary_variant_warning(work: Path):
    (work / "glossary.json").write_text(json.dumps({"Tamam": ["Peki"]}), encoding="utf-8")
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "Peki."), encoding="utf-8")
    r = assemble.run_checks(work)
    assert [x["check"] for x in r["warnings"]] == ["term variant"]


def test_review_parts_hold_each_cue_once_with_its_notes(work: Path):
    (work / "out" / "tr_01.txt").write_text(
        GOOD.replace("Tamam.", "Tamam, tamam, olur, peki, anladım, söz veriyorum."), encoding="utf-8"
    )
    (work / "out" / "flags_01.txt").write_text("3: unsure who asks\n", encoding="utf-8")
    assemble.run_checks(work)
    res = work / "assemble-reviewparts.json"
    assemble.main(["--result", str(res), "reviewparts", "--work", str(work)])
    got = json.loads(res.read_text(encoding="utf-8"))
    assert [(p["part"], p["first"], p["last"], p["cues"]) for p in got["parts"]] == [("01", 1, 4, 4)]
    assert got["parts"][0]["write_to"] == str(work / "out" / "fix_review_01.txt")
    lines = Path(got["parts"][0]["file"]).read_text(encoding="utf-8").splitlines()
    assert lines[:3] == [
        "n\tspeaker\tsource\ten\tturkish\tnotes",
        "# --- your part: cues 1-4 ---",
        "1\tSandra\tViens.\tCome.\tGel.\t",
    ]
    assert lines[4].endswith("\ttranslator: unsure who asks")
    # Cue 4, the last, is shown half a second longer: over 2.5 s the
    # English reads at 2.0 characters a second, the Turkish at 19.6.
    assert "only the Turkish is fast" in lines[5] and got["turkish_only_fast"] == 1


def _film(tmp_path: Path, cues: int, pause_after: int) -> Path:
    """A film of `cues` one-second cues, half a second apart, with a long
    pause after cue `pause_after`."""
    blocks, t = [], 0
    for n in range(1, cues + 1):
        blocks.append(f"{n}\n{srt.fmt_ms(t)} --> {srt.fmt_ms(t + 1000)}\nLine {n}.\n")
        t += 1500 + (20_000 if n == pause_after else 0)
    src = tmp_path / "long.en.srt"
    src.write_text("\n".join(blocks), encoding="utf-8")
    w = tmp_path / "long"
    prepare.build(w, src, None, None)
    (w / "out").mkdir(exist_ok=True)
    (w / "out" / "tr_01.txt").write_text("".join(f"{n}\nSatır {n}.\n\n" for n in range(1, cues + 1)), encoding="utf-8")
    return w


def test_review_parts_cut_at_the_longest_pause_near_an_even_cut(tmp_path: Path):
    w = _film(tmp_path, 520, pause_after=180)
    parts = assemble.review_parts(w, size=250)["parts"]
    # 520 cues make three parts; the first cut moves from cue 173 to the pause.
    assert [(p["first"], p["last"]) for p in parts] == [(1, 180), (181, 347), (348, 520)]
    text = Path(parts[1]["file"]).read_text(encoding="utf-8").splitlines()
    assert text[1] == "# --- context before your part: read it, never change it ---"
    assert assemble.PART_CONTEXT == 20
    assert text[2].startswith("161\t") and text[22] == "# --- your part: cues 181-347 ---"
    assert text[-21] == "# --- context after your part: read it, never change it ---" and text[-1].startswith("367\t")


def test_review_parts_never_leave_a_part_empty_when_cut_windows_overlap(tmp_path: Path):
    # 101 cues in parts of 50 make three parts with even cuts 34 cues apart,
    # so the windows around them overlap; both reach the one long pause.
    w = _film(tmp_path, 101, pause_after=50)
    parts = assemble.review_parts(w, size=50)["parts"]
    spans = [(p["first"], p["last"]) for p in parts]
    assert len(spans) == 3 and all(p["cues"] > 0 for p in parts)
    assert spans[0][0] == 1 and spans[-1][1] == 101
    assert all(b[0] == a[1] + 1 for a, b in zip(spans, spans[1:]))
    assert spans[0][1] == 50


def test_review_parts_mark_a_chunk_join_on_a_part_s_first_cue(tmp_path: Path):
    w = _film(tmp_path, 520, pause_after=180)
    # The translators' second chunk starts on cue 181, where part 2 starts.
    (w / "chunks.json").write_text(json.dumps([{"first": 1}, {"first": 181}]), encoding="utf-8")
    parts = assemble.review_parts(w, size=250)["parts"]
    assert parts[1]["first"] == 181
    for p, before in ((parts[0], "# --- context after your part"), (parts[1], "# --- your part: cues 181-347 ---")):
        text = Path(p["file"]).read_text(encoding="utf-8").splitlines()
        i = text.index("# --- chunk join before cue 181 ---")
        assert text[i - 1].startswith(before) and text[i + 1].startswith("181\t")


def test_review_parts_keep_only_the_notes_a_reviewer_acts_on(tmp_path: Path):
    w = _film(tmp_path, 10, pause_after=5)
    warn = [
        {"check": "reading speed", "cue": 2, "detail": "21.0 chars/s, source 9.0; only the Turkish is fast"},
        {"check": "reading speed", "cue": 3, "detail": "21.0 chars/s, source 20.0"},
        {"check": "term drift", "cue": 4, "detail": "x" * 300},
        {"check": "spelling", "cue": 5, "detail": "same"},
        {"check": "spelling", "cue": 5, "detail": "same"},
    ]
    (w / "checks.json").write_text(json.dumps({"hard": [], "warnings": warn}), encoding="utf-8")
    rows = {
        ln.split("\t")[0]: ln.split("\t")[5]
        for ln in Path(assemble.review_parts(w)["parts"][0]["file"]).read_text(encoding="utf-8").splitlines()[2:]
    }
    # Only the Turkish is fast on cue 2: the reviewer can shorten it. On cue
    # 3 the source is fast too, so there is nothing new to do.
    assert "only the Turkish is fast" in rows["2"] and rows["3"] == ""
    assert len(rows["4"]) == assemble.NOTE_CHARS and rows["4"].endswith("…")
    assert rows["5"] == "spelling: same"


def test_reviews_join_the_parts_notes_and_name_the_missing(tmp_path: Path):
    w = _film(tmp_path, 300, pause_after=150)
    parts = assemble.review_parts(w, size=250)["parts"]
    Path(parts[0]["notes_to"]).write_text("Changed 3 cues: meaning 12, 40.\n", encoding="utf-8")
    Path(parts[0]["write_to"]).write_text("12\nSatır on iki.\n", encoding="utf-8")
    got = assemble.join_reviews(w)
    assert got["notes_missing"] == ["02"] and got["fix_files"] == ["fix_review_01.txt"]
    assert "## Part 01\n\nChanged 3 cues: meaning 12, 40." in (w / "review.md").read_text(encoding="utf-8")
    assert assemble.load_translation(w)[0][12] == ["Satır on iki."]
    # A new cut starts afresh: the parts' old fixes and notes are gone.
    assemble.review_parts(w, size=250)
    assert not list((w / "out").glob("fix_review_*.txt")) and not Path(parts[0]["notes_to"]).exists()


def test_deliver_backs_up_and_learn_finds_swaps(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Evet.", "Peki.").replace("Tamam.", "Peki."), encoding="utf-8")
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    dest.write_text("old", encoding="utf-8")
    backups = tmp_path / "backups"
    info = assemble.deliver(work, dest, backups, force=False)
    assert Path(info["backup_of_old_file"]).read_text(encoding="utf-8") == "old"
    assert not (work / "chunks").exists()

    films = tmp_path / "data" / "films"
    films.mkdir(parents=True)
    assert learn.scan(tmp_path / "data") == []
    work.rename(films / "film")
    w2 = films / "film"
    assert learn.scan(tmp_path / "data") == []
    text = dest.read_text(encoding="utf-8").replace("Peki.", "Tamam.").replace("Gel.", "Gel buraya.")
    dest.write_bytes(text.replace("\n", "\r\n").encode())
    assert [x["file"] for x in learn.scan(tmp_path / "data")] == [str(dest)]
    d = learn.diff(w2)
    assert d["cues_edited"] == 3
    assert d["repeated_swaps"] == [{"from": "Peki", "to": "Tamam", "count": 2, "cues": [3, 4]}]
    learn.mark_learned(w2)
    assert learn.scan(tmp_path / "data") == []


def _delivered(films: Path, name: str, dest: Path, text: str, when: str) -> Path:
    work = films / name
    work.mkdir(parents=True)
    (work / "delivered.tr.srt").write_text(text, encoding="utf-8")
    info = {"delivered_to": str(dest), "sha256": hashlib.sha256(text.encode()).hexdigest(), "delivered_at": when}
    (work / "delivered.json").write_text(json.dumps(info), encoding="utf-8")
    return work


def test_learn_scan_ignores_a_file_a_later_run_replaced(tmp_path: Path):
    films = tmp_path / "data" / "films"
    dest = tmp_path / "Film.tr.srt"
    _delivered(films, "film-old", dest, "first run", "2026-11-10T10:00:00")
    newer = _delivered(films, "film-new", dest, "second run", "2026-11-11T10:00:00")
    dest.write_text("second run", encoding="utf-8")
    assert learn.scan(tmp_path / "data") == []
    dest.write_text("second run, edited", encoding="utf-8")
    assert learn.scan(tmp_path / "data") == [{"work": str(newer), "file": str(dest)}]


def test_learn_scan_still_lists_each_film_of_its_own(tmp_path: Path):
    films = tmp_path / "data" / "films"
    a, b = tmp_path / "A.tr.srt", tmp_path / "B.tr.srt"
    _delivered(films, "a", a, "A", "2026-11-10T10:00:00")
    _delivered(films, "b", b, "B", "2026-11-11T10:00:00")
    a.write_text("A edited", encoding="utf-8")
    b.write_text("B edited", encoding="utf-8")
    assert [x["file"] for x in learn.scan(tmp_path / "data")] == [str(a), str(b)]


def test_deliver_writes_utf8_with_a_bom(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    info = assemble.deliver(work, dest, tmp_path / "backups", force=False)
    data = dest.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf") and not data.startswith(b"\xef\xbb\xbf" * 2)
    assert "Hava soğuk." in data[3:].decode("utf-8")
    assert info["old_file"] is None and info["backup_of_old_file"] is None
    # learn compares the file next to the video with these bytes.
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    assert (work / "delivered.tr.srt").read_bytes() == data
    assert srt.parse(dest)[0][0].text == "Gel."


ENGLISH = "1\n00:00:01,000 --> 00:00:02,000\nCome here.\n\n2\n00:00:03,000 --> 00:00:04,000\nIt's cold.\n"
TURKISH = "1\n00:00:01,000 --> 00:00:02,000\nBuraya gel.\n\n2\n00:00:03,000 --> 00:00:04,000\nIşık soğuk.\n"


def test_deliver_backs_up_an_english_file_with_the_videos_name(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    dest.write_text(ENGLISH, encoding="utf-8")
    info = assemble.deliver(work, dest, tmp_path / "backups", force=False)
    assert info["old_file"] == "not Turkish"
    backup = Path(info["backup_of_old_file"])
    assert backup.parent == tmp_path / "backups" and backup.read_text(encoding="utf-8") == ENGLISH
    assert json.loads((work / "delivered.json").read_text(encoding="utf-8"))["old_file"] == "not Turkish"


def test_deliver_names_a_turkish_file_and_its_own_earlier_delivery(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    dest.write_text(TURKISH, encoding="utf-8")
    assert assemble.deliver(work, dest, tmp_path / "backups", force=False)["old_file"] == "Turkish"
    assemble.run_checks(work)
    assert assemble.deliver(work, dest, tmp_path / "backups", force=False)["old_file"] == "earlier delivery"


def test_deliver_takes_an_english_file_at_its_own_path_as_not_turkish(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    assemble.deliver(work, dest, tmp_path / "backups", force=False)
    # The user puts an English file in its place to watch in English.
    dest.write_text(ENGLISH, encoding="utf-8")
    assemble.run_checks(work)
    info = assemble.deliver(work, dest, tmp_path / "backups", force=False)
    assert info["old_file"] == "not Turkish"
    assert Path(info["backup_of_old_file"]).read_text(encoding="utf-8") == ENGLISH


def test_deliver_keeps_the_pre_062_name_as_an_earlier_delivery(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(work)
    old, new = tmp_path / "Film.tr.srt", tmp_path / "Film.srt"
    assemble.deliver(work, old, tmp_path / "backups", force=False)
    assemble.run_checks(work)
    info = assemble.deliver(work, new, tmp_path / "backups", force=False)
    assert info["earlier_deliveries"] == [str(old)]
    # A third run to the same name keeps the old one and does not list
    # the current one twice.
    assemble.run_checks(work)
    info = assemble.deliver(work, new, tmp_path / "backups", force=False)
    assert info["earlier_deliveries"] == [str(old)] and info["old_file"] == "earlier delivery"


def test_learn_scan_finds_new_and_pre_062_deliveries(tmp_path: Path):
    films = tmp_path / "data" / "films"
    old, new = tmp_path / "Old.tr.srt", tmp_path / "New.srt"
    _delivered(films, "old", old, "old run", "2026-11-10T10:00:00")
    _delivered(films, "new", new, "﻿new run", "2026-11-13T10:00:00")
    old.write_text("old run, edited", encoding="utf-8")
    new.write_text("﻿new run, edited", encoding="utf-8")
    assert [x["file"] for x in learn.scan(tmp_path / "data")] == [str(new), str(old)]


def test_deliver_refuses_hard_fails(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("<i>Hava soğuk.</i>", "Hava soğuk."), encoding="utf-8")
    assemble.run_checks(work)
    with pytest.raises(SystemExit):
        assemble.deliver(work, tmp_path / "x.tr.srt", tmp_path / "b", force=False)
    assemble.deliver(work, tmp_path / "x.tr.srt", tmp_path / "b", force=True)


def _touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def test_post_review_fix_wins_over_review(work: Path):
    out = work / "out"
    (out / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    # The reviewer breaks cue 2's italics; a later fix round repairs it. The
    # later file must win even though its name sorts before fix_review.txt.
    (out / "fix_review.txt").write_text("2\nHava soğuk.\n", encoding="utf-8")
    (out / "fix_r3_01.txt").write_text("2\n<i>Hava soğuk.</i>\n", encoding="utf-8")
    t = (out / "tr_01.txt").stat().st_mtime
    _touch(out / "fix_review.txt", t + 10)
    _touch(out / "fix_r3_01.txt", t + 20)
    assert assemble.run_checks(work)["hard_fail_count"] == 0


@pytest.mark.parametrize("review_last", [True, False])
def test_review_wins_over_the_polish_fix_and_loses_to_later_rounds(work: Path, review_last: bool):
    out = work / "out"
    for name in ("tr_00.txt", "fix_polish.txt", "fix_review.txt", "fix_soft.txt"):
        (out / name).write_text("1\nx\n", encoding="utf-8")
    t = (out / "tr_00.txt").stat().st_mtime
    # The fixer and the reviewer ran side by side; either can finish last.
    _touch(out / "fix_polish.txt", t + (10 if review_last else 20))
    _touch(out / "fix_review.txt", t + (20 if review_last else 10))
    _touch(out / "fix_soft.txt", t + 30)
    assert [p.name for p in assemble.fix_order(out)] == ["fix_polish.txt", "fix_review.txt", "fix_soft.txt"]
    # The review's parts count as the review.
    (out / "fix_review.txt").rename(out / "fix_review_02.txt")
    assert [p.name for p in assemble.fix_order(out)] == ["fix_polish.txt", "fix_review_02.txt", "fix_soft.txt"]
    (out / "fix_review_02.txt").rename(out / "fix_review.txt")
    # Without a review, the order is the writing order.
    (out / "fix_review.txt").unlink()
    assert [p.name for p in assemble.fix_order(out)] == ["fix_polish.txt", "fix_soft.txt"]


@pytest.mark.parametrize("review_last", [True, False])
def test_the_reviewers_text_is_checked_and_delivered_when_both_write_a_cue(work: Path, review_last: bool):
    out = work / "out"
    (out / "tr_00.txt").write_text(GOOD, encoding="utf-8")
    (out / "fix_polish.txt").write_text("4\nPeki.\n", encoding="utf-8")
    (out / "fix_review.txt").write_text("4\nOlur.\n", encoding="utf-8")
    t = (out / "tr_00.txt").stat().st_mtime
    _touch(out / "fix_polish.txt", t + (10 if review_last else 20))
    _touch(out / "fix_review.txt", t + (20 if review_last else 10))
    assert assemble.run_checks(work)["hard_fail_count"] == 0
    assert srt.parse(work / "draft.tr.srt")[0][-1].lines == ["Olur."]


def test_rebuild_drops_earlier_runs_files(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    (work / "out" / "fix_review.txt").write_text("4\nPeki.\n", encoding="utf-8")
    assemble.run_checks(work)
    assert (work / "draft.tr.srt").exists()
    prepare.build(work, tmp_path / "fr.srt", None, tmp_path / "en.srt")
    prepare.chunks(work, target=250)
    assert list((work / "out").iterdir()) == []
    assert not (work / "draft.tr.srt").exists() and not (work / "checks.json").exists()


def test_rebuild_drops_the_earlier_bible_check(work: Path, tmp_path: Path):
    names = prepare.BIBLE_CHECK_FILES
    assert "second.voices.json" in names and "questions.voices.json" in names
    for name in names:
        (work / name).write_text("{}", encoding="utf-8")
    prepare.build(work, tmp_path / "fr.srt", None, tmp_path / "en.srt")
    assert [n for n in names if (work / n).exists()] == []


def test_a_shift_rebuild_keeps_the_bible_check(work: Path, tmp_path: Path):
    # The early second reader may already have answered when the sync check
    # asks for a shift; a shift moves times, not cue numbers.
    for name in prepare.BIBLE_CHECK_FILES:
        (work / name).write_text("{}", encoding="utf-8")
    (work / "checks.json").write_text("{}", encoding="utf-8")
    prepare.build(work, tmp_path / "fr.srt", None, tmp_path / "en.srt", keep_bible_check=True)
    assert all((work / n).exists() for n in prepare.BIBLE_CHECK_FILES)
    assert not (work / "checks.json").exists()


def test_swap_retries_while_the_file_is_locked(tmp_path: Path, monkeypatch):
    tmp, path = tmp_path / "a.tmp", tmp_path / "a.txt"
    tmp.write_text("new", encoding="utf-8")
    path.write_text("old", encoding="utf-8")
    real, calls = os.replace, []

    def locked_twice(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("locked")
        real(src, dst)

    monkeypatch.setattr(prepare.os, "replace", locked_twice)
    monkeypatch.setattr(prepare.time, "sleep", lambda s: None)
    prepare._swap(tmp, path)
    assert len(calls) == 3 and path.read_text(encoding="utf-8") == "new" and not tmp.exists()


def test_swap_gives_up_after_the_last_try(tmp_path: Path, monkeypatch):
    calls = []

    def always_locked(src, dst):
        calls.append(1)
        raise PermissionError("locked")

    monkeypatch.setattr(prepare.os, "replace", always_locked)
    monkeypatch.setattr(prepare.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        prepare._swap(tmp_path / "a.tmp", tmp_path / "a.txt", tries=4)
    assert len(calls) == 4


def test_rechunking_replaces_files_in_place_and_drops_extra_ones(work: Path):
    folder = work / "chunks"
    (folder / "chunk_09.txt").write_text("old", encoding="utf-8")
    (work / "speakers.json").write_text(json.dumps({"1": {"voice": "V2"}}), encoding="utf-8")
    prepare.chunks(work, target=250)
    assert sorted(p.name for p in folder.iterdir()) == ["chunk_01.txt"]
    assert "[V2]" in (folder / "chunk_01.txt").read_text(encoding="utf-8")


def test_force_never_ships_a_stale_draft(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assert assemble.run_checks(work)["draft"]
    (work / "out" / "fix_review.txt").write_text("not a cue\nGel.\n", encoding="utf-8")
    r = assemble.run_checks(work)
    assert r["draft"] is None and not (work / "draft.tr.srt").exists()
    with pytest.raises(SystemExit):
        assemble.deliver(work, tmp_path / "x.tr.srt", tmp_path / "b", force=True)
    assert not (tmp_path / "x.tr.srt").exists()


def test_glossary_variant_that_differs_only_by_case(work: Path):
    (work / "glossary.json").write_text(json.dumps({"Tamam": ["TAMAM"]}), encoding="utf-8")
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assert assemble.run_checks(work)["warnings"] == []
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Tamam.", "TAMAM."), encoding="utf-8")
    checks = sorted(x["check"] for x in assemble.run_checks(work)["warnings"])
    assert checks == ["caps", "term variant"]


def test_deliver_refuses_edits_after_check(work: Path, tmp_path: Path):
    (work / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(work)
    late = work / "out" / "fix_late.txt"
    late.write_text("4\nPeki.\n", encoding="utf-8")
    _touch(late, (work / "checks.json").stat().st_mtime + 5)
    with pytest.raises(SystemExit, match="changed after the last check"):
        assemble.deliver(work, tmp_path / "x.tr.srt", tmp_path / "b", force=True)


def test_rebuild_with_another_timing_file_drops_old_speaker_labels(work: Path, tmp_path: Path):
    assert json.loads((work / "speakers.json").read_text(encoding="utf-8")) == {"1": {"label": "Sandra"}}
    other = "1\n00:00:00,500 --> 00:00:01,000\nMusique.\n\n2\n00:00:01,000 --> 00:00:03,000\nMARC: Viens.\n"
    (tmp_path / "other.srt").write_text(other, encoding="utf-8")
    prepare.build(work, tmp_path / "other.srt", None, None)
    assert json.loads((work / "speakers.json").read_text(encoding="utf-8")) == {"2": {"label": "Marc"}}


def test_check_warns_on_the_other_address_form(work: Path):
    decisions = {
        "characters": [{"name": "Sandra", "aliases": []}],
        "decisions": [
            {
                "id": "address:Sandra>Daniel",
                "kind": "address",
                "speaker": "Sandra",
                "listener": "Daniel",
                "question": "Does Sandra say sen or siz to Daniel?",
                "answer": [{"from_cue": 1, "form": "siz"}],
                "evidence": [1],
                "confidence": "sure",
            }
        ],
    }
    (work / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    (work / "out" / "tr_01.txt").write_text(GOOD.replace("Gel.", "Sen gel."), encoding="utf-8")
    r = assemble.run_checks(work)
    assert [(w["cue"], w["check"]) for w in r["warnings"]] == [(1, "address form")]


def _films_work(tmp_path: Path) -> tuple[Path, Path]:
    """A checked work folder under plugins/data/<plugin>/films, as on disk."""
    (tmp_path / "fr.srt").write_text(FR, encoding="utf-8")
    (tmp_path / "en.srt").write_text(EN, encoding="utf-8")
    data = tmp_path / "plugins" / "data"
    w = data / "subtitle-it-subtitle-it" / "films" / "film-new"
    prepare.build(w, tmp_path / "fr.srt", None, tmp_path / "en.srt")
    (w / "out").mkdir(exist_ok=True)
    (w / "out" / "tr_01.txt").write_text(GOOD, encoding="utf-8")
    assemble.run_checks(w)
    return w, data


def test_deliver_with_the_video_moves_the_old_plugins_delivery_to_backups(tmp_path: Path):
    work, data = _films_work(tmp_path)
    film = tmp_path / "Film"
    film.mkdir()
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    old = film / "Film.tr.srt"
    old.write_text(TURKISH, encoding="utf-8")
    record = data / "turkish-subtitles-turkish-subtitles" / "films" / "film"
    record.mkdir(parents=True)
    (record / "delivered.json").write_text(json.dumps({"delivered_to": str(old)}), encoding="utf-8")
    # The user's own English file beside the video is no delivery: it stays.
    (film / "Film.en.srt").write_text(ENGLISH, encoding="utf-8")
    backups = tmp_path / "backups"
    info = assemble.deliver(work, film / "Film.srt", backups, force=False, video=video)
    [moved] = info["moved_earlier_deliveries"]
    assert moved["from"] == str(old) and not old.exists()
    assert Path(moved["to"]).parent == backups and Path(moved["to"]).read_text(encoding="utf-8") == TURKISH
    assert (film / "Film.en.srt").exists() and (film / "Film.srt").exists()
    assert info["earlier_deliveries"] == []


def test_deliver_without_the_video_leaves_earlier_deliveries_in_place(tmp_path: Path):
    work, _ = _films_work(tmp_path)
    film = tmp_path / "Film"
    film.mkdir()
    old = film / "Film.tr.srt"
    assemble.deliver(work, old, tmp_path / "backups", force=False)
    assemble.run_checks(work)
    # The user named another destination: nothing beside it is moved.
    info = assemble.deliver(work, tmp_path / "elsewhere.srt", tmp_path / "backups", force=False)
    assert old.exists() and info["moved_earlier_deliveries"] == [] and info["earlier_deliveries"] == [str(old)]


def test_deliver_keeps_a_recorded_path_that_now_holds_another_language(tmp_path: Path):
    work, _ = _films_work(tmp_path)
    film = tmp_path / "Film"
    film.mkdir()
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    old = film / "Film.tr.srt"
    assemble.deliver(work, old, tmp_path / "backups", force=False)
    old.write_text(ENGLISH, encoding="utf-8")
    assemble.run_checks(work)
    info = assemble.deliver(work, film / "Film.srt", tmp_path / "backups", force=False, video=video)
    assert old.read_text(encoding="utf-8") == ENGLISH and info["moved_earlier_deliveries"] == []
