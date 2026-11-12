import json
import os
import random
import stat
import statistics
import wave
from pathlib import Path

import pytest

import speakers
import srt


def cue(n, start, end):
    return srt.Cue(n=n, start=start, end=end, ts="", lines=["x"])


def test_assign_voices_by_largest_overlap_and_renames_in_order():
    cues = [cue(1, 0, 1000), cue(2, 1000, 2000), cue(3, 2000, 3000), cue(4, 5000, 6000)]
    turns = [(0, 900, "SPEAKER_07"), (900, 1100, "SPEAKER_02"), (1100, 2600, "SPEAKER_02"), (2600, 3000, "SPEAKER_07")]
    # Cue 3: SPEAKER_02 covers 600 ms, SPEAKER_07 400 ms. Cue 4: nobody speaks.
    assert speakers.assign_voices(cues, turns, margin=1.0) == {1: "V1", 2: "V2", 3: "V2"}


def test_assign_voices_skips_close_calls():
    # Cue 3 above: the runner-up's 400 ms is more than 0.3 x 600 ms.
    cues = [cue(1, 0, 1000), cue(2, 2000, 3000)]
    turns = [(0, 600, "A"), (600, 1000, "B"), (2000, 2850, "A"), (2850, 3000, "B")]
    assert speakers.assign_voices(cues, turns) == {2: "V1"}


def test_assign_voices_skips_cues_with_two_speakers():
    two = srt.Cue(n=1, start=0, end=1000, ts="", lines=["- Who?", "<i>- Me.</i>"])
    one = srt.Cue(n=2, start=1000, end=2000, ts="", lines=["- Who is it?"])
    assert speakers.assign_voices([two, one], [(0, 2000, "A")]) == {2: "V1"}


def test_merge_similar_joins_alike_voices_and_keeps_others():
    turns = [(0, 1000, "A"), (1000, 2000, "B"), (2000, 3000, "C"), (3000, 4000, "D")]
    cent = {"A": [1.0, 0.0], "B": [0.9, 0.1], "C": [0.0, 1.0], "D": [float("nan"), 0.0]}
    merged = [(0, 1000, "A"), (1000, 2000, "A"), (2000, 3000, "C"), (3000, 4000, "D")]
    assert speakers.merge_similar(turns, cent, threshold=0.9) == merged
    assert speakers.merge_similar(turns, cent, threshold=0.999) == turns


def test_merge_similar_relabels_turns_of_an_earlier_merge():
    # B and C merge first (0.96); then A joins their average (0.90), though A
    # and C alone (0.83) are below the threshold. C's turns must end up as A.
    turns = [(0, 1000, "A"), (1000, 2000, "B"), (2000, 3000, "C")]
    cent = {"A": [1.0, 0.0], "B": [0.95, 0.312], "C": [0.83, 0.557]}
    out = speakers.merge_similar(turns, cent, threshold=0.85)
    assert {w for _, _, w in out} == {"A"}


def test_assign_voices_skips_cues_mostly_without_speech():
    assert speakers.assign_voices([cue(1, 0, 1000)], [(0, 200, "A")]) == {}
    assert speakers.assign_voices([cue(1, 0, 1000)], [(0, 300, "A")]) == {1: "V1"}


def test_merge_voices_keeps_labels_and_drops_old_voices():
    old = {"1": {"label": "Sandra", "voice": "V9"}, "5": {"voice": "V9"}, "7": {"name": "Marc"}}
    merged = speakers.merge_voices(old, {1: "V1", 2: "V2"})
    assert merged == {"1": {"label": "Sandra", "voice": "V1"}, "2": {"voice": "V2"}, "7": {"name": "Marc"}}
    assert list(merged) == ["1", "2", "7"]


def test_mixed_voices_finds_a_voice_that_speaks_for_several_characters():
    labels = ["Sam", "Nora", "Leo", "Ivy", "Sam", "Nora", "Leo"]  # V1: four characters
    labels += ["Sam"] * 5 + ["Nora"]  # V2: one character, one stray label
    labels += ["Sam", "Nora", "Sam", "Nora"]  # V3: too few labelled cues to judge
    voices = {n: v for n, v in zip(range(1, 17), ["V1"] * 7 + ["V2"] * 6 + ["V3"] * 4)}
    spk = {str(n): {"label": lab} for n, lab in enumerate(labels, 1)}
    spk["17"] = {"label": "Nora / Sam"}
    voices[17] = "V2"
    mixed = speakers.mixed_voices(spk, voices)
    assert mixed == {"V1": {"labelled_cues": 7, "characters": 4, "top_share": 0.29}}


def test_mixed_voices_counts_label_case_as_one_character():
    spk = {str(n): {"label": "SAM" if n % 2 else "Sam"} for n in range(1, 9)}
    assert speakers.mixed_voices(spk, {n: "V1" for n in range(1, 9)}) == {}


def test_mixed_voices_needs_a_clear_majority():
    # Four of six is exactly two thirds: the voice stays.
    spk = {str(n): {"label": "Sam" if n <= 4 else "Nora"} for n in range(1, 7)}
    assert speakers.mixed_voices(spk, {n: "V1" for n in range(1, 7)}) == {}
    spk["5"] = {"label": "Leo"}
    spk["4"] = {"label": "Ivy"}
    assert list(speakers.mixed_voices(spk, {n: "V1" for n in range(1, 7)})) == ["V1"]


def test_run_drops_the_hints_of_a_mixed_voice(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    blocks = [f"{i}\n00:00:{2 * i:02d},000 --> 00:00:{2 * i + 1:02d},000\nLine {i}.\n" for i in range(1, 10)]
    (tmp_path / "timing.srt").write_text("\n".join(blocks), encoding="utf-8")
    names = ["Sam", "Nora", "Leo", "Ivy", "Sam", "Nora"]
    (tmp_path / "speakers.json").write_text(json.dumps({str(i): {"label": n} for i, n in enumerate(names, 1)}), encoding="utf-8")
    monkeypatch.setattr(speakers, "extract_audio", lambda video, dest: dest)
    turns = [(2000 * i, 2000 * i + 1000, "A" if i <= 6 else "B") for i in range(1, 10)]
    monkeypatch.setattr(speakers, "diarize", lambda wav, token: (turns, {"A": [1.0, 0.0], "B": [0.0, 1.0]}))
    r = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=False)
    assert r["voices_dropped"] == 1 and list(r["mixed_voices"]) == ["V1"]
    assert r["voices"] == {"V2": 3} and r["cues_with_voice"] == 3
    saved = json.loads((tmp_path / "speakers.json").read_text(encoding="utf-8"))
    assert saved["1"] == {"label": "Sam"} and saved["7"] == {"voice": "V2"}


def dialogue(count=120, seed=7):
    """Cue starts 1.2 to 4 s apart, like dialogue: close enough that a 1.5 s
    shift puts a neighbouring line nearer than the right one."""
    rng = random.Random(seed)
    t, starts = 60_000, []
    for _ in range(count):
        t += rng.randint(1200, 4000)
        starts.append(t)
    return starts


def cues_at(starts):
    return [cue(i, s, s + 1000) for i, s in enumerate(starts, 1)]


def test_sync_offset_reports_late_subtitles():
    speech = dialogue()
    r = speakers.sync_offset(cues_at([s + 800 for s in speech]), speech)
    assert (r["median_offset_ms"], r["verdict"]) == (800, "subtitles are 800 ms late")
    assert r["matched_cues"] == r["speech_starts"] == len(speech)
    assert speakers.sync_offset(cues_at(speech), [])["median_offset_ms"] is None


def test_sync_offset_will_not_judge_from_a_few_matches():
    r = speakers.sync_offset(cues_at([1000, 3000]), [1000, 3000])
    assert r["median_offset_ms"] is None and r["verdict"].startswith("too little speech")


@pytest.mark.parametrize("shift", [1000, -1000, 1500, -1500, 3000, -3000, 5000, -5000])
def test_sync_offset_finds_a_clean_shift_past_the_gap_between_lines(shift):
    speech = dialogue()
    r = speakers.sync_offset(cues_at([s + shift for s in speech]), speech)
    assert r["median_offset_ms"] == shift
    assert r["verdict"] == f"subtitles are {abs(shift)} ms {'late' if shift > 0 else 'early'}"


def test_sync_offset_finds_a_shift_through_noise():
    # Speech starts off by up to 250 ms, a third of the lines without a cue,
    # and stray speech starts (breaths, sounds) with no cue at all.
    rng = random.Random(3)
    speech = dialogue()
    subs = [s + 1500 + rng.randint(-250, 250) for s in speech if rng.random() > 0.33]
    stray = [rng.randint(60_000, speech[-1]) for _ in range(40)]
    r = speakers.sync_offset(cues_at(subs), speech + stray)
    assert abs(r["median_offset_ms"] - 1500) <= 100
    assert r["verdict"].startswith("subtitles are") and r["verdict"].endswith("late")


@pytest.mark.parametrize("seed", [0, 1, 3])
def test_sync_offset_recentres_an_off_grid_shift(seed):
    # 1550 ms is between two 100 ms grid steps, and ±280 ms of jitter is
    # wider than the grid window can hold, so the grid's own median is
    # 6 to 20 ms off. Recentring on it once measures every start.
    rng = random.Random(seed)
    speech = dialogue(200, seed=seed + 20)
    subs = [s + 1550 + rng.randint(-280, 280) for s in speech]
    true = statistics.median(c - s for c, s in zip(subs, speech))
    r = speakers.sync_offset(cues_at(subs), speech)
    assert abs(r["median_offset_ms"] - true) <= 2
    assert r["matched_cues"] == len(speech)


def test_sync_offset_result_keys_are_the_same_on_every_path():
    keys = {"matched_cues", "speech_starts", "runner_up_matched", "median_offset_ms", "verdict"}
    speech = dialogue()
    assert set(speakers.sync_offset([], speech)) == keys
    assert set(speakers.sync_offset(cues_at([1000, 3000]), [1000, 3000])) == keys
    assert set(speakers.sync_offset(cues_at(speech), speech)) == keys


def test_sync_offset_leaves_an_in_sync_file_alone():
    rng = random.Random(5)
    speech = dialogue()
    subs = [s + rng.randint(-200, 200) for s in speech]
    r = speakers.sync_offset(cues_at(subs), speech)
    assert r["verdict"] == "in sync"
    assert abs(r["median_offset_ms"]) <= 100


def test_sync_offset_refuses_to_guess_without_a_clear_peak():
    # Speech starts that have nothing to do with the cues.
    rng = random.Random(9)
    speech = sorted(rng.randint(60_000, 400_000) for _ in range(120))
    r = speakers.sync_offset(cues_at(dialogue()), speech)
    assert r["median_offset_ms"] is None
    assert r["verdict"].startswith(("no clear offset", "no speech matched"))


def test_token_from_env_first_then_config(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert speakers.load_token(tmp_path) is None
    (tmp_path / "credentials.json").write_text(json.dumps({"api_key": "k"}), encoding="utf-8")
    speakers.save_token(tmp_path, "hf_x")
    creds = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
    assert creds == {"api_key": "k", "hf_token": "hf_x"}
    assert speakers.load_token(tmp_path) == "hf_x"
    monkeypatch.setenv("HF_TOKEN", "hf_env")
    assert speakers.load_token(tmp_path) == "hf_env"


def test_run_without_token_exits_3_and_touches_nothing(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    res = tmp_path / "results" / "speakers-run.json"
    argv = ["--result", str(res), "run", "--video", str(tmp_path / "v.mkv"), "--work", str(tmp_path), "--config", str(tmp_path)]
    with pytest.raises(SystemExit) as e:
        speakers.main(argv)
    assert e.value.code == speakers.TOKEN_MISSING
    assert json.loads(capsys.readouterr().out)["skipped"] == "token missing"
    # The skill reads the result file, so the skip must be in it too.
    assert json.loads(res.read_text(encoding="utf-8"))["skipped"] == "token missing"
    assert not (tmp_path / "speakers.json").exists()


def test_run_writes_voices_with_models_faked(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    (tmp_path / "timing.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nViens.\n\n2\n00:00:03,000 --> 00:00:04,000\nNon.\n", encoding="utf-8"
    )
    (tmp_path / "speakers.json").write_text(json.dumps({"1": {"label": "Sandra"}}), encoding="utf-8")
    monkeypatch.setattr(speakers, "extract_audio", lambda video, dest: dest)
    turns = [(900, 2100, "B"), (2900, 4100, "A")]
    monkeypatch.setattr(speakers, "diarize", lambda wav, token: (turns, {"A": [1.0, 0.0], "B": [0.0, 1.0]}))
    monkeypatch.setattr(speakers, "speech_starts", lambda wav: [1000, 3000])
    r = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=True)
    assert r["voices"] == {"V1": 1, "V2": 1} and r["voices_before_merge"] == 2
    assert r["sync"]["matched_cues"] == 2 and r["sync"]["verdict"].startswith("too little speech")
    saved = json.loads((tmp_path / "speakers.json").read_text(encoding="utf-8"))
    assert saved == {"1": {"label": "Sandra", "voice": "V1"}, "2": {"voice": "V2"}}
    out, err = capsys.readouterr()
    # Progress goes to stderr only: stdout carries the JSON result.
    assert out == ""
    assert [ln for ln in err.splitlines() if ln.startswith("speakers: ")] == [
        "speakers: extracting the audio",
        "speakers: finding who speaks when (a few minutes on a GPU, about the film's length on a CPU)",
        "speakers: voices saved; checking sync with the audio",
    ]


def test_run_without_token_or_config_suggests_the_default_folder(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    fix = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=False)["fix"]
    assert str(speakers.DEFAULT_CONFIG) in fix and '"None"' not in fix


def test_run_keeps_voices_when_the_sync_check_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    (tmp_path / "timing.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nViens.\n", encoding="utf-8")
    monkeypatch.setattr(speakers, "extract_audio", lambda video, dest: dest)
    monkeypatch.setattr(speakers, "diarize", lambda wav, token: ([(900, 2100, "A")], {}))

    def broken(wav):
        raise RuntimeError("cublas64_12.dll not found")

    monkeypatch.setattr(speakers, "speech_starts", broken)
    r = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=True)
    assert r["sync"]["verdict"].startswith("sync check failed: RuntimeError")
    assert set(r["sync"]) == set(speakers.sync_offset([], []))
    assert json.loads((tmp_path / "speakers.json").read_text(encoding="utf-8")) == {"1": {"voice": "V1"}}


@pytest.mark.parametrize(
    "error",
    [
        "cudnn missing",
        "Requested float16 compute type, but the target device or backend do not support efficient float16 computation.",
    ],
)
def test_speech_starts_falls_back_to_cpu_when_cuda_fails_while_transcribing(monkeypatch, capsys, error):
    import sys
    import types

    class Model:
        def __init__(self, name, device, compute_type):
            self.device = device

        def transcribe(self, audio, **kw):
            # Samples, not a path: given a path, faster-whisper decodes with PyAV.
            assert audio == "samples"

            def segments():
                if self.device == "cuda":
                    raise RuntimeError(error)  # raised lazily, as ctranslate2 does
                yield types.SimpleNamespace(start=1.5)

            return segments(), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(speakers, "_device", lambda: "cuda")
    monkeypatch.setattr(speakers, "read_wav", lambda wav: "samples")
    assert speakers.speech_starts(Path("a.wav")) == [1500]
    assert "trying the CPU" in capsys.readouterr().err


def test_speech_starts_does_not_retry_on_the_cpu_for_other_errors(monkeypatch):
    import sys
    import types

    devices = []

    class Model:
        def __init__(self, name, device, compute_type):
            devices.append(device)

        def transcribe(self, audio, **kw):
            raise ValueError("bad audio")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(speakers, "_device", lambda: "cuda")
    monkeypatch.setattr(speakers, "read_wav", lambda wav: "samples")
    with pytest.raises(ValueError):
        speakers.speech_starts(Path("a.wav"))
    assert devices == ["cuda"]


def test_diarize_allows_full_checkpoint_load_before_the_pipeline_loads(tmp_path: Path, monkeypatch):
    import sys
    import types

    # setenv then delenv: the variable is unset during the test and unset again after it.
    monkeypatch.setenv("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "")
    monkeypatch.delenv("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD")
    seen = {}

    class Segment:
        start, end = 1.0, 2.5

    class Result:
        def itertracks(self, yield_label):
            return [(Segment(), None, "SPEAKER_00")]

        def labels(self):
            return ["SPEAKER_00"]

    class Pipeline:
        @classmethod
        def from_pretrained(cls, name, use_auth_token):
            import os

            seen["env"] = os.environ.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD")
            return cls()

        def to(self, device):
            return self

        def __call__(self, wav, return_embeddings):
            assert return_embeddings
            return Result(), [[0.5, 0.25]]

    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False), device=lambda d: d)
    pyannote = types.ModuleType("pyannote")
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "pyannote", pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)

    assert speakers.diarize(tmp_path / "a.wav", "hf_x") == ([(1000, 2500, "SPEAKER_00")], {"SPEAKER_00": [0.5, 0.25]})
    assert seen["env"] == "1"


def _write_wav(path: Path, samples: list[int], rate: int = 16000, channels: int = 1, width: int = 2) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(width)
        f.setframerate(rate)
        f.writeframes(b"".join(s.to_bytes(width, "little", signed=width > 1) for s in samples))
    return path


def test_read_wav_gives_float_samples_without_pyav(tmp_path: Path):
    audio = speakers.read_wav(_write_wav(tmp_path / "a.wav", [0, 16384, -32768, 32767]))
    assert audio.dtype.name == "float32"
    assert audio.tolist() == [0.0, 0.5, -1.0, 32767 / 32768]


@pytest.mark.parametrize(
    "fmt",
    [{"rate": 44100}, {"channels": 2}, {"width": 1}],
    ids=["44.1 kHz", "stereo", "8-bit"],
)
def test_read_wav_refuses_audio_extract_audio_did_not_make(tmp_path: Path, fmt: dict):
    with pytest.raises(ValueError):
        speakers.read_wav(_write_wav(tmp_path / "b.wav", [0, 0], **fmt))


def test_sync_windows_spread_over_a_long_film_and_cover_a_short_one():
    rate = speakers.SAMPLE_RATE
    film = 100 * 60 * rate
    w = speakers.sync_windows(film)
    assert len(w) == speakers.SYNC_WINDOWS
    assert all(b - a == speakers.SYNC_WINDOW_S * rate for a, b in w)
    assert w[0][0] > 0 and w[-1][1] < film and w == sorted(w)
    assert speakers.sync_windows(20 * 60 * rate) == [(0, 20 * 60 * rate)]


def test_speech_starts_offsets_each_window_and_drops_its_edges(monkeypatch):
    import sys
    import types

    rate = speakers.SAMPLE_RATE
    audio = list(range(60 * rate))  # samples are just their own index here
    seen = []

    class Model:
        def __init__(self, name, device, compute_type):
            pass

        def transcribe(self, audio, **kw):
            seen.append(audio[0])
            # One start inside the window and one at each edge.
            return iter(types.SimpleNamespace(start=s) for s in (0.5, 5.0, 9.5)), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(speakers, "_device", lambda: "cpu")
    monkeypatch.setattr(speakers, "read_wav", lambda wav: audio)
    monkeypatch.setattr(speakers, "sync_windows", lambda n: [(10 * rate, 20 * rate), (40 * rate, 50 * rate)])
    assert speakers.speech_starts(Path("a.wav")) == [15000, 45000]
    assert seen == [10 * rate, 40 * rate]


def test_setup_config_with_a_tilde_means_the_home_folder(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    seen = []
    monkeypatch.setattr(speakers, "setup", seen.append)
    speakers.main(["setup", "--config", "~/cfg"])
    assert seen == [tmp_path / "cfg"]


def test_saved_token_is_readable_only_by_the_owner(tmp_path: Path):
    speakers.save_token(tmp_path, "hf_x")
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "credentials.json").stat().st_mode) == 0o600
