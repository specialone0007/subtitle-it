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
