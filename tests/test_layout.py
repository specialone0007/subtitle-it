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
    dest = tmp_path / "Film.tr.srt"
    assemble.deliver(work, dest, tmp_path / "backups", force=False)
    assert (work / "delivered_map.json").read_text(encoding="utf-8") == (work / "cue_map.json").read_text(encoding="utf-8")
    dest.write_text(dest.read_text(encoding="utf-8").replace("Tamam.", "Peki."), encoding="utf-8")
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
    dest = tmp_path / "Film.tr.srt"
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
    dest = tmp_path / "Film.tr.srt"
    backups = tmp_path / "backups"
    dest.write_text("first", encoding="utf-8")
    one = Path(assemble.deliver(work, dest, backups, force=False)["backup_of_old_file"])
    dest.write_text("second", encoding="utf-8")
    two = Path(assemble.deliver(work, dest, backups, force=False)["backup_of_old_file"])
    dest.write_text("third", encoding="utf-8")
    three = Path(assemble.deliver(work, dest, backups, force=False)["backup_of_old_file"])
    assert [one.name, two.name, three.name] == [
        "Film.tr.20261113-120000.srt",
        "Film.tr.20261113-120000-2.srt",
        "Film.tr.20261113-120000-3.srt",
    ]
    assert [p.read_text(encoding="utf-8") for p in (one, two, three)] == ["first", "second", "third"]
