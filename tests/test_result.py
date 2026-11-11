import json
from pathlib import Path

import pytest

import assemble
import learn
import result
import sources
import srt


def test_emit_prints_and_writes_the_same_json(tmp_path: Path, capsys):
    path = tmp_path / "results" / "x.json"
    result.emit({"film": "Çılgın", "n": [1, 2]}, path)
    printed = capsys.readouterr().out
    assert json.loads(printed) == {"film": "Çılgın", "n": [1, 2]}
    assert path.read_text(encoding="utf-8") == printed
    assert "Çılgın" in printed  # kept readable, not \u escapes


def test_emit_without_a_path_only_prints(tmp_path: Path, capsys):
    result.emit([], None)
    assert json.loads(capsys.readouterr().out) == []
    assert list(tmp_path.iterdir()) == []


def test_a_failed_run_leaves_no_stale_result(tmp_path: Path):
    path = tmp_path / "sources-validate.json"
    path.write_text('{"old": true}', encoding="utf-8")
    with pytest.raises(OSError):
        sources.main(["--result", str(path), "validate", "--file", str(tmp_path / "missing.srt")])
    assert not path.exists()


def test_slug_result_is_an_object_with_a_bare_name(tmp_path: Path):
    path = tmp_path / "slug.json"
    sources.main(["--result", str(path), "slug", "Harbour Lights (2026)"])
    assert json.loads(path.read_text(encoding="utf-8")) == {"slug": "harbour-lights-2026"}


def test_remember_command_writes_its_result_and_the_folder(tmp_path: Path):
    prefs = tmp_path / "preferences.md"
    prefs.write_text("# p\n\n## Media folders\n\n-\n", encoding="utf-8")
    film = tmp_path / "Videos" / "Anatomy.of.a.Fall.2023.mkv"
    film.parent.mkdir()
    film.write_bytes(b"x")
    path = tmp_path / "remember.json"
    sources.main(["--result", str(path), "remember", "--file", str(film), "--prefs", str(prefs)])
    out = json.loads(path.read_text(encoding="utf-8"))
    assert out == {"added": str(film.parent.resolve()), "covered_by": None, "too_broad": None}
    assert sources.media_folders(prefs) == [out["added"]]


def test_compare_result_is_written_and_indented(tmp_path: Path):
    a = tmp_path / "a.srt"
    a.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi.\n", encoding="utf-8")
    path = tmp_path / "compare.json"
    srt.main(["--result", str(path), "compare", str(a), str(a)])
    text = path.read_text(encoding="utf-8")
    assert json.loads(text)["paired_share"] == 1.0
    assert text.startswith("{\n")


def test_a_usage_error_also_removes_the_old_result(tmp_path: Path):
    path = tmp_path / "assemble-deliver.json"
    path.write_text('{"delivered_to": "old"}', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        assemble.main(["--result", str(path), "deliver", "--work", str(tmp_path)])  # no --dest
    assert e.value.code == 2
    assert not path.exists()


def test_learn_done_result_says_marked(tmp_path: Path):
    srt_file = tmp_path / "film.tr.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nMerhaba.\n", encoding="utf-8")
    (tmp_path / "delivered.json").write_text(json.dumps({"delivered_to": str(srt_file)}), encoding="utf-8")
    path = tmp_path / "learn-done.json"
    learn.main(["--result", str(path), "done", "--work", str(tmp_path)])
    assert json.loads(path.read_text(encoding="utf-8")) == {"marked": "learned"}
