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
