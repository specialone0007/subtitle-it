import json
from pathlib import Path

import srt

SAMPLE = """1
00:00:01,000 --> 00:00:02,500
Hello.

2
00:00:03,000 --> 00:00:05,000
<i>How are you?</i>
- Fine.

3
00:00:10,000 --> 00:00:12,000
Bye.
"""


def test_dash_lines_counts_turns_through_tags_and_spaces():
    assert srt.dash_lines(["- Who?", "  <i>- Me.</i>", "Not a dash - here"]) == 2
    assert not srt.is_dash_line("Word - word")


def test_parse_basic():
    cues = srt.parse_text(SAMPLE)
    assert [c.n for c in cues] == [1, 2, 3]
    assert cues[0].start == 1000 and cues[0].end == 2500
    assert cues[1].lines == ["<i>How are you?</i>", "- Fine."]
    assert cues[1].plain == "How are you? - Fine."
    assert cues[2].ts == "00:00:10,000 --> 00:00:12,000"


def test_parse_without_numbers_bom_crlf_and_dot_millis():
    text = "﻿00:00:01.000 --> 00:00:02.000\r\nA\r\n\r\n00:00:03.5 --> 00:00:04.000\r\nB\r\n"
    cues = srt.parse_text(text)
    assert [c.text for c in cues] == ["A", "B"]
    assert cues[1].start == 3500


def test_parse_well_formed_file_needs_no_repairs():
    repairs: list[str] = []
    cues = srt.parse_text(SAMPLE, repairs)
    assert repairs == []
    assert [(c.n, c.ts, c.lines) for c in cues] == [
        (1, "00:00:01,000 --> 00:00:02,500", ["Hello."]),
        (2, "00:00:03,000 --> 00:00:05,000", ["<i>How are you?</i>", "- Fine."]),
        (3, "00:00:10,000 --> 00:00:12,000", ["Bye."]),
    ]


# One file with each fault: cue 2 has no blank line before it (with its
# number line), cue 3 has none either (without a number line), and the text
# of cue 3 is split by a stray blank line.
MALFORMED = """1
00:00:01,000 --> 00:00:02,500
Hello.
2
00:00:03,000 --> 00:00:05,000
How are you?
00:00:06,000 --> 00:00:08,000
I am fine,

thank you.

4
00:00:10,000 --> 00:00:12,000
Bye.
"""


def test_parse_repairs_missing_blank_lines_and_stray_blank_lines():
    repairs: list[str] = []
    cues = srt.parse_text(MALFORMED, repairs)
    assert [(c.start, c.lines) for c in cues] == [
        (1000, ["Hello."]),
        (3000, ["How are you?"]),
        (6000, ["I am fine,", "thank you."]),
        (10000, ["Bye."]),
    ]
    assert [c.n for c in cues] == [1, 2, 3, 4]
    assert len(repairs) == 3, repairs


def test_parse_never_puts_a_timestamp_line_in_cue_text():
    for text in (SAMPLE, MALFORMED, SAMPLE.replace("\n\n", "\n"), MALFORMED.replace("\n\n", "\n")):
        for c in srt.parse_text(text):
            assert not any(srt.TS_RE.match(ln) for ln in c.lines), c


def test_parse_stray_number_line_and_text_before_the_first_cue():
    text = "Made by someone\n\n1\n00:00:01,000 --> 00:00:02,000\nA\n\n2\n\n00:00:03,000 --> 00:00:04,000\nB\n"
    repairs: list[str] = []
    cues = srt.parse_text(text, repairs)
    assert [c.lines for c in cues] == [["A"], ["B"]]
    # Text before the first cue goes, as before; the cut-off number is a repair.
    assert len(repairs) == 1


def test_parse_reports_repairs_from_a_file(tmp_path: Path):
    p = tmp_path / "x.srt"
    p.write_text(MALFORMED, encoding="utf-8")
    repairs: list[str] = []
    cues, _ = srt.parse(p, repairs)
    assert len(cues) == 4 and len(repairs) == 3
    srt.main(["--result", str(tmp_path / "r.json"), "info", str(p)])
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["repairs"] == 3


def test_decode_turkish_cp1254_and_bom():
    raw = "Şey... Ağır bir gün.\nİyi geceler, Çağrı.\n".encode("cp1254") * 20
    text, enc = srt.decode(raw)
    assert "Ağır" in text and "İyi" in text, enc
    text, enc = srt.decode("﻿Merhaba".encode())
    assert text == "Merhaba" and enc == "utf-8-sig"
    text, enc = srt.decode("Merhaba".encode("utf-16"))
    assert text == "Merhaba"


def test_write_round_trip_crlf(tmp_path: Path):
    cues = srt.parse_text(SAMPLE)
    out = tmp_path / "x.srt"
    srt.write(out, cues, {1: ["Merhaba."], 2: ["<i>Nasılsın?</i>", "- İyiyim."], 3: ["Hoşça kal."]})
    raw = out.read_bytes()
    assert b"\r\n" in raw and b"\n\n" not in raw.replace(b"\r\n", b"")
    assert not raw.startswith(b"\xef\xbb\xbf")
    back, enc = srt.parse(out)
    assert enc == "utf-8"
    assert [c.ts for c in back] == [c.ts for c in cues]
    assert back[1].lines == ["<i>Nasılsın?</i>", "- İyiyim."]


def test_read_blocks(tmp_path: Path):
    p = tmp_path / "tr_01.txt"
    p.write_text("1\nBir.\n\n#2\nİki\nsatır\n\nnot a number\nx\n\n2\nAgain\n", encoding="utf-8")
    blocks, problems = srt.read_blocks(p)
    assert blocks[1] == ["Bir."] and blocks[2] == ["Again"]
    assert len(problems) == 2


def _cue(n, start, end, text="x"):
    return srt.Cue(n=n, start=start, end=end, ts=f"{srt.fmt_ms(start)} --> {srt.fmt_ms(end)}", lines=[text])


def test_pair_by_overlap():
    timing = [_cue(1, 0, 2000), _cue(2, 2500, 4000), _cue(3, 9000, 10000)]
    other = [_cue(1, 100, 1900, "a"), _cue(2, 2400, 3000, "b"), _cue(3, 3000, 4100, "c"), _cue(4, 6000, 7000, "lost")]
    p = srt.pair(timing, other)
    assert [o.text for o in p[1]] == ["a"]
    assert [o.text for o in p[2]] == ["b", "c"]
    assert p[3] == []


def test_offset_check_detects_shift():
    timing = [_cue(i, i * 3000, i * 3000 + 2000) for i in range(1, 50)]
    shifted = [_cue(i, i * 3000 + 500, i * 3000 + 2500) for i in range(1, 50)]
    r = srt.offset_check(timing, shifted)
    assert r["paired_share"] > 0.9 and r["median_start_diff_ms"] == 500


def test_chunk_cuts_at_longest_pause():
    cues, t = [], 0
    for i in range(1, 501):
        gap = 8000 if i == 262 else 500
        t += gap
        cues.append(_cue(i, t, t + 1500))
        t += 1500
    bounds = srt.chunk(cues, target=250)
    assert bounds == [(1, 261), (262, 500)]


def test_chunk_small_film_is_one_chunk():
    cues = [_cue(i, i * 2000, i * 2000 + 1000) for i in range(1, 120)]
    assert srt.chunk(cues) == [(1, 119)]


def test_shift_moves_cues_and_stops_at_zero():
    cues = srt.parse_text("1\n00:00:00,200 --> 00:00:01,000\nHi\n\n2\n00:00:05,000 --> 00:00:06,500\nBye\n")
    out = srt.shift(cues, -500)
    assert [c.ts for c in out] == ["00:00:00,000 --> 00:00:00,500", "00:00:04,500 --> 00:00:06,000"]
    assert [c.lines for c in out] == [["Hi"], ["Bye"]]
    assert cues[0].start == 200  # the input is left as it was


def test_shift_command_writes_the_moved_file(tmp_path: Path):
    src = tmp_path / "in.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n", encoding="utf-8")
    dest = tmp_path / "out.srt"
    srt.main(["shift", str(src), str(dest), "--ms", "-500"])
    assert srt.parse(dest)[0][0].ts == "00:00:00,500 --> 00:00:01,500"


def _film(minutes=25):
    """A film's worth of spoken cues with uneven lengths and pauses, as in a
    real film; evenly spaced cues would fit at many offsets."""
    cues, t, i = [], 1000, 0
    while t < minutes * 60_000:
        i += 1
        length = 1200 + (i * 7919) % 2300
        cues.append(_cue(i, t, t + length, f"line {i}"))
        t += length + 300 + (i * 104_729) % 3100
    return cues


def test_is_sound_spots_descriptions_labels_and_songs():
    assert srt.is_sound(_cue(1, 0, 1, "[door creaks]"))
    assert srt.is_sound(_cue(1, 0, 1, "(SIGHS)"))
    assert srt.is_sound(_cue(1, 0, 1, "JOHN:"))
    assert srt.is_sound(_cue(1, 0, 1, "♪ Coming back for me ♪"))
    assert srt.is_sound(_cue(1, 0, 1, "# Coming back for me #"))
    assert not srt.is_sound(_cue(1, 0, 1, "Room #4, please."))
    assert not srt.is_sound(_cue(1, 0, 1, "[sighs] Fine."))
    assert not srt.is_sound(_cue(1, 0, 1, "- Who? - Me."))
    assert not srt.is_sound(_cue(1, 0, 1, "Tamam."))


def test_fit_finds_a_constant_lead_in_despite_merged_lines_and_sound_cues():
    timing = _film()
    # Another edition: 15.3 s later, every third pair of lines merged into
    # one cue, and a hearing-impaired description between every few cues.
    other = []
    for k, (a, b) in enumerate(zip(timing[::2], timing[1::2])):
        if k % 3 == 0:
            other.append(_cue(k, a.start + 15_300, b.end + 15_300, "merged"))
        else:
            other += [_cue(k, c.start + 15_300, c.end + 15_300) for c in (a, b)]
    other += [_cue(1000 + i, c.end + 15_400, c.end + 16_000, "[thud]") for i, c in enumerate(timing[::5])]
    other.sort(key=lambda c: c.start)
    assert srt.offset_check(timing, other)["paired_share"] < 0.8  # the old gate refuses it
    r = srt.fit(timing, other)
    assert r["fits"], r["reason"]
    assert abs(r["offset_ms"] + 15_300) <= 50
    assert r["covered"] >= 0.99 and r["sound_cues"][1] > 0


def test_fit_leaves_a_file_that_already_fits_in_place():
    timing = _film()
    assert srt.fit(timing, timing)["offset_ms"] == 0


def test_fit_refuses_a_different_cut():
    timing = _film()
    # Ten minutes in, the other file loses 20 s: everything after is late.
    other = [c if c.start < 600_000 else _cue(c.n, c.start + 20_000, c.end + 20_000) for c in timing]
    r = srt.fit(timing, other)
    assert not r["fits"]
    assert "different cut" in r["reason"] or "covers" in r["reason"]


def test_fit_refuses_a_file_with_lines_missing():
    timing = _film()
    other = [c for i, c in enumerate(timing) if i % 4]  # a quarter of the lines left out
    r = srt.fit(timing, other)
    assert not r["fits"] and "covers 74.8% of the spoken cues, needs 80.0%" in r["reason"]


def test_fit_takes_a_file_that_covers_most_lines():
    # One line in eight missing: 87.5% covered, under the old 90% bar and
    # over the new 80% one, so the file is polished rather than refused.
    timing = _film()
    other = [c for i, c in enumerate(timing) if i % 8]
    r = srt.fit(timing, other)
    assert r["fits"], r["reason"]
    assert 0.8 <= r["covered"] < 0.9


def test_fit_refuses_a_file_with_lines_in_the_silences():
    timing = _film()
    extra = [
        _cue(5000 + i, a.end + 100, b.start - 100) for i, (a, b) in enumerate(zip(timing, timing[1:])) if b.start - a.end >= 1200
    ]
    r = srt.fit(timing, sorted(timing + extra, key=lambda c: c.start))
    assert not r["fits"] and "land on speech" in r["reason"]
    assert r["covered"] >= 0.99


def test_fit_refuses_a_file_with_no_spoken_cues():
    timing = _film(minutes=3)
    sounds = [_cue(c.n, c.start, c.end, "[music]") for c in timing]
    r = srt.fit(timing, sounds)
    assert not r["fits"] and r["reason"] == "no spoken cues in one of the files"


def test_fit_says_when_nothing_pairs():
    timing = _film(minutes=3)
    later = srt.shift(timing, 3_600_000)  # an hour away, beyond the search
    r = srt.fit(timing, later)
    assert not r["fits"] and "no cue pairs" in r["reason"] and "None" not in r["reason"]


def test_fit_command_writes_the_result(tmp_path: Path):
    a = tmp_path / "a.srt"
    srt.write(a, _film(minutes=3))
    path = tmp_path / "fit.json"
    srt.main(["--result", str(path), "fit", str(a), str(a)])
    out = json.loads(path.read_text(encoding="utf-8"))
    assert out["fits"] is True and out["offset_ms"] == 0
