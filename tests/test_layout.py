"""The last step before delivery: two lines of 42 at most, one line per
speaker, and a two-speaker cue split in two when it cannot be shown so."""

import json
from datetime import datetime
from pathlib import Path

import pytest

import assemble
import layout
import learn
import prepare
import srt

ASK = "- Bunu sana daha önce söylemiştim, hatırlamıyor musun?"
ANSWER = "- Hatırlıyorum ama o zaman başka bir şey demiştin."


def test_a_cue_that_fits_stays_as_it_is():
    parts, why = layout.plan(0, 2000, ["Gel.", "Hemen."], 80)
    assert why is None and [p.lines for p in parts] == [["Gel.", "Hemen."]]


def test_a_long_one_speaker_cue_is_rewrapped_into_two_lines():
    lines = ["<i>Bunu sana daha önce</i>", "<i>söylemiştim, hatırlamıyor</i>", "<i>musun?</i>"]
    parts, why = layout.plan(0, 3000, lines, 80)
    assert why is None and len(parts) == 1
    assert parts[0].lines == ["<i>Bunu sana daha önce söylemiştim,</i>", "<i>hatırlamıyor musun?</i>"]


def test_a_one_speaker_cue_that_needs_three_lines_fails():
    text = "Bunu sana daha önce söylemiştim, hatırlamıyor musun? Hatırlıyorum ama o zaman başka bir şey demiştin."
    parts, why = layout.plan(0, 6000, [text], 80)
    assert "more than 2 lines" in why and parts[0].lines == [text]


def test_two_speakers_get_one_line_each():
    parts, why = layout.plan(0, 2000, ["- Kim o?", "- Benim,", "aç kapıyı."], 80)
    assert why is None and parts[0].lines == ["- Kim o?", "- Benim, aç kapıyı."]


def test_two_long_turns_are_split_at_the_speaker_change():
    parts, why = layout.plan(10_000, 18_000, [ASK, ANSWER], 120)
    assert why is None and len(parts) == 2
    a, b = parts
    assert a.start == 10_000 and b.end == 18_000 and b.start - a.end == 120
    # Time is shared by length: the longer question gets the longer part.
    assert a.end - a.start > b.end - b.start
    assert a.lines == ["Bunu sana daha önce söylemiştim,", "hatırlamıyor musun?"]
    assert b.lines == ["Hatırlıyorum ama o zaman", "başka bir şey demiştin."]


def test_no_split_when_a_part_would_be_too_fast():
    parts, why = layout.plan(10_000, 14_000, [ASK, ANSWER], 120)
    assert "chars/s" in why and len(parts) == 1 and parts[0].lines == [ASK, ANSWER]


def test_a_one_word_reply_gets_its_minimum_first():
    ask = "- Bunu sana daha önce söylemiştim, hatırlamıyor musun?"
    parts, why = layout.plan(0, 6000, [ask, "- Evet."], 80)
    assert why is None and len(parts) == 2
    a, b = parts
    assert b.end - b.start >= layout.MIN_PART_MS and a.end - a.start > b.end - b.start
    assert b.start - a.end == 80 and b.lines == ["Evet."]


def test_uneven_turns_keep_time_by_length_when_both_reach_the_minimum():
    # 55 and 26 characters over 5.2 s: by length both parts last over a
    # second and read under 17 chars/s, so the split stays by length.
    ask = "- " + "Bunu sana daha önce söylemiştim, hatırlamıyor musun hiç?"[:55]
    reply = "- " + "Hatırlıyorum ama değişti o."[:26]
    parts, why = layout.plan(0, 5200, [ask, reply], 80)
    assert why is None and len(parts) == 2
    a, b = parts
    size_a, size_b = (sum(len(ln) for ln in p.lines) for p in parts)
    assert abs((a.end - a.start) / (b.end - b.start) - size_a / size_b) < 0.01


def test_share_raises_only_a_part_under_the_minimum():
    assert layout.share(6000, [50, 50]) == [3000, 3000]
    out = layout.share(6000, [52, 4])
    assert out == [5000, 1000]
    out = layout.share(4000, [40, 4, 4])
    assert out == [2000, 1000, 1000] and sum(out) == 4000


def test_no_split_when_a_part_would_be_too_short():
    parts, why = layout.plan(0, 1500, ["- Bu çok uzun bir soru, değil mi sence de bu?", "- Evet."], 80)
    assert "ms" in why and len(parts) == 1


def test_usual_gap_is_the_median_short_gap_capped():
    cues = [
        srt.Cue(n=i, start=s, end=e, ts="", lines=["x"])
        for i, (s, e) in enumerate([(0, 900), (1000, 1900), (2040, 3000), (9000, 9500)], 1)
    ]
    assert layout.usual_gap(cues) == 140
    assert layout.usual_gap(cues[:1]) == 80


FR = """1
00:00:01,000 --> 00:00:03,000
Viens.

2
00:00:03,500 --> 00:00:04,000
[Door creaks]

3
00:00:05,000 --> 00:00:13,000
- Je te l'avais dit, tu ne te souviens pas ?
- Si, mais tu avais dit autre chose.

4
00:00:13,100 --> 00:00:15,000
D'accord.
"""

TR = f"1\nGel.\n\n3\n{ASK}\n{ANSWER}\n\n4\nTamam.\n"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "fr.srt").write_text(FR, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, None)
    prepare.chunks(w, target=250)
    (w / "out" / "tr_01.txt").write_text(TR, encoding="utf-8")
    return w


def test_check_splits_renumbers_and_maps_the_delivered_cues(work: Path):
    r = assemble.run_checks(work)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["split_cues"] == 1 and r["delivered_cues"] == 4 and r["sound_only_cues"] == 1
    draft, _ = srt.parse(work / "draft.tr.srt")
    assert [c.n for c in draft] == [1, 2, 3, 4]
    assert draft[0].ts == "00:00:01,000 --> 00:00:03,000" and draft[3].ts == "00:00:13,100 --> 00:00:15,000"
    assert draft[1].start == 5000 and draft[2].end == 13_000 and draft[1].end < draft[2].start
    cue_map = json.loads((work / "cue_map.json").read_text(encoding="utf-8"))
    assert cue_map["cues"] == {
        "1": {"cue": 1},
        "2": {"cue": 3, "part": 1, "of": 2},
        "3": {"cue": 3, "part": 2, "of": 2},
        "4": {"cue": 4},
    }
    assert [x["delivered"] for x in assemble.where(work, [1, 3, 4])] == [[1], [2, 3], [4]]


def test_check_hard_fails_a_two_speaker_cue_too_tight_to_split(work: Path):
    text = (work / "timing.srt").read_text(encoding="utf-8").replace("00:00:13,000", "00:00:08,000")
    (work / "timing.srt").write_text(text, encoding="utf-8")
    r = assemble.run_checks(work)
    assert [(x["cue"], x["check"]) for x in r["hard"]] == [(3, "line length")]


def test_where_command_writes_the_result(work: Path):
    assemble.run_checks(work)
    res = work / "where.json"
    assemble.main(["--result", str(res), "where", "--work", str(work), "--cues", "2,3"])
    out = json.loads(res.read_text(encoding="utf-8"))
    assert out[0]["delivered"] == [] and out[1]["delivered"] == [2, 3]


def test_deliver_keeps_the_map_and_learn_reads_it(work: Path, tmp_path: Path):
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    assemble.deliver(work, dest, tmp_path / "backups", force=False)
    # The film speaks at 1 s: no opening credit, so the numbers stay; the
    # two closing credit cues come after the film's four.
    delivered = json.loads((work / "delivered_map.json").read_text(encoding="utf-8"))
    assert delivered["cues"] == json.loads((work / "cue_map.json").read_text(encoding="utf-8"))["cues"]
    assert delivered["credits"] == [5, 6]
    # An edit to a credit cue teaches nothing; an edit to a line does.
    text = dest.read_text(encoding="utf-8").replace("Tamam.", "Peki.").replace(assemble.CREDIT_BYE, "Görüşürüz.")
    dest.write_text(text, encoding="utf-8")
    d = learn.diff(work)
    assert [(e["cue"], e["timing_cue"]) for e in d["edits"]] == [(4, 4)]
    # A second delivery backs up the first with its map, so its numbers
    # still lead back to the timing file.
    assemble.run_checks(work)
    dest.write_bytes((work / "delivered.tr.srt").read_bytes())
    info = assemble.deliver(work, dest, tmp_path / "backups", force=False)
    backup = Path(info["backup_of_old_file"])
    assert json.loads(Path(str(backup) + ".map.json").read_text(encoding="utf-8"))["cues"]["3"] == {"cue": 3, "part": 2, "of": 2}


def test_deliver_leaves_out_the_map_when_the_user_edited_the_file(work: Path, tmp_path: Path):
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    assemble.deliver(work, dest, tmp_path / "backups", force=False)
    # The user edits the delivered file: the old map no longer describes it.
    dest.write_text(dest.read_text(encoding="utf-8").replace("Tamam.", "Peki."), encoding="utf-8")
    assemble.run_checks(work)
    info = assemble.deliver(work, dest, tmp_path / "backups", force=False)
    backup = Path(info["backup_of_old_file"])
    assert "Peki." in backup.read_text(encoding="utf-8")
    assert not Path(str(backup) + ".map.json").exists()
    assert [p.name for p in (tmp_path / "backups").iterdir()] == [backup.name]


def test_two_deliveries_in_one_second_keep_both_backups(work: Path, tmp_path: Path, monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 13, 12, 0, 0)

    monkeypatch.setattr(assemble, "datetime", Frozen)
    assemble.run_checks(work)
    dest = tmp_path / "Film.srt"
    backups = tmp_path / "backups"
    dest.write_text("first", encoding="utf-8")
    one = Path(assemble.deliver(work, dest, backups, force=False)["backup_of_old_file"])
    dest.write_text("second", encoding="utf-8")
    two = Path(assemble.deliver(work, dest, backups, force=False)["backup_of_old_file"])
    dest.write_text("third", encoding="utf-8")
    three = Path(assemble.deliver(work, dest, backups, force=False)["backup_of_old_file"])
    assert [one.name, two.name, three.name] == [
        "Film.20261113-120000.srt",
        "Film.20261113-120000-2.srt",
        "Film.20261113-120000-3.srt",
    ]
    assert [p.read_text(encoding="utf-8") for p in (one, two, three)] == ["first", "second", "third"]


# A fast cue stays on screen into the silence after it (`available_end`).


def test_a_cue_at_or_under_17_keeps_its_end():
    # 34 characters over 2 s is exactly 17 a second.
    assert layout.available_end(0, 2000, 5000, 80, 34) == 2000


def test_a_fast_cue_gets_just_the_time_it_needs():
    # 40 characters need 2353 ms to read at 17 a second.
    assert layout.available_end(0, 2000, 5000, 80, 40) == 2353


def test_a_fast_cue_stops_at_the_usual_gap_before_the_next_cue():
    assert layout.available_end(0, 2000, 2300, 80, 60) == 2220


def test_a_fast_cue_gets_half_a_second_at_most():
    assert layout.available_end(0, 2000, 9000, 80, 60) == 2500
    assert layout.available_end(0, 2000, None, 80, 60) == 2500


def test_a_fast_cue_is_never_shown_past_seven_seconds():
    assert layout.available_end(0, 6800, 9000, 80, 200) == layout.MAX_SHOWN_MS
    # A cue already longer than that keeps its own end.
    assert layout.available_end(0, 7500, 9000, 80, 200) == 7500


def test_a_fast_cue_with_no_room_keeps_its_end():
    # The next cue starts within the usual gap, or overlaps.
    assert layout.available_end(0, 2000, 2050, 80, 60) == 2000
    assert layout.available_end(0, 2000, 1900, 80, 60) == 2000


def test_a_split_gives_the_extra_time_to_the_last_part():
    parts, why = layout.plan(10_000, 18_000, [ASK, ANSWER], 120)
    longer, why_longer = layout.plan(10_000, 18_000, [ASK, ANSWER], 120, 18_400)
    assert why is None and why_longer is None
    assert longer[0] == parts[0] and longer[1].start == parts[1].start and longer[1].end == 18_400


FAST = "Sana bunu kaç kere söyledim, hiç dinlemiyorsun."  # 47 characters


def _fast_work(tmp_path: Path, next_start: str) -> Path:
    fr = f"1\n00:00:01,000 --> 00:00:03,000\nJe te l'ai dit cent fois.\n\n2\n{next_start} --> 00:00:12,000\nD'accord.\n"
    (tmp_path / "fr.srt").write_text(fr, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, None)
    prepare.chunks(w, target=250)
    (w / "out" / "tr_01.txt").write_text(f"1\n{FAST}\n\n2\nTamam.\n", encoding="utf-8")
    return w


def test_check_shows_a_fast_cue_longer_and_measures_it_over_that_time(tmp_path: Path):
    w = _fast_work(tmp_path, "00:00:10,000")
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0, r["hard"]
    assert r["extended_cues"] == 1
    draft, _ = srt.parse(w / "draft.tr.srt")
    # Half a second more, the start as written; the next cue is untouched.
    assert draft[0].ts == "00:00:01,000 --> 00:00:03,500"
    assert draft[1].ts == "00:00:10,000 --> 00:00:12,000"
    # 47 characters over 2.5 s, the source's 25 over the same time.
    assert [x["detail"] for x in r["warnings"] if x["check"] == "reading speed"] == [
        f"18.8 chars/s, source 10.0; {assemble.TURKISH_ONLY_FAST}"
    ]


def test_check_never_runs_a_fast_cue_into_the_next_one(tmp_path: Path):
    w = _fast_work(tmp_path, "00:00:03,100")
    r = assemble.run_checks(w)
    assert r["extended_cues"] == 0
    draft, _ = srt.parse(w / "draft.tr.srt")
    assert draft[0].ts == "00:00:01,000 --> 00:00:03,000"
    assert [x["detail"][:4] for x in r["warnings"] if x["check"] == "reading speed"] == ["23.5"]


def _cues(*spans: tuple[int, int]) -> list[srt.Cue]:
    return [
        srt.Cue(n=i, start=a, end=b, ts=f"{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}", lines=[f"Satır {i}."])
        for i, (a, b) in enumerate(spans, 1)
    ]


NAMED = ["Çeviri: specialone0007", assemble.CREDIT_TOOL]


def test_credit_opens_in_the_silence_and_closes_after_the_last_line():
    shown, shift, credits = assemble.with_credit(_cues((10_000, 12_000), (60_000, 62_500)), "specialone0007")
    assert shift == 2 and credits == [1, 2, 5, 6] and [c.n for c in shown] == [1, 2, 3, 4, 5, 6]
    assert shown[0].ts == "00:00:01,000 --> 00:00:03,000" and shown[0].lines == [assemble.CREDIT_HELLO]
    assert shown[1].ts == "00:00:03,000 --> 00:00:07,000" and shown[1].lines == NAMED
    assert shown[2].lines == ["Satır 1."] and shown[2].ts == "00:00:10,000 --> 00:00:12,000"
    assert shown[4].ts == "00:01:03,500 --> 00:01:05,500" and shown[4].lines == [assemble.CREDIT_BYE]
    assert shown[5].ts == "00:01:05,500 --> 00:01:09,500" and shown[5].lines == NAMED
    # No screen has more than two lines, none longer than a subtitle line.
    assert max(len(c.lines) for c in shown) == 2
    assert max(len(ln) for c in shown for ln in c.lines) <= assemble.MAX_LINE


def test_credit_opening_shortens_or_drops_when_the_film_speaks_early():
    # First line at 7.5 s: just room for both screens.
    shown, shift, _ = assemble.with_credit(_cues((7_500, 9_000)), "specialone0007")
    assert shift == 2 and shown[1].ts == "00:00:03,000 --> 00:00:07,000"
    # First line at 7.4 s: no greeting, the credit alone for 4 s.
    shown, shift, _ = assemble.with_credit(_cues((7_400, 9_000)), "specialone0007")
    assert shift == 1 and shown[0].ts == "00:00:01,000 --> 00:00:05,000" and shown[0].lines == NAMED
    # First line at 4.5 s: the credit alone, ending half a second before it.
    shown, shift, _ = assemble.with_credit(_cues((4_500, 6_000)))
    assert shift == 1 and shown[0].ts == "00:00:01,000 --> 00:00:04,000"
    # First line at 4.4 s: under 3 s of room, so no opening credit.
    shown, shift, credits = assemble.with_credit(_cues((4_400, 6_000)))
    assert shift == 0 and credits == [2, 3] and shown[0].lines == ["Satır 1."]


def test_credit_without_a_name_shows_the_tool_alone():
    shown, _, _ = assemble.with_credit(_cues((10_000, 12_000)), "  ")
    assert shown[1].lines == [assemble.CREDIT_TOOL] and shown[-1].lines == [assemble.CREDIT_TOOL]


def test_credit_name_too_long_stops():
    with pytest.raises(SystemExit):
        assemble.credit_lines("x" * (assemble.CREDIT_NAME_MAX + 1))
    assert assemble.credit_lines("x" * assemble.CREDIT_NAME_MAX)[0] == "Çeviri: " + "x" * assemble.CREDIT_NAME_MAX


def test_deliver_with_credit_moves_the_map_and_keeps_the_draft(tmp_path: Path):
    (tmp_path / "fr.srt").write_text(
        FR.replace("00:00:01,000 --> 00:00:03,000", "00:00:06,000 --> 00:00:08,000", 1).replace(
            "00:00:03,500 --> 00:00:04,000", "00:00:08,500 --> 00:00:09,000"
        ),
        encoding="utf-8",
    )
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, None)
    prepare.chunks(w, target=250)
    (w / "out" / "tr_01.txt").write_text(TR, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    draft = (w / "draft.tr.srt").read_bytes()
    dest = tmp_path / "Film.srt"
    info = assemble.deliver(w, dest, tmp_path / "backups", force=False, translator="specialone0007")
    assert info["credit"] is True and info["credit_name"] == "specialone0007" and info["credit_cues"] == [1, 6, 7]
    assert (w / "draft.tr.srt").read_bytes() == draft
    raw = dest.read_bytes()
    assert raw.startswith(assemble.UTF8_BOM) and b"\r\n" in raw and b"\r\r" not in raw
    shown, _ = srt.parse(dest)
    assert [c.n for c in shown] == list(range(1, 8)) and shown[1].lines == ["Gel."]
    assert shown[0].lines == NAMED and shown[-1].lines == NAMED
    assert [x["delivered"] for x in assemble.where(w, [1, 3])] == [[2], [3, 4]]
    # Off: the file is the draft as it was, BOM added.
    assemble.deliver(w, dest, tmp_path / "backups", force=False, credit=False)
    assert dest.read_bytes() == assemble.UTF8_BOM + draft.removeprefix(assemble.UTF8_BOM)
