"""On-screen text the timing file lacks, found in other tracks (prepare.on_screen)."""

import argparse
import json
from pathlib import Path

import pytest

import assemble
import polish
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


def _added(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e["state"] == "cue"]


def _left(entries: list[dict], reason: str) -> list[dict]:
    return [e for e in entries if e["state"] == "left_out" and e["reason"] == reason]


def test_a_line_two_languages_show_in_a_gap_is_added(tmp_path: Path):
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Trois jours plus tôt...")])
    es = _film(tmp_path, "es.srt", "Línea", [(CARD[0] + 200, CARD[1] + 100, "TRES DÍAS ANTES...")], offset=150)
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", es)], [])
    assert len(entries) == 1 and summary["added"] == 1 and summary["states"] == {"cue": 1}
    # The first track given leads: its text and times, the shift undone.
    e = entries[0]
    assert e["state"] == "cue" and "reason" not in e and e["id"] == "1:1"
    assert e["lines"] == ["Trois jours plus tôt..."]
    assert (e["start"], e["end"]) == CARD
    assert e["texts"] == {"fr": ["Trois jours plus tôt..."], "es": ["TRES DÍAS ANTES..."]}
    assert e["evidence"] == [
        {"track": 1, "language": "fr", "forced": False, "cue": 1},
        {"track": 2, "language": "es", "forced": False, "cue": 1},
    ]
    assert [t["fits"] for t in summary["tracks"]] == [True, True]


def test_one_language_alone_is_recorded_not_added(tmp_path: Path):
    # A French track also subtitles shouts the English one leaves out.
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Allez!")])
    es = _film(tmp_path, "es.srt", "Línea")
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", es)], [])
    assert _added(entries) == [] and summary["reasons"] == {prepare.ONE_LANGUAGE: 1}
    assert entries[0]["lines"] == ["Allez!"] and (entries[0]["start"], entries[0]["end"]) == CARD
    assert entries[0]["n"] is None and entries[0]["texts"] == {"fr": ["Allez!"]}


def test_credits_sounds_and_one_language_twice_are_never_added(tmp_path: Path):
    song = (5_000, 7_000)  # both tracks sing it: still a song, not on-screen text
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CREDIT, "Sous-titres : Jean"), (*CARD, "Mmmh."), (*song, "♪ La la la ♪")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CREDIT, "Subtítulos: Gabriel"), (*song, "♪ La la la ♪")])
    sdh = _film(tmp_path, "sdh.srt", "Line", [(*CARD, "HARTLEY: Hmm...")])
    en2 = _film(tmp_path, "en2.srt", "Line", [(*CREDIT, "THE END")])
    tracks = [("fr", fr), ("es", es), ("en", sdh), ("en", en2)]
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), tracks, [])
    assert _added(entries) == []
    # "Mmmh." alone is left; "Hmm..." and the song never count. The two
    # credits, shown at the same time, are one entry left out as such.
    assert [e["lines"] for e in _left(entries, prepare.ONE_LANGUAGE)] == [["Mmmh."], ["THE END"]]
    credit = _left(entries, prepare.CREDIT)
    assert len(credit) == 1 and credit[0]["texts"] == {"fr": ["Sous-titres : Jean"], "es": ["Subtítulos: Gabriel"]}
    assert len(entries) == 3


def test_one_language_with_and_without_a_region_is_still_one(tmp_path: Path):
    pt = _film(tmp_path, "pt.srt", "Linha", [(*CARD, "TRÊS DIAS ANTES")])
    br = _film(tmp_path, "br.srt", "Linha", [(*CARD, "TRÊS DIAS ANTES")])
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("pt", pt), ("pt-br", br)], [])
    assert _added(entries) == [] and summary["reasons"] == {prepare.ONE_LANGUAGE: 1}


def test_a_forced_track_alone_is_enough_and_is_not_shifted(tmp_path: Path):
    forced = tmp_path / "forced.srt"
    forced.write_text(f"1\n{srt.fmt_ms(CARD[0])} --> {srt.fmt_ms(CARD[1])}\nLUNDHAVEN, 1890\n", encoding="utf-8")
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), [], [("en", forced)])
    assert [e["lines"] for e in _added(entries)] == [["LUNDHAVEN, 1890"]]
    assert entries[0]["evidence"] == [{"track": 1, "language": "en", "forced": True, "cue": 1}]
    assert summary["tracks"][0]["forced"] is True and "fits" not in summary["tracks"][0]


def test_the_id_names_the_first_track_and_a_forced_track_gives_the_text(tmp_path: Path):
    forced = tmp_path / "forced.srt"
    forced.write_text(f"1\n{srt.fmt_ms(CARD[0])} --> {srt.fmt_ms(CARD[1])}\nLUNDHAVEN, 1890\n", encoding="utf-8")
    tracks = _two(tmp_path, [(*CARD, "LUNDHAVEN")], [(*CARD, "LUNDHAVEN (1890)")])
    entries, _ = prepare.on_screen(_cues(_timing(tmp_path)), tracks, [("en", forced)])
    # Tracks come before forced tracks in the list: the forced one is 3rd.
    assert [(e["id"], e["lines"]) for e in _added(entries)] == [("1:1", ["LUNDHAVEN, 1890"])]


def test_order_tracks_keeps_the_first_and_english_in_front_and_sorts_the_rest():
    p = Path
    given = [
        ("fr", p("dl/fr.srt")),
        ("fin", p("s/track10.fin.srt")),
        ("en", p("s/track1_fit.srt")),
        ("de", p("dl/a.de.srt")),
        ("ar", p("s/track2.ar.srt")),
        ("en-gb", p("s/track5.en.srt")),
        ("heb", p("s/Track12.heb.srt")),
    ]
    assert prepare.order_tracks(given) == [
        # The first one given, then English in the order given.
        ("fr", p("dl/fr.srt")),
        ("en", p("s/track1_fit.srt")),
        ("en-gb", p("s/track5.en.srt")),
        # Then track<N> by number (2 before 10), then other files by name.
        ("ar", p("s/track2.ar.srt")),
        ("fin", p("s/track10.fin.srt")),
        ("heb", p("s/Track12.heb.srt")),
        ("de", p("dl/a.de.srt")),
    ]
    assert prepare.order_tracks([]) == []


def test_the_same_tracks_in_any_order_give_the_same_entries(tmp_path: Path):
    # One 2026 film: the title card's text came from whichever track
    # the session happened to list first after English.
    en = _film(tmp_path, "track1_fit.srt", "Line", [(*CREDIT, "THE END")])
    rest = [
        ("heb", _film(tmp_path, "track12.heb.srt", "Shura", [(*CARD, "HEBREW TITLE")], offset=-44)),
        ("ar", _film(tmp_path, "track2.ar.srt", "Satr", [(*CARD, "ARABIC TITLE")], offset=-50)),
        ("de", _film(tmp_path, "download.de.srt", "Zeile", [(*CARD, "GERMAN TITLE")])),
        ("fin", _film(tmp_path, "track10.fin.srt", "Rivi", [(*CARD, "FINNISH TITLE"), (*CREDIT, "LOPPU")], offset=-300)),
    ]
    timing = _cues(_timing(tmp_path))
    runs = [
        prepare.on_screen(timing, [("en", en), *order], [], timing_language="en")
        for order in (rest, rest[::-1], rest[1:] + rest[:1])
    ]
    assert runs[0] == runs[1] == runs[2]
    entries, summary = runs[0]
    card = _added(entries)[0]
    # English first, then track2 (Arabic) before track10 and track12; the
    # download last.
    assert card["lines"] == ["ARABIC TITLE"] and card["id"] == "2:1" and (card["start"], card["end"]) == CARD
    assert list(card["texts"]) == ["ar", "fin", "heb", "de"]
    assert [t["language"] for t in summary["tracks"]] == ["en", "ar", "fin", "heb", "de"]
    # English keeps its lead over every other track: the end title is its.
    assert [e["lines"] for e in entries if e["start"] >= CREDIT[0]] == [["THE END"]]


def test_a_track_that_does_not_fit_is_left_out(tmp_path: Path):
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "Une carte")])
    # Every line two seconds apart from the timing file's: another cut.
    other = "".join(f"{k + 1}\n{srt.fmt_ms(k * 2_000)} --> {srt.fmt_ms(k * 2_000 + 900)}\nUna {k}\n\n" for k in range(200))
    (tmp_path / "es.srt").write_text(other, encoding="utf-8")
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", tmp_path / "es.srt")], [])
    assert _added(entries) == [] and summary["reasons"] == {prepare.ONE_LANGUAGE: 1}
    assert summary["tracks"][1]["fits"] is False and summary["tracks"][1]["reason"]


def test_an_added_cue_is_clipped_between_its_neighbours_or_dropped(tmp_path: Path):
    # Starts inside the first line's gap and runs into it: clipped to end
    # where the first line starts. A second one with no room left is dropped.
    late = (7_000, 10_400)  # the first line starts at 0:10
    tight = (12_600, 13_000)  # 400 ms between line 1 (ends 12,500) and line 2
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*late, "LONDRES"), (*tight, "PARIS")])
    es = _film(tmp_path, "es.srt", "Línea", [(*late, "LONDRES"), (*tight, "PARÍS")])
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), [("fr", fr), ("es", es)], [])
    assert [(a["start"], a["end"]) for a in _added(entries)] == [(7_000, 10_000)]
    # Recorded with the track's own times.
    assert [(e["start"], e["end"], e["lines"]) for e in _left(entries, prepare.NO_ROOM)] == [(*tight, ["PARIS"])]


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


def test_deliver_puts_the_goodbye_after_an_end_title(tmp_path: Path):
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
    # Opening credit, 80 lines, the title, then the goodbye 3 s after it:
    # nothing translated follows the goodbye.
    assert info["credit_cues"] == [1, LINES + 3] and info["goodbye"] == assemble.GOODBYE_AFTER_LINE
    shown = _cues(tmp_path / "Film.srt")
    title, bye = shown[LINES + 1], shown[LINES + 2]
    assert bye.lines == [assemble.CREDIT_BYE, "specialone0007"] and title.lines == ["SON LİMAN"]
    assert title.start == CREDIT[0] and (bye.start, bye.end) == (CREDIT[1] + 3_000, CREDIT[1] + 7_000)
    assert [x["delivered"] for x in assemble.where(w, [LINES, LINES + 1])] == [[LINES + 1], [LINES + 2]]
    delivered = json.loads((w / assemble.DELIVERED_MAP_FILE).read_text(encoding="utf-8"))
    assert delivered["credits"] == [1, LINES + 3] and delivered["cues"][str(LINES + 2)] == {"cue": LINES + 1}


def test_build_clears_the_picture_folder_of_an_earlier_run(tmp_path: Path):
    w = tmp_path / "work"
    (w / "screen").mkdir(parents=True)
    (w / "screen" / "ends.json").write_text("{}", encoding="utf-8")
    prepare.build(w, _timing(tmp_path), None, None)
    assert not (w / "screen").exists()


# --- the list: every text found is recorded (on_screen.json) ---------------


def _two(tmp: Path, extra_fr: list, extra_es: list) -> list[tuple[str, Path]]:
    return [("fr", _film(tmp, "fr.srt", "Ligne", extra_fr)), ("es", _film(tmp, "es.srt", "Línea", extra_es))]


def _entries(w: Path) -> list[dict]:
    return json.loads((w / prepare.ON_SCREEN_FILE).read_text(encoding="utf-8"))


def _translate(w: Path) -> None:
    """A Turkish line for every cue the build kept, as a translator writes."""
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{r['n']}\n{r['n']}. satır.\n\n" for r in rows if not prepare.left_out(r))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")


# Between line 36 (ends 2:32.5) and line 37 (starts 2:34).
MIDDLE = (152_600, 153_800)


def test_build_writes_every_entry_found_and_numbers_the_added_ones(tmp_path: Path):
    tracks = _two(tmp_path, [(*CARD, "UN JOUR"), (*MIDDLE, "Hé!"), (*CREDIT, "# Au revoir #")], [(*CARD, "UN DÍA")])
    w = tmp_path / "work"
    summary = prepare.build(w, _timing(tmp_path), None, None, tracks=tracks)
    entries = _entries(w)
    assert [(e["state"], e.get("reason"), e["n"]) for e in entries] == [
        ("cue", None, 1),
        ("left_out", prepare.ONE_LANGUAGE, None),
        ("left_out", prepare.SONG_LINE, None),
    ]
    assert entries[0]["id"] == "1:1" and entries[1]["lines"] == ["Hé!"] and entries[2]["start"] == CREDIT[0]
    info = summary["on_screen"]
    assert info["added"] == 1 and info["states"] == {"cue": 1, "left_out": 2}
    assert info["reasons"] == {prepare.ONE_LANGUAGE: 1, prepare.SONG_LINE: 1}
    # Every line of the two tracks that the timing file covers: 80 each.
    assert info["covered_lines"] == 2 * LINES and info["dropped_timing_cues"] == []
    assert info["file"] == str(w / prepare.ON_SCREEN_FILE)
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert len(rows) == LINES + 1 and "on_screen" in rows[0]


def test_a_build_with_no_tracks_writes_an_empty_list(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None, tracks=_two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")]))
    assert len(_entries(w)) == 1
    prepare.build(w, _timing(tmp_path), None, None)
    assert _entries(w) == []


def _sung(tmp: Path) -> Path:
    """The timing file with an italic song of six lines from 5:40."""
    song = [(340_000 + k * 3_000, 342_000 + k * 3_000, f"<i>Down the river {k}</i>") for k in range(6)]
    return _film(tmp, "en.srt", "Line", song)


def test_a_sign_two_languages_show_during_a_song_is_recorded_not_placed(tmp_path: Path):
    # The tracks translate the lyric, marked by italics alone: placing it
    # would add the song as cues. A line one language shows there is the
    # timing file's own, counted as covered.
    fr = [(343_000, 345_000, "LE FLEUVE"), (346_000, 348_000, "Au fil de l'eau")]
    tracks = _two(tmp_path, fr, [(343_000, 345_000, "EL RÍO")])
    w = tmp_path / "work"
    summary = prepare.build(w, _sung(tmp_path), None, None, tracks=tracks)
    entries = _entries(w)
    assert [(e["state"], e["reason"], e["texts"]) for e in entries] == [
        ("left_out", prepare.DURING_SONG, {"fr": ["LE FLEUVE"], "es": ["EL RÍO"]})
    ]
    assert summary["cues"] == LINES + 6 and summary["on_screen"]["covered_lines"] == 2 * LINES + 1


def test_a_line_over_speech_is_never_recorded_even_in_two_languages(tmp_path: Path):
    # Line 1 runs 0:10 to 0:12.5: two languages show something over it.
    tracks = _two(tmp_path, [(10_000, 12_500, "ROME")], [(10_000, 12_500, "ROMA")])
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), tracks, [])
    assert entries == [] and summary["covered_lines"] == 2 * LINES + 2


def test_a_sound_description_kept_by_hi_keep_does_not_hide_a_sign(tmp_path: Path):
    # With --hi keep, "[thunder]" stays in the timing file and covers the card.
    timing = _film(tmp_path, "en.srt", "Line", [(*CARD, "[thunder]")])
    w = tmp_path / "work"
    prepare.build(w, timing, None, None, hi="keep", tracks=_two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")]))
    assert [(e["state"], e["reason"]) for e in _entries(w)] == [("left_out", prepare.DURING_SONG)]


# --- an entry is never lost inside build or check ---------------------------


def test_a_card_is_never_a_song_or_a_bare_sound_whatever_the_source_says(tmp_path: Path):
    # The source file, in another language, has a lyric and a bare sound
    # where the tracks show two cards: the rows stay cards.
    second = (5_000, 8_000)
    source = _film(tmp_path, "source.srt", "Ligne", [(*CARD, "♪ La la la ♪"), (*second, "Oh.")])
    tracks = _two(tmp_path, [(*CARD, "UN JOUR"), (*second, "LA FIN")], [(*CARD, "UN DÍA"), (*second, "EL FIN")])
    w = tmp_path / "work"
    summary = prepare.build(w, _timing(tmp_path), source, None, tracks=tracks)
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert [("on_screen" in r, r.get("song"), r.get("left_out")) for r in rows[:2]] == [(True, None, None)] * 2
    assert summary["song_cues"] == 0 and summary["bare_sound_cues_dropped"] == 0


def test_check_never_cleans_a_card_into_a_sound(tmp_path: Path):
    w = tmp_path / "work"
    w.mkdir()
    (w / "build.json").write_text(json.dumps({"hearing_impaired_tags": "remove", "hearing_impaired": {"timing": True}}))
    row = {"timing_lines": ["(PARIS)"], "source": ["[music]"]}
    rows = {1: {"n": 1, **row, "on_screen": {"fr": ["PARIS"]}}, 2: {"n": 2, **row}}
    assert assemble.sound_only_cues(w, rows) == {2}


def test_check_fails_when_an_added_entry_has_no_cue_that_is_delivered(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None, tracks=_two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")]))
    _translate(w)
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    rows[0]["left_out"] = "sound"
    (w / "cues.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    hard = assemble.run_checks(w)["hard"]
    assert [x for x in hard if x["check"] == "on-screen text"] == [
        {"cue": 1, "check": "on-screen text", "detail": "entry 1:1 has no cue that is delivered"}
    ]


def test_every_left_out_value_on_a_row_has_a_note(tmp_path: Path):
    # Entry reasons stay in on_screen.json; only the values `build` and
    # `songs` write on rows reach check, `where` and the review.
    timing = _film(tmp_path, "en.srt", "Line", [(5_000, 6_000, "Oh."), (7_000, 8_500, "♪ La la ♪")])
    tracks = _two(tmp_path, [(*CREDIT, "Allez!"), (2_000, 4_000, "Sous-titres : Jean")], [])
    w = tmp_path / "work"
    prepare.build(w, timing, None, None, tracks=tracks)
    prepare.songs(w, "skip")
    values = {r["left_out"] for r in json.loads((w / "cues.json").read_text(encoding="utf-8")) if r.get("left_out")}
    assert values == {"sound", "song"} and values <= set(assemble.LEFT_OUT_NOTES)
    assert {e["reason"] for e in _entries(w)} == {prepare.ONE_LANGUAGE, prepare.CREDIT}


# --- the sync rebuild keeps every cue number --------------------------------


def _shifted(tmp: Path, path: Path, ms: int) -> Path:
    out = tmp / f"shifted_{ms}_{path.name}"
    srt.write(out, srt.shift(srt.parse(path)[0], ms))
    return out


def test_a_shift_rebuild_moves_the_entries_and_keeps_every_number(tmp_path: Path):
    # A hearing-impaired timing file: "[somber music]" under the card is
    # dropped by the first build, and must be dropped again.
    timing = _film(tmp_path, "en.srt", "Line", [(*CARD, "[somber music]"), (*CREDIT, "♪ Fin ♪")])
    tracks = _two(tmp_path, [(*CARD, "UN JOUR"), (*MIDDLE, "Hé!")], [(*CARD, "UN DÍA")])
    w = tmp_path / "work"
    first = prepare.build(w, timing, None, None, tracks=tracks)
    assert first["on_screen"]["dropped_timing_cues"] == [1]
    rows_before, entries_before = json.loads((w / "cues.json").read_text(encoding="utf-8")), _entries(w)
    (w / "screen").mkdir()
    shift = -700
    # No track given: the entries come from on_screen.json, not found again.
    again = prepare.build(w, _shifted(tmp_path, timing, shift), None, None, keep_bible_check=True, shift_ms=shift)
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert [(r["n"], r["timing_lines"]) for r in rows] == [(r["n"], r["timing_lines"]) for r in rows_before]
    assert [r["start"] - b["start"] for r, b in zip(rows, rows_before)] == [shift] * len(rows)
    assert [(e["id"], e["n"], e["start"] - b["start"]) for e, b in zip(_entries(w), entries_before)] == [
        (b["id"], b["n"], shift) for b in entries_before
    ]
    assert again["on_screen"]["shift_ms"] == shift and again["on_screen"]["dropped_timing_cues"] == [1]
    assert again["on_screen"]["cues"][0]["ts"] == srt.fmt_ms(CARD[0] + shift)
    assert (w / "screen").exists()


def test_the_same_shift_rebuild_twice_moves_the_entries_once(tmp_path: Path):
    timing = _film(tmp_path, "en.srt", "Line", [])
    tracks = _two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")])
    w = tmp_path / "work"
    prepare.build(w, timing, None, None, tracks=tracks)
    files = ("cues.json", "on_screen.json")

    def rebuild(ms: int) -> tuple[str, ...]:
        info = prepare.build(w, _shifted(tmp_path, timing, ms), None, None, keep_bible_check=True, shift_ms=ms)
        assert info["on_screen"]["shift_ms"] == ms
        return tuple((w / f).read_text(encoding="utf-8") for f in files)

    once = rebuild(-700)
    assert rebuild(-700) == once
    # A card held at 0:00 by one shift goes back to its own time with the next.
    rebuild(-(CARD[0] + 5_000))
    assert [e["start"] for e in _entries(w) if e["state"] == "cue"] == [0]
    assert rebuild(-700) == once


def test_a_shift_rebuild_keeps_the_numbers_where_a_card_and_a_line_reach_0_00(tmp_path: Path):
    # The card ends 0.1 s before a line; moved 4 s earlier, both start at
    # 0:00, as `srt.py shift` moves a cue no earlier than that.
    hello = (CARD[1] + 100, CARD[1] + 1_500)
    timing = _film(tmp_path, "en.srt", "Line", [(*hello, "Hello.")])
    tracks = _two(tmp_path, [(*CARD, "UN JOUR"), (*hello, "Bonjour.")], [(*CARD, "UN DÍA"), (*hello, "Hola.")])
    w = tmp_path / "work"
    assert prepare.build(w, timing, None, None, tracks=tracks)["on_screen"]["added"] == 1
    prepare.build(w, _shifted(tmp_path, timing, -4_000), None, None, shift_ms=-4_000)
    rows = json.loads((w / "cues.json").read_text(encoding="utf-8"))
    assert [(r["n"], r["start"], "on_screen" in r) for r in rows[:2]] == [(1, 0, True), (2, 0, False)]
    assert rows[1]["timing_lines"] == ["Hello."]


def test_a_shift_rebuild_of_an_older_folder_finds_the_entries_again(tmp_path: Path):
    w = tmp_path / "work"
    tracks = _two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")])
    prepare.build(w, _timing(tmp_path), None, None, tracks=tracks)
    (w / prepare.ON_SCREEN_FILE).unlink()
    summary = prepare.build(w, _shifted(tmp_path, _timing(tmp_path), 400), None, None, tracks=tracks, shift_ms=400)
    assert summary["on_screen"]["added"] == 1 and _entries(w)[0]["start"] == CARD[0] + 400


# --- what the review, the listener and the report see -----------------------


def test_the_review_and_listen_parts_mark_a_card(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None, tracks=_two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")]))
    _translate(w)
    assemble.run_checks(w)
    review = Path(assemble.review_parts(w, size=50)["parts"][0]["file"]).read_text(encoding="utf-8")
    assert "\n1\ton-screen text\tUN JOUR\t" in review and "\n2\t\tLine 1, here.\t" in review
    listen = Path(assemble.listen_parts(w, size=50)["parts"][0]["file"]).read_text(encoding="utf-8")
    assert "\n1\t00:00:01\ton-screen text\t" in listen


def test_deliver_reports_each_entry_delivered_and_left_out_at_the_ends(tmp_path: Path):
    fr = [(*CARD, "UN JOUR"), (5_000, 7_000, "Psst!"), (*MIDDLE, "Hé!"), (*CREDIT, "Merci."), (350_000, 352_000, "LA FIN")]
    tracks = _two(tmp_path, fr, [(*CARD, "UN DÍA"), (350_000, 352_000, "EL FIN")])
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None, tracks=tracks)
    _translate(w)
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    info = assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False)
    report = info["on_screen"]
    # The card leaves no room for the opening credit; the end title comes
    # before the goodbye.
    assert report["delivered"] == [
        {"cue": [1], "at": "00:00:01,000", "text": "UN JOUR", "turkish": "1. satır."},
        {"cue": [LINES + 2], "at": "00:05:50,000", "text": "LA FIN", "turkish": f"{LINES + 2}. satır."},
    ]
    # One line before the first spoken cue, one after story end; the one
    # in the middle is only counted.
    assert report["left_out_at_ends"] == [
        {"at": "00:00:05,000", "text": "Psst!", "reason": prepare.ONE_LANGUAGE},
        {"at": "00:05:40,000", "text": "Merci.", "reason": prepare.ONE_LANGUAGE},
    ]
    assert report["left_out"] == {prepare.ONE_LANGUAGE: 1}
    assert report["file"] == str(w / prepare.ON_SCREEN_FILE) and report["limits"] == list(assemble.ON_SCREEN_LIMITS)
    assert report["unplaced_human_lines"] == []
    assert json.loads((w / "delivered.json").read_text(encoding="utf-8"))["on_screen"] == report


def test_deliver_lists_human_lines_placed_nowhere_unless_a_card_is_delivered_there(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None, tracks=_two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")]))
    # A polish run: the human file's lines that landed on no cue, with times.
    _translate(w)
    (w / "out" / "tr_01.txt").rename(w / "out" / "tr_00.txt")
    unplaced = [
        {"near": [1], "start": CARD[0], "end": CARD[1], "text": "BİR GÜN"},
        {"near": [36, 37], "start": MIDDLE[0], "end": MIDDLE[1], "text": "MERKEZ"},
    ]
    (w / "polish_placement.json").write_text(json.dumps({"joined": [], "unplaced": unplaced}), encoding="utf-8")
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    info = assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False)
    assert info["on_screen"]["unplaced_human_lines"] == [{"at": "00:02:32,600", "text": "MERKEZ"}]


def test_a_polish_seed_records_when_each_unplaced_line_is_shown(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None)
    tr = tmp_path / "tr.srt"
    tr.write_text(f"1\n{srt.fmt_ms(MIDDLE[0])} --> {srt.fmt_ms(MIDDLE[1])}\nMERKEZ\n", encoding="utf-8")
    polish.seed(w, tr)
    placement = json.loads((w / polish.PLACEMENT_FILE).read_text(encoding="utf-8"))
    assert placement["unplaced"] == [{"near": [36, 37], "start": MIDDLE[0], "end": MIDDLE[1], "text": "MERKEZ"}]


def test_a_sign_under_a_sound_and_a_spoken_line_at_once_is_only_counted(tmp_path: Path):
    # "[thunder]" alone would make the card an entry shown during a sound;
    # a spoken line over it too means the timing file has the screen.
    timing = _film(tmp_path, "en.srt", "Line", [(1_000, 2_500, "[thunder]"), (2_500, 4_000, "Who's there?")])
    tracks = _two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")])
    w = tmp_path / "work"
    summary = prepare.build(w, timing, None, None, hi="keep", tracks=tracks)
    assert _entries(w) == [] and summary["on_screen"]["covered_lines"] == 2 * LINES + 2


def test_check_fails_when_an_added_entry_names_a_cue_the_rows_lack(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None, tracks=_two(tmp_path, [(*CARD, "UN JOUR")], [(*CARD, "UN DÍA")]))
    _translate(w)
    entries = _entries(w)
    entries[0]["n"] = 999
    (w / prepare.ON_SCREEN_FILE).write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    hard = assemble.run_checks(w)["hard"]
    assert [x["cue"] for x in hard if x["check"] == "on-screen text"] == [999]


def test_deliver_reports_no_on_screen_section_for_an_older_folder(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None)
    (w / prepare.ON_SCREEN_FILE).unlink()
    _translate(w)
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    assert assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=False)["on_screen"] is None


def test_deliver_stops_on_a_malformed_on_screen_file_before_any_file_moves(tmp_path: Path):
    w = tmp_path / "work"
    prepare.build(w, _timing(tmp_path), None, None)
    _translate(w)
    assert assemble.run_checks(w)["hard_fail_count"] == 0
    # A cue entry with no number: the report reads it after the file moves.
    cue = {"state": "cue", "start": 1_000, "end": 2_000, "lines": ["FIN"]}
    for bad in ([{"n": 1}], [cue]):
        (w / prepare.ON_SCREEN_FILE).write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(SystemExit, match="is malformed"):
            assemble.deliver(w, tmp_path / "Film.srt", tmp_path / "backups", force=True)
        assert not (tmp_path / "Film.srt").exists() and not (w / "delivered.json").exists()


# --- many languages: a share of them must show the line ----------------------

LANGS = ["fr", "es", "de", "it", "nl", "pl", "sv", "fi"]


def _many(tmp: Path, langs: list[str], showing: int, text: str = "FARMACIA") -> list[tuple[str, Path]]:
    """One track per language; the first `showing` of them show `text` in the card's gap."""
    return [
        (lang, _film(tmp, f"{lang}_{k}.srt", "Ligne", [(*CARD, text)] if k < showing else [])) for k, lang in enumerate(langs)
    ]


@pytest.mark.parametrize(
    "n, need",
    [(0, 2), (1, 2), (5, 2), (6, 5), (8, 6), (31, 24)],
)
def test_the_share_starts_at_six_other_languages(n: int, need: int):
    assert prepare.need_languages(n) == need


def test_with_many_languages_a_line_too_few_show_is_left_out(tmp_path: Path):
    # Eight other languages: six must show it. Five is a sign in the background.
    timing = _cues(_timing(tmp_path))
    entries, summary = prepare.on_screen(timing, _many(tmp_path, LANGS, 5), [], timing_language="en")
    assert _added(entries) == [] and summary["reasons"] == {prepare.FEW_LANGUAGES: 1}
    assert summary["languages_needed"] == 6
    entries, summary = prepare.on_screen(timing, _many(tmp_path, LANGS, 6), [], timing_language="en")
    assert len(_added(entries)) == 1


def test_with_few_languages_two_still_prove(tmp_path: Path):
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), _many(tmp_path, LANGS[:4], 2), [], timing_language="en")
    assert len(_added(entries)) == 1 and summary["languages_needed"] == 2


def test_the_timing_language_counts_neither_in_the_share_nor_for_the_line(tmp_path: Path):
    # English and six others: n is 6, so five of the others must show it.
    # English and four others show it: four is too few.
    langs = ["en", *LANGS[:6]]
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), _many(tmp_path, langs, 5), [], timing_language="en")
    assert summary["languages_needed"] == 5 and _added(entries) == []
    assert summary["reasons"] == {prepare.FEW_LANGUAGES: 1}


def test_a_forced_track_still_proves_alone_among_many_languages(tmp_path: Path):
    forced = tmp_path / "forced.srt"
    forced.write_text(f"1\n{srt.fmt_ms(CARD[0])} --> {srt.fmt_ms(CARD[1])}\nFARMACIA\n\n", encoding="utf-8")
    entries, _ = prepare.on_screen(_cues(_timing(tmp_path)), _many(tmp_path, LANGS, 0), [("es", forced)], timing_language="en")
    assert len(_added(entries)) == 1


@pytest.mark.parametrize(
    "text",
    ["Azpitituluak: Miren", "Ikuskatzailea: Jon"],
)
def test_basque_subtitle_credits_are_credits(text: str):
    assert prepare.CREDIT_RE.search(text)


def test_a_line_shown_with_a_subtitle_credit_is_a_credit_too(tmp_path: Path):
    # "Creative supervisor" reads as a credit in no language, but the
    # Basque track names the supervisor at the same time.
    timing = _cues(_timing(tmp_path))
    tracks = _many(tmp_path, LANGS, 8, "Supervision créative / Jean")
    eu = _film(tmp_path, "eu.srt", "Lerroa", [(*CARD, "Ikuskatzailea: Jon")])
    entries, summary = prepare.on_screen(timing, [*tracks, ("eu", eu)], [], timing_language="en")
    assert _added(entries) == [] and summary["reasons"] == {prepare.CREDIT: 1}
    assert len(entries[0]["texts"]) == 9


def test_below_six_languages_a_credit_at_the_same_time_leaves_a_card_alone(tmp_path: Path):
    # French and Spanish show a card while the German track's subtitle
    # credit overlaps it: with three other languages the card is added.
    fr = _film(tmp_path, "fr.srt", "Ligne", [(*CARD, "UN JOUR")])
    es = _film(tmp_path, "es.srt", "Línea", [(*CARD, "UN DÍA")])
    de = _film(tmp_path, "de.srt", "Zeile", [(*CARD, "Untertitel: Hans")])
    tracks = [("fr", fr), ("es", es), ("de", de)]
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), tracks, [], timing_language="en")
    assert [e["lines"] for e in _added(entries)] == [["UN JOUR"]]
    assert summary["reasons"] == {prepare.CREDIT: 1}


def test_the_share_counts_a_region_once_and_leaves_out_tracks_that_do_not_fit(tmp_path: Path):
    # pt and pt-br are one language, and a track that does not fit counts
    # for nothing: five other languages in all, so two still prove.
    tracks = _many(tmp_path, ["fr", "es", "de", "it"], 1)
    tracks.append(("pt", _film(tmp_path, "pt.srt", "Linha", [(*CARD, "FARMÁCIA")])))
    tracks.append(("pt-br", _film(tmp_path, "br.srt", "Linha", [(*CARD, "FARMÁCIA")])))
    far = tmp_path / "far.srt"
    far.write_text("1\n00:50:00,000 --> 00:50:02,000\nLoin.\n\n", encoding="utf-8")
    tracks.append(("nl", far))
    entries, summary = prepare.on_screen(_cues(_timing(tmp_path)), tracks, [], timing_language="en")
    assert summary["languages_needed"] == 2 and len(_added(entries)) == 1
