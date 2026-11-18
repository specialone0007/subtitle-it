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
    # closing credit cue comes after the film's four.
    delivered = json.loads((work / "delivered_map.json").read_text(encoding="utf-8"))
    assert delivered["cues"] == json.loads((work / "cue_map.json").read_text(encoding="utf-8"))["cues"]
    assert delivered["credits"] == [5]
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


# FR with every cue 7 s later: the first line at 8 s leaves room for the
# full opening credit.
FR_LATE = srt.render(srt.shift(srt.parse_text(FR), 7_000))
HELLO = [assemble.CREDIT_HELLO, "specialone0007"]
BYE = [assemble.CREDIT_BYE, "specialone0007"]


def test_credit_opens_in_the_silence_and_closes_after_the_last_line():
    shown, shift, credits = assemble.with_credit(_cues((10_000, 12_000), (60_000, 62_500)), "specialone0007")
    assert shift == 1 and credits == [1, 4] and [c.n for c in shown] == [1, 2, 3, 4]
    assert shown[0].ts == "00:00:03,000 --> 00:00:07,000" and shown[0].lines == HELLO
    assert shown[1].lines == ["Satır 1."] and shown[1].ts == "00:00:10,000 --> 00:00:12,000"
    assert shown[3].ts == "00:01:05,500 --> 00:01:09,500" and shown[3].lines == BYE


def test_credit_closing_stays_inside_the_video():
    spans = ((10_000, 12_000), (60_000, 62_500))
    # Room for the 3 s gap and the full 4 s: the video's end changes nothing.
    shown, _, credits = assemble.with_credit(_cues(*spans), video_end=69_500)
    assert credits == [1, 4] and shown[3].ts == "00:01:05,500 --> 00:01:09,500"
    # Less room: it moves earlier to keep its 4 s, ending with the video.
    shown, _, _ = assemble.with_credit(_cues(*spans), video_end=68_000)
    assert shown[3].ts == "00:01:04,000 --> 00:01:08,000"
    # Half a second after the last line at most, then cut short, 3 s at least.
    shown, _, _ = assemble.with_credit(_cues(*spans), video_end=66_000)
    assert shown[3].ts == "00:01:03,000 --> 00:01:06,000"
    # Under 3.5 s between the last line and the video's end: no closing credit.
    shown, shift, credits = assemble.with_credit(_cues(*spans), video_end=65_900)
    assert shift == 1 and credits == [1] and shown[-1].lines == ["Satır 2."]


def test_video_end_ms_is_none_when_the_video_cannot_be_read(tmp_path: Path, monkeypatch):
    fake = tmp_path / "Film.mkv"
    fake.write_bytes(b"not a video")
    monkeypatch.setattr(assemble.sources, "_run", lambda cmd: (_ for _ in ()).throw(SystemExit("ffprobe not found")))
    assert assemble.video_end_ms(fake) is None
    monkeypatch.setattr(assemble.sources, "_run", lambda cmd: '{"format": {"duration": "5400.25"}, "streams": []}')
    assert assemble.video_end_ms(fake) == 5_400_250


def test_credit_opening_shortens_or_drops_when_the_film_speaks_early():
    # First line at 7.5 s: just room for the full 4 s.
    shown, shift, _ = assemble.with_credit(_cues((7_500, 9_000)), "specialone0007")
    assert shift == 1 and shown[0].ts == "00:00:03,000 --> 00:00:07,000"
    # First line at 6.5 s: cut to 3 s, ending half a second before it.
    shown, shift, _ = assemble.with_credit(_cues((6_500, 8_000)))
    assert shift == 1 and shown[0].ts == "00:00:03,000 --> 00:00:06,000"
    # First line at 6.4 s: under 3 s of room, so no opening credit.
    shown, shift, credits = assemble.with_credit(_cues((6_400, 8_000)))
    assert shift == 0 and credits == [2] and shown[0].lines == ["Satır 1."]


def test_credit_without_a_name_shows_the_greeting_alone():
    shown, _, _ = assemble.with_credit(_cues((10_000, 12_000)), "  ")
    assert shown[0].lines == [assemble.CREDIT_HELLO] and shown[-1].lines == [assemble.CREDIT_BYE]


def test_credit_name_too_long_stops():
    with pytest.raises(SystemExit):
        assemble.credit_lines(assemble.CREDIT_HELLO, "x" * (assemble.CREDIT_NAME_MAX + 1))
    assert assemble.credit_lines(assemble.CREDIT_BYE, "x" * assemble.CREDIT_NAME_MAX)[1] == "x" * assemble.MAX_LINE


def test_deliver_with_credit_moves_the_map_and_keeps_the_draft(tmp_path: Path):
    (tmp_path / "fr.srt").write_text(FR_LATE, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, None)
    prepare.chunks(w, target=250)
    (w / "out" / "tr_01.txt").write_text(TR, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    draft = (w / "draft.tr.srt").read_bytes()
    dest = tmp_path / "Film.srt"
    info = assemble.deliver(w, dest, tmp_path / "backups", force=False, translator="specialone0007")
    assert info["credit"] is True and info["credit_name"] == "specialone0007" and info["credit_cues"] == [1, 6]
    assert (w / "draft.tr.srt").read_bytes() == draft
    raw = dest.read_bytes()
    assert raw.startswith(assemble.UTF8_BOM) and b"\r\n" in raw and b"\r\r" not in raw
    shown, _ = srt.parse(dest)
    assert [c.n for c in shown] == list(range(1, 7)) and shown[1].lines == ["Gel."]
    assert shown[0].lines == HELLO and shown[-1].lines == BYE
    assert [x["delivered"] for x in assemble.where(w, [1, 3])] == [[2], [3, 4]]
    # Off: the file is the draft as it was, BOM added.
    assemble.deliver(w, dest, tmp_path / "backups", force=False, credit=False)
    assert dest.read_bytes() == assemble.UTF8_BOM + draft.removeprefix(assemble.UTF8_BOM)


def test_deliver_cli_passes_the_credit_flags(tmp_path: Path):
    (tmp_path / "fr.srt").write_text(FR_LATE, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, None)
    prepare.chunks(w, target=250)
    (w / "out" / "tr_01.txt").write_text(TR, encoding="utf-8")
    assemble.run_checks(w)
    dest, res = tmp_path / "Film.srt", tmp_path / "res.json"
    base = ["--result", str(res), "deliver", "--work", str(w), "--dest", str(dest), "--backups", str(tmp_path / "b")]
    assemble.main(base + ["--credit-name", "specialone0007"])
    shown, _ = srt.parse(dest)
    assert shown[0].lines == HELLO and shown[-1].lines == BYE
    info = json.loads((w / "delivered.json").read_text(encoding="utf-8"))
    assert info["credit"] is True and info["credit_name"] == "specialone0007"
    assemble.main(base + ["--no-credit"])
    shown, _ = srt.parse(dest)
    assert all(assemble.CREDIT_HELLO not in c.lines and assemble.CREDIT_BYE not in c.lines for c in shown)
    assert json.loads((w / "delivered.json").read_text(encoding="utf-8"))["credit"] is False


def test_deliver_holds_the_closing_credit_to_the_video(tmp_path: Path, monkeypatch):
    (tmp_path / "fr.srt").write_text(FR_LATE, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "fr.srt", None, None)
    prepare.chunks(w, target=250)
    (w / "out" / "tr_01.txt").write_text(TR, encoding="utf-8")
    assemble.run_checks(w)
    draft, _ = srt.parse(w / "draft.tr.srt")
    last = max(c.end for c in draft)
    asked = []

    def video_end(video: Path) -> int:
        asked.append(video)
        return last + 3_600

    monkeypatch.setattr(assemble, "video_end_ms", video_end)
    # Without --video the length is never read: the closing credit keeps its 3 s gap.
    dest = tmp_path / "elsewhere.srt"
    assemble.deliver(w, dest, tmp_path / "b", force=False)
    shown, _ = srt.parse(dest)
    assert asked == [] and (shown[-1].start, shown[-1].end) == (last + 3_000, last + 7_000)
    # With it, the closing credit moves earlier and ends with the video.
    film = tmp_path / "Film"
    film.mkdir()
    video = film / "Film.mkv"
    video.write_bytes(b"x")
    dest = film / "Film.srt"
    assemble.deliver(w, dest, tmp_path / "b", force=False, video=video)
    shown, _ = srt.parse(dest)
    assert asked == [video] and shown[-1].lines == [assemble.CREDIT_BYE]
    assert (shown[-1].start, shown[-1].end) == (last + 500, last + 3_600)


def test_goodbye_follows_the_story_not_an_end_title():
    # The third cue is an end title from another track: the goodbye comes
    # 3 s after the story's last line, before it.
    shown, shift, credits = assemble.with_credit(
        _cues((10_000, 12_000), (60_000, 62_500), (80_000, 83_000)), "specialone0007", on_screen={3}
    )
    assert shift == 1 and credits == [1, 4] and [c.n for c in shown] == [1, 2, 3, 4, 5]
    assert shown[3].lines == BYE and shown[3].ts == "00:01:05,500 --> 00:01:09,500"
    assert shown[4].lines == ["Satır 3."]


def test_goodbye_ends_before_the_next_card_and_skips_cards_in_its_way():
    # Two closing cards 2 s apart: the first is in the way, so the goodbye
    # takes the 2 s between them and ends 0.1 s before the second.
    cues = _cues((10_000, 12_000), (60_000, 62_500), (63_000, 66_000), (68_000, 70_000))
    shown, _, credits = assemble.with_credit(cues, "specialone0007", on_screen={3, 4})
    assert credits == [1, 5] and [c.lines for c in shown[3:]] == [["Satır 3."], BYE, ["Satır 4."]]
    assert shown[4].ts == "00:01:06,000 --> 00:01:07,900"


def test_goodbye_with_no_free_two_seconds_follows_the_last_cue():
    cues = _cues((10_000, 12_000), (60_000, 62_500), (63_000, 66_000), (67_000, 70_000))
    shown, _, credits = assemble.with_credit(cues, "specialone0007", on_screen={3, 4})
    assert credits == [1, 6] and shown[-1].lines == BYE and shown[-1].ts == "00:01:13,000 --> 00:01:17,000"
    # A video that ends 3.6 s after the last cue: the goodbye moves earlier
    # and ends with it; 3.4 s leaves no room for it.
    shown, _, credits = assemble.with_credit(cues, "specialone0007", 73_600, {3, 4})
    assert credits == [1, 6] and shown[-1].ts == "00:01:10,500 --> 00:01:13,600"
    shown, _, credits = assemble.with_credit(cues, "specialone0007", 73_400, {3, 4})
    assert credits == [1] and shown[-1].lines == ["Satır 4."]


def test_goodbye_with_no_story_cue_follows_the_last_cue():
    cues = _cues((10_000, 12_000), (60_000, 62_500))
    shown, _, credits = assemble.with_credit(cues, "specialone0007", on_screen={1, 2})
    assert credits == [1, 4] and shown[-1].ts == "00:01:05,500 --> 00:01:09,500"


def test_goodbye_follows_kept_songs_after_the_last_line():
    # A song still in the draft was kept because it carries the story.
    cues = _cues((10_000, 12_000), (60_000, 62_500), (63_000, 66_000), (66_500, 69_000), (90_000, 93_000))
    for c in cues[2:4]:
        c.lines[:] = ["<i>♪ Şarkı sürüyor ♪</i>"]
    shown, _, credits = assemble.with_credit(cues, "specialone0007", on_screen={5})
    assert credits == [1, 6] and shown[5].ts == "00:01:12,000 --> 00:01:16,000"
    assert shown[6].lines == ["Satır 5."]


def test_credit_map_numbers_the_draft_around_a_goodbye_that_is_not_last():
    cue_map = {"cues": {str(d): {"cue": d + 10} for d in range(1, 5)}, "sound_only": [7]}
    moved = assemble.credit_map(cue_map, [1, 4])
    assert moved["cues"] == {"2": {"cue": 11}, "3": {"cue": 12}, "5": {"cue": 13}, "6": {"cue": 14}}
    assert moved["credits"] == [1, 4] and moved["sound_only"] == [7]
    # No opening credit, goodbye last: the numbers stay.
    assert assemble.credit_map(cue_map, [5])["cues"] == cue_map["cues"]


def test_on_screen_draft_cues_include_every_part_of_a_split_cue(tmp_path: Path):
    rows = [{"n": 1}, {"n": 2, "on_screen": {"fr": ["FIN"], "es": ["FIN"]}}, {"n": 3, "song": True}]
    (tmp_path / "cues.json").write_text(json.dumps(rows), encoding="utf-8")
    cues = {"1": {"cue": 1}, "2": {"cue": 2, "part": 1, "of": 2}, "3": {"cue": 2, "part": 2, "of": 2}, "4": {"cue": 3}}
    (tmp_path / assemble.MAP_FILE).write_text(json.dumps({"cues": cues, "sound_only": []}), encoding="utf-8")
    assert assemble.on_screen_draft_cues(tmp_path) == {2, 3}
