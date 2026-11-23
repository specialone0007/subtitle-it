import json
from pathlib import Path

import srt
import transcribe
from transcribe import Word


def _words(*items):
    """(start, end, text) triples as Words."""
    return [Word(s, e, t) for s, e, t in items]


def test_a_pause_over_a_second_starts_a_new_cue():
    cues = transcribe.words_to_cues(
        _words((0.0, 0.4, " Hello"), (0.5, 0.9, " there."), (2.5, 3.0, " Who's"), (3.1, 3.5, " that?"))
    )
    assert cues == [(0, 900, "Hello there."), (2500, 3500, "Who's that?")]


def test_a_sentence_end_closes_a_cue_only_once_it_is_long_enough():
    short = transcribe.words_to_cues(_words((0.0, 0.3, "Yes."), (0.4, 0.8, "Come"), (0.9, 1.2, "in.")))
    assert short == [(0, 1200, "Yes. Come in.")], "a short sentence stays with the next one"
    long_first = "I told you we would be late tonight."
    words = [Word(i * 0.3, i * 0.3 + 0.25, t) for i, t in enumerate(long_first.split())]
    words.append(Word(3.0, 3.3, "Sorry."))
    cues = transcribe.words_to_cues(words)
    assert [c[2] for c in cues] == [long_first, "Sorry."]


def test_a_cue_never_passes_two_lines_or_seven_seconds():
    words = [Word(i * 0.5, i * 0.5 + 0.4, "word") for i in range(40)]
    cues = transcribe.words_to_cues(words)
    assert all(len(line) <= transcribe.LINE for _, _, t in cues for line in transcribe.wrap(t))
    assert all(e - s <= transcribe.MAX_DURATION * 1000 for s, e, _ in cues)
    assert sum(len(t.split()) for _, _, t in cues) == 40, "no word is lost"


def test_a_cue_closes_before_no_two_line_break_fits():
    line = "I told the investigators that the unbelievably complicated paperwork was never filed"
    words = [Word(i * 0.2, i * 0.2 + 0.15, t) for i, t in enumerate(line.split())]
    cues = transcribe.words_to_cues(words)
    assert all(len(x) <= transcribe.LINE for _, _, t in cues for x in transcribe.wrap(t))
    assert " ".join(t for _, _, t in cues) == line


def test_fits_needs_a_break_that_leaves_both_lines_short():
    assert transcribe.fits("Short.")
    assert transcribe.fits("Where did you put the keys? They were on the table this morning.")
    assert not transcribe.fits("I told the investigators that the unbelievably complicated paperwork was never")


def test_empty_words_are_skipped():
    assert transcribe.words_to_cues(_words((0.0, 0.2, " "), (0.3, 0.6, " Hi."))) == [(300, 600, "Hi.")]


def test_wrap_splits_a_long_line_near_the_middle():
    assert transcribe.wrap("Short line.") == ["Short line."]
    lines = transcribe.wrap("I never said she stole the money from the safe, did I?")
    assert len(lines) == 2 and all(len(x) <= transcribe.LINE for x in lines)
    assert " ".join(lines) == "I never said she stole the money from the safe, did I?"


def test_wrap_breaks_after_a_sentence_end_or_a_comma_when_both_lines_fit():
    assert transcribe.wrap("Where did you put the keys? They were on the table this morning.") == [
        "Where did you put the keys?",
        "They were on the table this morning.",
    ]
    assert transcribe.wrap("If you really want to know, ask your mother about the money.") == [
        "If you really want to know,",
        "ask your mother about the money.",
    ]
    short_first = transcribe.wrap("No. I never said she stole the money from the old safe, did I?")
    assert all(len(x) <= transcribe.LINE for x in short_first), "a break that leaves a line too long is not taken"


def test_drop_repeats_keeps_two_in_a_row_and_drops_a_loop():
    cues = [(i * 1000, i * 1000 + 500, "Thank you.") for i in range(5)] + [(9000, 9500, "Bye.")]
    kept = transcribe.drop_repeats(cues)
    assert [c[2] for c in kept] == ["Thank you.", "Thank you.", "Bye."]


def test_to_srt_cues_gives_short_cues_time_but_never_overlaps():
    out = transcribe.to_srt_cues([(0, 200, "Oh."), (500, 900, "Hey."), (5000, 5100, "Go.")])
    assert [(c.start, c.end) for c in out] == [(0, 499), (500, 1200), (5000, 5700)]
    assert out[0].ts == "00:00:00,000 --> 00:00:00,499"
    assert [c.n for c in out] == [1, 2, 3]


def test_run_writes_the_srt_in_the_detected_language(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_extract(video, dest):
        seen["video"] = video
        return dest

    def fake_transcribe(wav, model_name, language):
        seen["model"], seen["language"] = model_name, language
        return _words((1.0, 1.5, " Bonjour."), (3.0, 3.6, " Ça va?")), "fr", 0.97, "cpu"

    monkeypatch.setattr(transcribe.speakers, "extract_audio", fake_extract)
    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    out_path = tmp_path / "out.json"
    transcribe.main(["--result", str(out_path), "run", "--video", str(tmp_path / "film.mkv"), "--work", str(tmp_path / "w")])
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out == {
        "path": str(tmp_path / "w" / "sources" / "asr.fr.srt"),
        "language": "fr",
        "language_probability": 0.97,
        "language_given": False,
        "cues": 2,
        "words": 2,
        "model": "large-v3-turbo",
        "device": "cpu",
    }
    assert seen == {"video": tmp_path / "film.mkv", "model": "large-v3-turbo", "language": None}
    cues, _ = srt.parse(out["path"])
    assert [(c.start, c.text) for c in cues] == [(1000, "Bonjour."), (3000, "Ça va?")]


def test_run_passes_a_given_language_and_model(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_transcribe(wav, model_name, language):
        seen["args"] = (model_name, language)
        return [], language, 1.0, "cuda"

    monkeypatch.setattr(transcribe.speakers, "extract_audio", lambda video, dest: dest)
    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    out = transcribe.run(tmp_path / "film.mkv", tmp_path / "w", "ja", "small")
    assert seen["args"] == ("small", "ja")
    assert out["language_given"] and out["path"].endswith("asr.ja.srt") and out["cues"] == 0


def test_a_gpu_library_error_falls_back_to_the_cpu(tmp_path: Path, monkeypatch):
    import sys
    import types

    devices = []

    class FakeModel:
        def __init__(self, name, device, compute_type):
            devices.append((device, compute_type))
            self.device = device

        def transcribe(self, audio, **kw):
            if self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found")
            seg = types.SimpleNamespace(words=[types.SimpleNamespace(start=0.0, end=0.5, word=" Hi.")])
            return iter([seg]), types.SimpleNamespace(language="en", language_probability=0.9)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(transcribe.speakers, "read_wav", lambda wav: [0.0])
    monkeypatch.setattr(transcribe.speakers, "_device", lambda: "cuda")
    words, lang, prob, device = transcribe.transcribe(tmp_path / "a.wav", "large-v3-turbo", None)
    assert devices == [("cuda", "float16"), ("cpu", "int8")]
    assert (lang, device) == ("en", "cpu") and [w.text for w in words] == [" Hi."]


def test_an_error_unrelated_to_the_gpu_is_raised_not_retried(tmp_path: Path, monkeypatch):
    import sys
    import types

    import pytest

    devices = []

    class FakeModel:
        def __init__(self, name, device, compute_type):
            devices.append(device)
            raise ValueError("Invalid model size 'large-v9'")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(transcribe.speakers, "read_wav", lambda wav: [0.0])
    monkeypatch.setattr(transcribe.speakers, "_device", lambda: "cuda")
    with pytest.raises(ValueError, match="large-v9"):
        transcribe.transcribe(tmp_path / "a.wav", "large-v9", None)
    assert devices == ["cuda"], "no slow CPU retry for an error the CPU would hit too"


# --- sync check -------------------------------------------------------------


def _cue(n, start, text):
    return srt.Cue(n, start, start + 1500, "", text.split("\n"))


def _lines(count=60, gap=2500, first=60_000):
    """Cues with distinct opening words, `gap` ms apart."""
    return [_cue(i, first + i * gap, f"Line number {i} says hello.") for i in range(count)]


def _said(cues, lag_ms, jitter=None):
    """Words a transcript would give for these cues, each cue's words spoken
    `lag_ms` before the cue starts (plus jitter[i], when given)."""
    out = []
    for i, c in enumerate(cues):
        at = (c.start - lag_ms + (jitter[i] if jitter else 0)) / 1000
        for k, w in enumerate(c.plain.split()):
            out.append(Word(at + k * 0.25, at + k * 0.25 + 0.2, " " + w))
    return out


def test_tokens_ignore_case_punctuation_and_curly_apostrophes():
    assert transcribe.tokens("Don’t GO, Sam!") == ["don't", "go", "sam"]
    assert transcribe.tokens("- Who? -Me.") == ["who", "me"]


def test_cue_words_leave_out_sounds_labels_tags_and_songs():
    assert transcribe.cue_words(_cue(1, 0, "[door slams]\nSANDRA: <i>Who is it?</i>")) == ["who", "is", "it"]
    assert transcribe.cue_words(_cue(2, 0, "♪ Who is it ♪")) == []


def test_text_offsets_pair_each_cue_with_where_its_first_words_are_said():
    cues = _lines()
    pairs = transcribe.text_offsets(cues, _said(cues, 650))
    assert len(pairs) == len(cues)
    assert {g for _, g in pairs} == {650}


def test_text_offsets_skip_short_cues_and_anchors_that_could_pair_the_wrong_line():
    cues = _lines(10)
    cues.append(_cue(10, 200_000, "No."))  # too short to anchor
    cues.append(_cue(11, 210_000, "I don't know what you mean."))
    cues.append(_cue(12, 214_000, "I don't know, maybe."))  # same opening near the one before
    words = _said(cues, 650)
    # Line 3's opening said twice by the transcript, near its cue.
    words += [Word(68.2, 68.4, "Line"), Word(68.45, 68.65, "number"), Word(68.7, 68.9, "3")]
    starts = {s for s, _ in transcribe.text_offsets(cues, words)}
    assert starts == {c.start for c in cues[:10]} - {cues[3].start}


def test_text_offsets_find_a_shift_longer_than_the_gap_between_lines():
    cues = _lines(gap=1800)
    pairs = transcribe.text_offsets(cues, _said(cues, -4000))
    assert len(pairs) == len(cues) and {g for _, g in pairs} == {-4000}


def test_sync_verdict_says_how_late_and_how_to_shift():
    pairs = [(i * 1000, 660 + (i % 7) * 10 - 30) for i in range(80)]
    r = transcribe.sync_verdict(pairs, lead_ms=0)
    assert r["verdict"] == "subtitles are 660 ms late" and r["shift_ms"] == -660
    assert r["matches"] == 80 and r["agreeing"] == 1.0 and r["spread_ms"] <= 40
    early = transcribe.sync_verdict([(i, -1234) for i in range(40)], lead_ms=0)
    assert early["verdict"] == "subtitles are 1234 ms early" and early["shift_ms"] == 1230


def test_sync_verdict_takes_whispers_lead_off_the_median():
    r = transcribe.sync_verdict([(i, 700) for i in range(40)], lead_ms=100)
    assert (r["median_gap_ms"], r["offset_ms"], r["shift_ms"]) == (700, 600, -600)
    assert transcribe.sync_verdict([(i, 350) for i in range(40)], lead_ms=100)["verdict"] == "in sync"


def test_sync_verdict_leaves_an_in_sync_file_alone():
    pairs = [(i * 1000, (i * 37) % 400 - 200) for i in range(60)]
    r = transcribe.sync_verdict(pairs, lead_ms=0)
    assert r["verdict"] == "in sync" and r["shift_ms"] == 0


def test_sync_verdict_needs_enough_lines():
    r = transcribe.sync_verdict([(i, 700) for i in range(transcribe.SYNC_MIN_MATCHES - 1)])
    assert r["verdict"].startswith("too little speech matched") and r["shift_ms"] == 0 and r["offset_ms"] is None


def test_sync_verdict_will_not_shift_when_the_gaps_scatter():
    pairs = [(i * 1000, (i * 7919) % 6000 - 3000) for i in range(60)]
    r = transcribe.sync_verdict(pairs, lead_ms=0)
    assert r["verdict"].startswith("no steady offset") and r["shift_ms"] == 0


def test_sync_verdict_will_not_shift_an_offset_that_changes_through_the_film():
    spans = [(0, 100_000), (100_000, 200_000), (200_000, 300_000)]
    pairs = [(s * 1000, 600 if s < 100 else 900 if s < 200 else 1500) for s in range(0, 300, 5)]
    r = transcribe.sync_verdict(pairs, spans, lead_ms=0)
    assert [w["offset_ms"] for w in r["windows"]] == [600, 900, 1500]
    assert r["verdict"].startswith("offset changes through the film") and r["shift_ms"] == 0


def test_sync_check_finds_a_late_file_and_passes_one_in_sync():
    cues = _lines(80)
    jitter = [(i * 53) % 200 - 100 for i in range(80)]
    late = transcribe.sync_verdict(transcribe.text_offsets(cues, _said(cues, 650, jitter)), lead_ms=0)
    assert late["verdict"].endswith("ms late") and abs(late["shift_ms"] + 650) <= 30
    ok = transcribe.sync_verdict(transcribe.text_offsets(cues, _said(cues, 0, jitter)), lead_ms=0)
    assert ok["verdict"] == "in sync"


def test_sync_verdict_gives_no_offset_to_a_stretch_with_few_matches():
    spans = [(0, 100_000), (100_000, 200_000)]
    few = transcribe.SYNC_WINDOW_MIN_MATCHES - 1
    pairs = [(s * 1000, 700) for s in range(0, 100, 2)] + [(150_000 + i, 1500) for i in range(few)]
    r = transcribe.sync_verdict(pairs, spans, lead_ms=0)
    assert [w["offset_ms"] for w in r["windows"]] == [700, None]
    assert r["verdict"] == "subtitles are 700 ms late"


def test_sync_spans_spread_over_the_film_or_cover_a_short_one():
    spans = transcribe.sync_spans(7_200_000)
    assert len(spans) == transcribe.SYNC_WINDOWS
    assert all(b - a == transcribe.SYNC_WINDOW_S * 1000 for a, b in spans)
    assert spans[0][0] > 0 and spans[-1][1] < 7_200_000
    assert transcribe.sync_spans(1_200_000) == [(0, 1_200_000)]


def _fake_whisper(monkeypatch, said, fail_on_cuda=False):
    """A fake faster_whisper whose model says `said[i]` (start s, text) for
    the i-th audio it is given; the audio is the stretch index."""
    import sys
    import types

    devices = []

    class FakeModel:
        def __init__(self, name, device, compute_type):
            devices.append(device)
            self.device = device

        def transcribe(self, audio, **kw):
            if fail_on_cuda and self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found")
            ws = [types.SimpleNamespace(start=t, end=t + 0.2, word=w) for t, w in said[audio]]
            return iter([types.SimpleNamespace(words=ws)]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    cut = iter(range(len(said)))
    monkeypatch.setattr(transcribe, "_cut", lambda video, a, b, dest: dest)
    monkeypatch.setattr(transcribe.speakers, "read_wav", lambda wav: next(cut))
    return devices


def test_window_words_puts_words_in_film_time_and_drops_those_near_a_cut(tmp_path: Path, monkeypatch):
    spans = [(100_000, 280_000), (500_000, 680_000)]
    said = [
        [(1.0, " early"), (10.0, " one"), (179.0, " late")],
        [(0.5, " early"), (20.25, " two"), (178.5, " edge")],
    ]
    _fake_whisper(monkeypatch, said)
    monkeypatch.setattr(transcribe.speakers, "_device", lambda: "cpu")
    words, device = transcribe.window_words(tmp_path / "v.mkv", spans, "small", "en")
    assert device == "cpu"
    assert [(w.start, w.text) for w in words] == [(110.0, " one"), (520.25, " two")]


def test_window_words_keeps_every_word_of_a_single_stretch(tmp_path: Path, monkeypatch):
    _fake_whisper(monkeypatch, [[(0.5, " first"), (59.5, " last")]])
    monkeypatch.setattr(transcribe.speakers, "_device", lambda: "cpu")
    words, _ = transcribe.window_words(tmp_path / "v.mkv", [(0, 60_000)], "small", None)
    assert [w.text for w in words] == [" first", " last"]


def test_window_words_falls_back_to_the_cpu_on_a_gpu_library_error(tmp_path: Path, monkeypatch):
    devices = _fake_whisper(monkeypatch, [[(10.0, " hi")]], fail_on_cuda=True)
    monkeypatch.setattr(transcribe.speakers, "_device", lambda: "cuda")
    words, device = transcribe.window_words(tmp_path / "v.mkv", [(0, 60_000)], "small", None)
    assert devices == ["cuda", "cpu"] and device == "cpu" and [w.text for w in words] == [" hi"]


def test_sync_transcribes_spread_stretches_and_reports_the_offset(tmp_path: Path, monkeypatch):
    cues = _lines(80, gap=60_000, first=30_000)
    for c in cues:
        c.ts = f"{srt.fmt_ms(c.start)} --> {srt.fmt_ms(c.end)}"
    timing = tmp_path / "timing.srt"
    srt.write(timing, cues)
    seen = {}

    def fake_window_words(video, spans, model_name, language):
        seen["spans"], seen["args"] = spans, (model_name, language)
        return _said(srt.parse(timing)[0], 800), "cuda"

    monkeypatch.setattr(transcribe.sources, "probe", lambda video: {"duration_ms": 7_200_000})
    monkeypatch.setattr(transcribe, "window_words", fake_window_words)
    r = transcribe.sync(tmp_path / "v.mkv", timing, "en", "small")
    assert seen["spans"] == transcribe.sync_spans(7_200_000) and seen["args"] == ("small", "en")
    assert r["timing"] == str(timing) and r["device"] == "cuda" and r["model"] == "small"
    assert r["matches"] == 80 and r["words"] == 80 * 5
    assert r["offset_ms"] == 800 - transcribe.WHISPER_LEAD_MS and r["shift_ms"] == -r["offset_ms"]
    assert r["verdict"] == f"subtitles are {r['offset_ms']} ms late"
