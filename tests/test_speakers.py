import json
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
    assert speakers.assign_voices(cues, turns) == {1: "V1", 2: "V2", 3: "V2"}


def test_assign_voices_skips_cues_mostly_without_speech():
    assert speakers.assign_voices([cue(1, 0, 1000)], [(0, 200, "A")]) == {}
    assert speakers.assign_voices([cue(1, 0, 1000)], [(0, 300, "A")]) == {1: "V1"}


def test_merge_voices_keeps_labels_and_drops_old_voices():
    old = {"1": {"label": "Sandra", "voice": "V9"}, "5": {"voice": "V9"}, "7": {"name": "Marc"}}
    merged = speakers.merge_voices(old, {1: "V1", 2: "V2"})
    assert merged == {"1": {"label": "Sandra", "voice": "V1"}, "2": {"voice": "V2"}, "7": {"name": "Marc"}}
    assert list(merged) == ["1", "2", "7"]


def test_sync_offset_reports_late_subtitles():
    cues = [cue(i, i * 5000 + 800, i * 5000 + 2000) for i in range(1, 6)]
    starts = [i * 5000 for i in range(1, 6)]
    r = speakers.sync_offset(cues, starts)
    assert r == {"matched_cues": 5, "median_offset_ms": 800, "verdict": "subtitles are 800 ms late"}
    assert speakers.sync_offset(cues, [s + 800 for s in starts])["verdict"] == "in sync"
    assert speakers.sync_offset(cues, [])["median_offset_ms"] is None


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


def test_run_writes_voices_with_models_faked(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    (tmp_path / "timing.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nViens.\n\n2\n00:00:03,000 --> 00:00:04,000\nNon.\n", encoding="utf-8"
    )
    (tmp_path / "speakers.json").write_text(json.dumps({"1": {"label": "Sandra"}}), encoding="utf-8")
    monkeypatch.setattr(speakers, "extract_audio", lambda video, dest: dest)
    monkeypatch.setattr(speakers, "diarize", lambda wav, token: [(900, 2100, "B"), (2900, 4100, "A")])
    monkeypatch.setattr(speakers, "speech_starts", lambda wav: [1000, 3000])
    r = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=True)
    assert r["voices"] == {"V1": 1, "V2": 1} and r["sync"]["verdict"] == "in sync"
    saved = json.loads((tmp_path / "speakers.json").read_text(encoding="utf-8"))
    assert saved == {"1": {"label": "Sandra", "voice": "V1"}, "2": {"voice": "V2"}}


def test_run_without_token_or_config_suggests_the_default_folder(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    fix = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=False)["fix"]
    assert str(speakers.DEFAULT_CONFIG) in fix and '"None"' not in fix


def test_run_keeps_voices_when_the_sync_check_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    (tmp_path / "timing.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nViens.\n", encoding="utf-8")
    monkeypatch.setattr(speakers, "extract_audio", lambda video, dest: dest)
    monkeypatch.setattr(speakers, "diarize", lambda wav, token: [(900, 2100, "A")])

    def broken(wav):
        raise RuntimeError("cublas64_12.dll not found")

    monkeypatch.setattr(speakers, "speech_starts", broken)
    r = speakers.run(tmp_path / "v.mkv", tmp_path, None, sync_check=True)
    assert r["sync"]["verdict"].startswith("sync check failed: RuntimeError")
    assert json.loads((tmp_path / "speakers.json").read_text(encoding="utf-8")) == {"1": {"voice": "V1"}}


def test_speech_starts_falls_back_to_cpu_when_cuda_fails_while_transcribing(monkeypatch):
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
                    raise RuntimeError("cudnn missing")  # raised lazily, as ctranslate2 does
                yield types.SimpleNamespace(start=1.5)

            return segments(), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(speakers, "_device", lambda: "cuda")
    monkeypatch.setattr(speakers, "read_wav", lambda wav: "samples")
    assert speakers.speech_starts(Path("a.wav")) == [1500]


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

    class Pipeline:
        @classmethod
        def from_pretrained(cls, name, use_auth_token):
            import os

            seen["env"] = os.environ.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD")
            return cls()

        def to(self, device):
            return self

        def __call__(self, wav):
            return Result()

    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False), device=lambda d: d)
    pyannote = types.ModuleType("pyannote")
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "pyannote", pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)

    assert speakers.diarize(tmp_path / "a.wav", "hf_x") == [(1000, 2500, "SPEAKER_00")]
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
