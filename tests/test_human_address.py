"""The human Turkish file as the evidence for sen and siz in a polish run:
the bible judge sees its counts per pair, and `check` lists every line
whose form a fix changed, warning when no reason was given."""

import json
import os
from pathlib import Path

import assemble
import bible
import polish
import prepare
import srt

EN = ["Nora, sit down.", "Nora, listen.", "Nora, I told you.", "Nora, are you ready?", "Thanks, Nora."]
TR = ["Nora, sen otur.", "Nora, seni dinle.", "Nora, sana söyledim.", "Nora, hazır mısın?", "Sağ ol Nora."]


def _srt(lines: list[str]) -> str:
    return "".join(f"{i}\n00:00:{i * 3:02d},000 --> 00:00:{i * 3 + 2:02d},000\n{t}\n\n" for i, t in enumerate(lines, 1))


def _decisions(form: str) -> dict:
    return {
        "characters": [{"name": "Sam", "aliases": []}, {"name": "Nora", "aliases": []}],
        "decisions": [
            {
                "id": "address:Sam>Nora",
                "kind": "address",
                "speaker": "Sam",
                "listener": "Nora",
                "question": "Does Sam say sen or siz to Nora?",
                "answer": [{"from_cue": 1, "form": form}],
                "evidence": [1],
                "confidence": "guess",
            }
        ],
    }


def polish_work(tmp_path: Path, form: str = "siz") -> Path:
    (tmp_path / "en.srt").write_text(_srt(EN), encoding="utf-8")
    (tmp_path / "tr.srt").write_text(_srt(TR), encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, tmp_path / "en.srt", None, tmp_path / "en.srt")
    (w / "decisions.json").write_text(json.dumps(_decisions(form)), encoding="utf-8")
    (w / "speakers.json").write_text(json.dumps({str(n): {"label": "Sam"} for n in range(1, 6)}), encoding="utf-8")
    polish.seed(w, tmp_path / "tr.srt")
    return w


def test_reason_lines_are_no_turkish_and_are_read_apart(tmp_path: Path):
    f = tmp_path / "fix.txt"
    f.write_text("3\nNora, size söyledim.\n#address: the English says sir\n\n4\nHazır mısınız?\n", encoding="utf-8")
    blocks, problems = srt.read_blocks(f)
    assert problems == [] and blocks == {3: ["Nora, size söyledim."], 4: ["Hazır mısınız?"]}
    assert srt.read_reasons(f) == {3: "the English says sir"}


def test_human_forms_count_each_pair_the_bible_asks_about(tmp_path: Path):
    w = polish_work(tmp_path)
    forms = bible.human_forms(w)
    # Cue 5 uses no form; the other four name Nora and use sen.
    assert forms == {("Sam", "Nora"): {"sen": [1, 2, 3, 4], "siz": []}}


def test_human_forms_are_empty_in_a_full_run(tmp_path: Path):
    w = polish_work(tmp_path)
    (w / "out" / "tr_00.txt").unlink()
    assert bible.human_forms(w) == {}


def test_compare_sends_an_agreed_form_the_human_file_contradicts_to_the_judge(tmp_path: Path):
    w = polish_work(tmp_path, form="siz")
    answer = {"id": "address:Sam>Nora", "answer": [{"from_cue": 1, "form": "siz"}], "evidence": [1], "confidence": "guess"}
    (w / "second.json").write_text(json.dumps({"answers": [answer], "extra": []}), encoding="utf-8")
    out = bible.compare(w)
    assert out["agreed"] == 0 and out["judge_ids"] == ["address:Sam>Nora"]
    item = json.loads((w / "compare.json").read_text(encoding="utf-8"))["to_judge"][0]
    assert item["why"] == "the human Turkish file uses another form than both readers give on 4 of its 4 lines"
    assert item["human_file"] == {"sen": {"lines": 4, "cues": [1, 2, 3, 4]}, "siz": {"lines": 0, "cues": []}}


def test_compare_keeps_an_agreed_form_the_human_file_shares(tmp_path: Path):
    w = polish_work(tmp_path, form="sen")
    answer = {"id": "address:Sam>Nora", "answer": [{"from_cue": 1, "form": "sen"}], "evidence": [1], "confidence": "sure"}
    (w / "second.json").write_text(json.dumps({"answers": [answer], "extra": []}), encoding="utf-8")
    assert bible.compare(w)["agreed"] == 1


def test_polish_flags_and_review_notes_leave_the_human_form_alone(tmp_path: Path):
    w = polish_work(tmp_path, form="siz")
    assert any(x["check"] == "address form" for x in assemble.run_checks(w)["warnings"])
    assert not any(k.startswith("address form") for k in polish.flags(w)["by_check"])
    part = Path(assemble.review_parts(w)["parts"][0]["file"]).read_text(encoding="utf-8")
    assert "address form" not in part


def test_check_lists_address_changes_and_warns_without_a_reason(tmp_path: Path):
    w = polish_work(tmp_path)
    (w / "out" / "fix_review_01.txt").write_text(
        "1\nNora, siz oturun.\n#address: the English says ma'am\n\n2\nNora, sizi dinleyin.\n\n5\nTeşekkürler Nora.\n",
        encoding="utf-8",
    )
    checks = assemble.run_checks(w)
    assert checks["address_changes"] == [
        {"cue": 1, "human": "sen", "now": "siz", "file": "fix_review_01.txt", "reason": "the English says ma'am"},
        {"cue": 2, "human": "sen", "now": "siz", "file": "fix_review_01.txt", "reason": None},
    ]
    changed = [x for x in checks["warnings"] if x["check"] == "address changed"]
    assert [x["cue"] for x in changed] == [2]
    assert changed[0]["detail"] == "the human file says sen, now siz, no reason given (fix_review_01.txt)"
    # The reason line is not delivered.
    assert "#address" not in (w / "draft.tr.srt").read_text(encoding="utf-8-sig")


def test_a_full_run_lists_no_address_changes(tmp_path: Path):
    w = polish_work(tmp_path)
    (w / polish.PLACEMENT_FILE).unlink()
    (w / "out" / "fix_review_01.txt").write_text("2\nNora, sizi dinleyin.\n", encoding="utf-8")
    checks = assemble.run_checks(w)
    assert checks["address_changes"] == []
    assert not any(x["check"] == "address changed" for x in checks["warnings"])


def test_the_judges_cues_show_the_human_line(tmp_path: Path):
    w = polish_work(tmp_path)
    rows = bible.cues(w, [2], 0)
    assert rows[0]["human_tr"] == "Nora, seni dinle."


def test_compare_weighs_a_switch_against_the_human_lines(tmp_path: Path):
    # Both readers put a switch from siz to sen at cue 4; the human file
    # uses sen from cue 1, so three of its lines go against them.
    w = polish_work(tmp_path)
    steps = [{"from_cue": 1, "form": "siz"}, {"from_cue": 4, "form": "sen"}]
    data = json.loads((w / "decisions.json").read_text(encoding="utf-8"))
    data["decisions"][0]["answer"] = steps
    (w / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    answer = {"id": "address:Sam>Nora", "answer": steps, "evidence": [1], "confidence": "likely"}
    (w / "second.json").write_text(json.dumps({"answers": [answer], "extra": []}), encoding="utf-8")
    assert bible.compare(w)["judge_ids"] == ["address:Sam>Nora"]
    assert bible.human_against({"sen": [1, 2, 3, 4], "siz": []}, steps) == [1, 2, 3]


def test_a_later_fix_file_without_a_reason_keeps_the_reviewers_reason(tmp_path: Path):
    # The soft pass writes after the review and keeps the reviewer's siz on
    # cue 1 without a reason line: the reviewer's reason must still count.
    w = polish_work(tmp_path)
    out = w / "out"
    (out / "fix_review_01.txt").write_text("1\nNora, siz oturun.\n#address: the English says ma'am\n", encoding="utf-8")
    (out / "fix_soft.txt").write_text("1\nNora, siz oturun lütfen.\n", encoding="utf-8")
    # Fix files apply in the order they were written.
    review = (out / "fix_review_01.txt").stat().st_mtime
    os.utime(out / "fix_soft.txt", (review + 10, review + 10))
    checks = assemble.run_checks(w)
    assert checks["address_changes"] == [
        {"cue": 1, "human": "sen", "now": "siz", "file": "fix_soft.txt", "reason": "the English says ma'am"},
    ]
    assert not any(x["check"] == "address changed" for x in checks["warnings"])
