"""The blind comparison of delivered subtitles: shuffled rows and a key,
then verdicts turned back into per-version numbers. Synthetic text only."""

import json
from pathlib import Path

import pytest

import compare
import srt

EN = "".join(f"{i}\n00:00:{i * 3:02d},000 --> 00:00:{i * 3 + 2:02d},000\nLine {i}.\n\n" for i in range(1, 5))


def tr(words: list[str]) -> str:
    return "".join(f"{i}\n00:00:{i * 3:02d},100 --> 00:00:{i * 3 + 2:02d},000\n{w}\n\n" for i, w in enumerate(words, 1))


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    out = {"en": tmp_path / "en.srt", "old": tmp_path / "old.srt", "new": tmp_path / "new.srt"}
    out["en"].write_text(EN, encoding="utf-8")
    out["old"].write_text(tr(["Bir.", "<i>İki.</i>", "Üç.", "Dört."]), encoding="utf-8")
    out["new"].write_text(tr(["Bir.", "İkinci.", "Üç.", "Dördüncü."]), encoding="utf-8")
    return out


def test_rows_keep_only_differences_and_hide_the_versions(files, tmp_path: Path):
    out = tmp_path / "blind"
    compare.main(["rows", "--timing", str(files["en"]), "--version", f"old={files['old']}",
                  "--version", f"new={files['new']}", "--out", str(out), "--seed", "3"])  # fmt: skip
    lines = (out / "rows.tsv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "id\ttime\tenglish\tA\tB"
    assert [ln.split("\t")[2] for ln in lines[1:]] == ["Line 2.", "Line 4."]
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    assert key["versions"] == ["old", "new"] and key["rows"]["1"]["cue"] == 2
    row = lines[1].split("\t")
    letters = key["rows"]["1"]["letters"]
    assert {letters["A"]: row[3], letters["B"]: row[4]} == {"old": "İki.", "new": "İkinci."}  # tags gone


def test_rows_with_all_and_parts(files, tmp_path: Path):
    timing, _ = srt.parse(files["en"])
    versions = {k: srt.parse(files[k])[0] for k in ("old", "new")}
    rows = compare.build_rows(timing, versions, keep_same=True)
    assert len(rows) == 4
    got = compare.write_rows(rows, ["old", "new"], tmp_path / "blind", seed=1, parts=2)
    assert got["rows"] == 4 and [Path(f).name for f in got["files"]] == ["rows_1.tsv", "rows_2.tsv"]


def test_parts_never_leave_a_file_empty(tmp_path: Path):
    rows = [
        {"cue": n, "time": "00:00:01,000", "english": f"Line {n}.", "texts": {"old": "a", "new": f"b{n}"}} for n in range(1, 6)
    ]
    got = compare.write_rows(rows, ["old", "new"], tmp_path / "blind", seed=1, parts=4)
    sizes = [len(Path(f).read_text(encoding="utf-8").splitlines()) - 1 for f in got["files"]]
    assert sizes == [2, 1, 1, 1]


def test_the_same_seed_gives_the_same_letters(files, tmp_path: Path):
    timing, _ = srt.parse(files["en"])
    versions = {k: srt.parse(files[k])[0] for k in ("old", "new")}
    rows = compare.build_rows(timing, versions, keep_same=True)
    keys = []
    for name in ("a", "b"):
        compare.write_rows(rows, ["old", "new"], tmp_path / name, seed=9)
        keys.append(json.loads((tmp_path / name / "key.json").read_text(encoding="utf-8"))["rows"])
    assert keys[0] == keys[1]


def test_rows_refuse_a_folder_inside_the_repository(files):
    with pytest.raises(SystemExit, match="inside the repository"):
        compare.write_rows([], ["old", "new"], compare.REPO / "blind-test", seed=1)
    assert not (compare.REPO / "blind-test").exists()


def test_rows_need_two_or_three_versions(files, tmp_path: Path):
    with pytest.raises(SystemExit, match="two or three"):
        compare.main(["rows", "--timing", str(files["en"]), "--version", f"old={files['old']}", "--out", str(tmp_path / "x")])


KEY = {
    "versions": ["v1", "v2", "v3"],
    "seed": 1,
    "rows": {
        "1": {"cue": 10, "letters": {"A": "v1", "B": "v2", "C": "v3"}},
        "2": {"cue": 11, "letters": {"A": "v3", "B": "v1", "C": "v2"}},
        "3": {"cue": 12, "letters": {"A": "v2", "B": "v3", "C": "v1"}},
    },
}


def test_unblind_counts_places_problems_and_head_to_head():
    verdicts = [
        {"id": 1, "rank": ["C", "A=B"], "problems": {"A": "meaning", "B": "none", "C": "none"}, "why": "."},
        {"id": 2, "rank": ["A", "B", "C"], "problems": {"A": "none", "B": "unnatural", "C": "meaning"}, "why": "."},
        {"id": 3, "rank": ["A=B=C"], "problems": {}, "why": "."},
        {"id": 99, "rank": ["A"], "why": "unknown row"},
        {"id": 3, "rank": ["A", "B"], "why": "a letter missing"},
    ]
    out = compare.unblind(KEY, verdicts)
    assert out["unknown_ids"] == [99] and out["incomplete_ranks"] == [3] and out["rows_judged"] == 3
    v1, v2, v3 = (out["versions"][k] for k in ("v1", "v2", "v3"))
    # Row 1: v3 best, v1 and v2 tied last. Row 2: v3, v1, v2. Row 3: all tied.
    assert (v3["best_alone"], v3["worst"], v3["average_rank"]) == (2, 0, 0.0)
    assert (v1["best_alone"], v1["worst"], v1["average_rank"]) == (0, 1, 0.667)
    assert (v2["worst"], v2["average_rank"]) == (2, 1.0)
    assert v1["problems"] == {"meaning": 1, "unnatural": 1} and v2["problems"] == {"meaning": 1} and v3["problems"] == {}
    h2h = {(h["a"], h["b"]): (h["a_wins"], h["b_wins"], h["ties"]) for h in out["head_to_head"]}
    assert h2h == {("v1", "v2"): (1, 0, 2), ("v1", "v3"): (0, 2, 1), ("v2", "v3"): (0, 2, 1)}


def test_unblind_from_the_command_line(tmp_path: Path, capsys):
    (tmp_path / "key.json").write_text(json.dumps(KEY), encoding="utf-8")
    (tmp_path / "v.json").write_text(json.dumps([{"id": 1, "rank": ["A", "B", "C"], "problems": {}}]), encoding="utf-8")
    compare.main(["unblind", "--key", str(tmp_path / "key.json"), "--verdicts", str(tmp_path / "v.json")])
    assert json.loads(capsys.readouterr().out)["versions"]["v1"]["best_alone"] == 1
