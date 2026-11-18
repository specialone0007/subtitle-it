"""On-screen text the timing file lacks, found in other tracks (prepare.on_screen)."""

import argparse
import json
from pathlib import Path

import pytest

import assemble
import prepare
import srt

# Dialogue every 4 seconds from 0:10. The tracks hold the same lines in
# their own language, plus the extras each test adds.
LINES = 80
CARD = (1_000, 3_500)  # before the first line: a title card
CREDIT = (340_000, 342_000)  # after the last line ends


def _film(tmp: Path, name: str, word: str, extra: list[tuple[int, int, str]] = (), offset: int = 0) -> Path:
    cues = [(10_000 + k * 4_000 + offset, 12_500 + k * 4_000 + offset, f"{word} {k + 1}, here.") for k in range(LINES)]
    cues += [(a + offset, b + offset, text) for a, b, text in extra]
    cues.sort()
    body = "".join(f"{i}\n{srt.fmt_ms(a)} --> {srt.fmt_ms(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(cues, 1))
    path = tmp / name
    path.write_text(body, encoding="utf-8")
    return path


def _timing(tmp: Path) -> Path:
    return _film(tmp, "en.srt", "Line")


def _cues(path: Path) -> list[srt.Cue]:
    return srt.parse(path)[0]


def test_a_line_two_languages_show_in_a_gap_is_added(tmp_path: Path):
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Trois jours plus tôt...")])
    es = _film(tmp_path, "es.srt", "Línea", [(CARD[0] + 200, CARD[1] + 100, "TRES DÍAS ANTES...")], offset=150)
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", es)], [])
    assert len(added) == 1 and summary["added"] == 1
    # The first track given leads: its text and times, the shift undone.
    assert added[0]["lines"] == ["Trois jours plus tôt..."]
    assert (added[0]["start"], added[0]["end"]) == CARD
    assert added[0]["texts"] == {"fr": ["Trois jours plus tôt..."], "es": ["TRES DÍAS ANTES..."]}
    assert [t["fits"] for t in summary["tracks"]] == [True, True]


def test_one_language_alone_is_reported_not_added(tmp_path: Path):
    # A French track also subtitles shouts the English one leaves out.
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Allez!")])
    es = _film(tmp_path, "es.srt", "Línea")
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", es)], [])
    assert added == []
    assert summary["only_one_language"] == 1
    assert summary["only_one_language_first"][0]["text"] == "Allez!"


def test_credits_sounds_and_one_language_twice_are_never_added(tmp_path: Path):
    song = (5_000, 7_000)  # both tracks sing it: still a song, not on-screen text
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CREDIT, "Sous-titres : Jean"), (*CARD, "Mmmh."), (*song, "♪ La la la ♪")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CREDIT, "Subtítulos: Gabriel"), (*song, "♪ La la la ♪")])
    sdh = _film(tmp_path, "sdh.srt", "Line", [(*CARD, "HARTLEY: Hmm...")])
    en2 = _film(tmp_path, "en2.srt", "Line", [(*CREDIT, "THE END")])
    tracks = [("fr", fr), ("es", es), ("en", sdh), ("en", en2)]
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), tracks, [])
    assert added == []
    # "Mmmh." alone is left; the credits and "Hmm..." never count.
    assert [x["text"] for x in summary["only_one_language_first"]] == ["Mmmh.", "THE END"]


def test_one_language_with_and_without_a_region_is_still_one(tmp_path: Path):
    pt = _film(tmp_path, "pt.srt", "Linha", [(*CARD, "TRÊS DIAS ANTES")])
    br = _film(tmp_path, "br.srt", "Linha", [(*CARD, "TRÊS DIAS ANTES")])
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("pt", pt), ("pt-br", br)], [])
    assert added == [] and summary["only_one_language"] == 1


def test_a_forced_track_alone_is_enough_and_is_not_shifted(tmp_path: Path):
    forced = tmp_path / "forced.srt"
    forced.write_text(f"1\n{srt.fmt_ms(CARD[0])} --> {srt.fmt_ms(CARD[1])}\nLUNDHAVEN, 1890\n", encoding="utf-8")
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), [], [("en", forced)])
    assert [a["lines"] for a in added] == [["LUNDHAVEN, 1890"]]
    assert summary["tracks"][0]["forced"] is True and "fits" not in summary["tracks"][0]


def test_a_track_that_does_not_fit_is_left_out(tmp_path: Path):
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Une carte")])
    # Every line two seconds apart from the timing file's: another cut.
    other = "".join(f"{k + 1}\n{srt.fmt_ms(k * 2_000)} --> {srt.fmt_ms(k * 2_000 + 900)}\nUna {k}\n\n" for k in range(200))
    (tmp_path / "es.srt").write_text(other, encoding="utf-8")
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", tmp_path / "es.srt")], [])
    assert added == []
    assert summary["tracks"][1]["fits"] is False and summary["tracks"][1]["reason"]


def test_an_added_cue_is_clipped_between_its_neighbours_or_dropped(tmp_path: Path):
    # Starts inside the first line's gap and runs into it: clipped to end
    # where the first line starts. A second one with no room left is dropped.
    late = (7_000, 10_400)  # the first line starts at 0:10
    tight = (12_600, 13_000)  # 400 ms between line 1 (ends 12,500) and line 2
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*late, "LONDRES"), (*tight, "PARIS")])
    es = _film(tmp_path, "es.srt", "Línea", [(*late, "LONDRES"), (*tight, "PARÍS")])
    added, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", es)], [])
    assert [(a["start"], a["end"]) for a in added] == [(7_000, 10_000)]
    assert summary["no_room"] == [{"ts": srt.fmt_ms(tight[0]), "text": "PARIS"}]


def test_build_adds_the_cue_and_the_run_delivers_it(tmp_path: Path):
    timing = _timing(tmp_path)
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "<i>Trois jours plus tôt...</i>")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CARD, "TRES DÍAS ANTES...")])
    w = tmp_path / "work"
    summary = prepare.build(w, timing, None, None, tracks=[("fr", fr), ("es", es)])
    assert summary["cues"] == LINES + 1 and summary["cues_without_source_text"] == 0
    assert summary["on_screen"]["cues"] == [
        {"n": 1, "ts": srt.fmt_ms(CARD[0]), "texts": {"fr": "<i>Trois jours plus tôt...</i>", "es": "TRES DÍAS ANTES..."}}
    ]
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    # Numbers follow the merged order; italics on another track are no song.
    assert [r["n"] for r in rows[:2]] == [1, 2] and rows[1]["source"] == ["Line 1, here."]
    assert rows[0]["on_screen"]["es"] == ["TRES DÍAS ANTES..."] and "song" not in rows[0] and "left_out" not in rows[0]
    prepare.chunks(w, target=250)
    chunk = (w / "chunks" / "chunk_01.txt").read_text(encoding="utf-8")
    assert "#1 00:00:01 [on-screen text]\nsrc: <i>Trois jours plus tôt...</i>\nalso: es: TRES DÍAS ANTES...\n" in chunk
    tr = "1\n<i>Üç gün önce...</i>\n\n" + "".join(f"{k + 2}\n{k + 1}. satır, burada.\n\n" for k in range(LINES))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    r = assemble.run_checks(w)
    assert r["hard_fail_count"] == 0, r["hard"]
    draft = srt.parse(w / "draft.tr.srt")[0]
    assert draft[0].start == CARD[0] and draft[0].lines == ["<i>Üç gün önce...</i>"]
    assert len(draft) == LINES + 1


def test_build_reads_past_a_sound_only_timing_cue(tmp_path: Path):
    # A hearing-impaired timing file shows "[somber music]" over the card.
    # Build would drop that cue, so the card takes its place.
    timing = _film(tmp_path, "en.srt", "Line", [(*CARD, "[somber music]")])
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Trois jours plus tôt...")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CARD, "TRES DÍAS ANTES...")])
    w = tmp_path / "work"
    summary = prepare.build(w, timing, None, None, tracks=[("fr", fr), ("es", es)])
    assert [c["ts"] for c in summary["on_screen"]["cues"]] == [srt.fmt_ms(CARD[0])]
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert summary["cues"] == LINES + 1 and rows[0]["on_screen"]["fr"] == ["Trois jours plus tôt..."]


def test_a_sound_only_cue_under_a_card_is_not_delivered_with_it(tmp_path: Path):
    # The source file has the card too. Paired with "[somber music]", it
    # would keep that cue alive and deliver the card twice.
    timing = _film(tmp_path, "en.srt", "Line", [(*CARD, "[somber music]")])
    source = _film(tmp_path, "source.srt", "Ligne", [(*CARD, "Trois jours plus tôt...")])
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Trois jours plus tôt...")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CARD, "TRES DÍAS ANTES...")])
    w = tmp_path / "work"
    summary = prepare.build(w, timing, source, None, tracks=[("fr", fr), ("es", es)])
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    with_card = [r["n"] for r in rows if r["source"] == ["Trois jours plus tôt..."]]
    assert with_card == [1] and "on_screen" in rows[0] and summary["cues"] == LINES + 1


def test_build_with_other_source_and_english_files_keeps_the_card(tmp_path: Path):
    # Neither the source file nor the English one has the card: the row
    # takes the track's text, has no English, and is no unpaired cue.
    timing = _timing(tmp_path)
    source = _film(tmp_path, "source.srt", "Ligne")
    en = _film(tmp_path, "en-other.srt", "Line")
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Trois jours plus tôt...")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CARD, "TRES DÍAS ANTES...")])
    w = tmp_path / "work"
    summary = prepare.build(w, timing, source, en, tracks=[("fr", fr), ("es", es)])
    assert summary["cues_without_source_text"] == 0
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert rows[0]["source"] == ["Trois jours plus tôt..."] and rows[0]["en"] is None
    assert rows[1]["source"] == ["Ligne 1, here."] and rows[1]["en"] == ["Line 1, here."]


@pytest.mark.parametrize("tag", ["", "<i>"], ids=["plain card", "italic card"])
def test_a_card_inside_an_italic_song_neither_splits_it_nor_joins_it(tmp_path: Path, tag: str):
    # Six italic lines with no sentence end are a song. A card the other
    # tracks show between the third and the fourth is not part of it: a
    # plain one does not split the song in two runs of three, too short to
    # count, and an italic one does not join it.
    song = [(340_000 + k * 3_000 + (3_000 if k > 2 else 0), 342_000 + k * 3_000 + (3_000 if k > 2 else 0)) for k in range(6)]
    card = (348_500, 350_500)
    timing = _film(tmp_path, "en.srt", "Line", [(a, b, f"<i>Down the river {k}</i>") for k, (a, b) in enumerate(song)])
    end = tag.replace("<", "</")
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*card, f"{tag}Quelque part au nord{end}")])
    es = _film(tmp_path, "es.srt", "Línea", [(*card, f"{tag}En algún lugar del norte{end}")])
    w = tmp_path / "work"
    summary = prepare.build(w, timing, None, None, tracks=[("fr", fr), ("es", es)])
    assert summary["on_screen"]["added"] == 1
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    tail = rows[LINES:]
    assert [r.get("song", False) for r in tail] == [True, True, True, False, True, True, True]
    assert "on_screen" in tail[3]


def test_an_italic_card_the_source_file_sings_along_is_no_song(tmp_path: Path):
    # The source file has the card too, in italics inside its own song,
    # so its italics would make the card a song line.
    song = [(340_000 + k * 3_000 + (3_000 if k > 2 else 0), 342_000 + k * 3_000 + (3_000 if k > 2 else 0)) for k in range(6)]
    card = (348_500, 350_500)
    sung = [(a, b, f"<i>Down the river {k}</i>") for k, (a, b) in enumerate(song)]
    timing = _film(tmp_path, "en.srt", "Line", sung)
    source = _film(tmp_path, "source.srt", "Ligne", [*sung, (*card, "<i>Quelque part au nord</i>")])
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*card, "<i>Quelque part au nord</i>")])
    es = _film(tmp_path, "es.srt", "Línea", [(*card, "<i>En algún lugar del norte</i>")])
    w = tmp_path / "work"
    prepare.build(w, timing, source, None, tracks=[("fr", fr), ("es", es)])
    tail = json.loads((w / "cues.json").read_text(encoding="utf-8"))[LINES:]
    assert tail[3]["source"] == ["<i>Quelque part au nord</i>"] and "on_screen" in tail[3]
    assert [r.get("song", False) for r in tail] == [True, True, True, False, True, True, True]


def test_build_without_tracks_reports_no_on_screen_step(tmp_path: Path):
    summary = prepare.build(tmp_path / "work", _timing(tmp_path), None, None)
    assert summary["on_screen"] is None and summary["cues"] == LINES


def test_track_arg_reads_lang_and_path():
    assert prepare.track_arg("FR=a/b.srt") == ("fr", Path("a/b.srt"))
    assert prepare.track_arg("pt-BR=a.srt") == ("pt-br", Path("a.srt"))
    for bad in ("a/b.srt", "french=a.srt", "fr=", "=a.srt", "pt-=a.srt", "pt_BR=a.srt"):
        with pytest.raises(argparse.ArgumentTypeError):
            prepare.track_arg(bad)


def test_deliver_puts_the_goodbye_before_an_end_title(tmp_path: Path):
    timing = _timing(tmp_path)
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CREDIT, "LE DERNIER PORT")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CREDIT, "EL ÚLTIMO PUERTO")])
    w = tmp_path / "work"
    prepare.build(w, timing, None, None, tracks=[("fr", fr), ("es", es)])
    prepare.chunks(w, target=250)
    tr = "".join(f"{k + 1}\n{k + 1}. satır, burada.\n\n" for k in range(LINES)) + f"{LINES + 1}\nSON LİMAN\n\n"
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    info = assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False, translator="specialone0007")
    # Opening credit, 80 lines, the goodbye 3 s after the last line, then the title.
    assert info["credit_cues"] == [1, LINES + 2]
    shown = _cues(tmp_path / "Film.srt")
    bye, title = shown[LINES + 1], shown[LINES + 2]
    assert bye.lines == [assemble.CREDIT_BYE, "specialone0007"] and title.lines == ["SON LİMAN"]
    last_line = 12_500 + (LINES - 1) * 4_000
    assert (bye.start, bye.end) == (last_line + 3_000, last_line + 7_000) and title.start == CREDIT[0]
    # The delivered map leads every number past the goodbye to its own cue.
    assert [x["delivered"] for x in assemble.where(w, [LINES, LINES + 1])] == [[LINES + 1], [LINES + 3]]
    delivered = json.loads((w / assemble.DELIVERED_MAP_FILE).read_text(encoding="utf-8"))
    assert delivered["credits"] == [1, LINES + 2] and delivered["cues"][str(LINES + 3)] == {"cue": LINES + 1}


def test_build_clears_the_picture_folder_of_an_earlier_run(tmp_path: Path):
    w = tmp_path / "work"
    (w / "screen").mkdir(parents=True)
    (w / "screen" / "ends.json").write_text("{}", encoding="utf-8")
    prepare.build(w, _timing(tmp_path), None, None)
    assert not (w / "screen").exists()
