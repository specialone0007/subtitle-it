"""The bible check loop: questions, compare, the judge's cues, apply, and
the address-form warnings in the Turkish text."""

import json
from pathlib import Path

import pytest

import bible
import srt


def cue_row(n: int, en: str) -> dict:
    s = (n - 1) * 3
    ts = f"00:00:{s:02d},000 --> 00:00:{s + 2:02d},000"
    return {"n": n, "ts": ts, "start": s * 1000, "end": (s + 2) * 1000, "timing_lines": [en], "source": [en], "en": None}


LINES = ["Nora, sit down.", "Yes, sir.", "Are you OK?", "Sport, come here.", "Nora, you're fired."]


def decisions() -> dict:
    return {
        "characters": [{"name": "Sam", "aliases": ["SAM"]}, {"name": "Nora", "aliases": ["NORA"]}],
        "decisions": [
            {
                "id": "address:Sam>Nora",
                "kind": "address",
                "speaker": "Sam",
                "listener": "Nora",
                "question": "Does Sam say sen or siz to Nora?",
                "answer": [{"from_cue": 1, "form": "siz"}],
                "evidence": [1, 5],
                "confidence": "sure",
            },
            {
                "id": "voice:V1",
                "kind": "voice",
                "question": "Who is V1?",
                "answer": "Sam",
                "evidence": [1],
                "confidence": "likely",
            },
            {
                "id": "term:sport",
                "kind": "term",
                "question": "Turkish for 'sport'?",
                "answer": "koçum",
                "evidence": [4],
                "confidence": "guess",
            },
        ],
    }


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "cues.json").write_text(json.dumps([cue_row(i, t) for i, t in enumerate(LINES, 1)]), encoding="utf-8")
    speakers = {"1": {"voice": "V1"}, "3": {"label": "Sam"}, "5": {"label": "Sam", "voice": "V1"}, "2": {"label": "Nora / Sam"}}
    (tmp_path / "speakers.json").write_text(json.dumps(speakers), encoding="utf-8")
    (tmp_path / "decisions.json").write_text(json.dumps(decisions()), encoding="utf-8")
    return tmp_path


def write_second(work: Path, answers: list[dict], extra: list[dict] | None = None) -> None:
    (work / "second.json").write_text(json.dumps({"answers": answers, "extra": extra or []}), encoding="utf-8")


def ans(id: str, answer, evidence=(1,), confidence="sure") -> dict:
    return {"id": id, "answer": answer, "evidence": list(evidence), "confidence": confidence}


def test_questions_leave_out_the_answers(work):
    out = bible.questions(work)
    qs = json.loads((work / "questions.json").read_text(encoding="utf-8"))
    assert out["questions"] == 3 and out["by_kind"] == {"address": 1, "voice": 1, "term": 1}
    assert all("answer" not in q and "evidence" not in q and "confidence" not in q for q in qs)
    assert qs[0]["speaker"] == "Sam" and qs[0]["listener"] == "Nora"


def test_questions_refuse_a_broken_decision(work):
    data = decisions()
    data["decisions"][0]["answer"] = [{"from_cue": 1, "form": "you"}]
    (work / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit, match="sen or siz"):
        bible.questions(work)


def test_compare_agrees_on_same_answers_and_case(work):
    write_second(
        work,
        [ans("address:Sam>Nora", [{"from_cue": 1, "form": "siz"}]), ans("voice:V1", "sam"), ans("term:sport", "'Koçum'")],
    )
    out = bible.compare(work)
    assert out["agreed"] == 3 and out["to_judge"] == 0


def test_compare_sends_disagreements_missing_answers_and_extras_to_the_judge(work):
    write_second(
        work,
        [ans("address:Sam>Nora", [{"from_cue": 1, "form": "sen"}]), ans("voice:V1", None)],
        [{"id": "name:judge", "kind": "name", "question": "How is the judge addressed?", **ans("name:judge", "Hâkim Bey")}],
    )
    out = bible.compare(work)
    assert out["judge_ids"] == ["address:Sam>Nora", "voice:V1", "term:sport", "name:judge"]
    cmp = json.loads((work / "compare.json").read_text(encoding="utf-8"))
    why = {t["id"]: t["why"] for t in cmp["to_judge"]}
    assert why["address:Sam>Nora"] == "the readers disagree"
    assert why["voice:V1"] == "the second reader gave no answer"
    assert why["name:judge"] == "only the second reader asked this"
    assert cmp["to_judge"][0]["writer"]["answer"] == [{"from_cue": 1, "form": "siz"}]


def test_compare_refuses_an_extra_that_reuses_a_question_id(work):
    write_second(work, [], [{"id": "voice:V1", "kind": "voice", "question": "Who is V1?", **ans("voice:V1", "Nora")}])
    with pytest.raises(SystemExit, match="already a question"):
        bible.compare(work)


def test_address_switch_points_close_together_agree():
    a = [{"from_cue": 1, "form": "siz"}, {"from_cue": 400, "form": "sen"}]
    near = [{"from_cue": 1, "form": "siz"}, {"from_cue": 400 + bible.ADDRESS_TOLERANCE, "form": "sen"}]
    far = [{"from_cue": 1, "form": "siz"}, {"from_cue": 401 + bible.ADDRESS_TOLERANCE, "form": "sen"}]
    assert bible.agree("address", a, near)
    assert not bible.agree("address", a, far)
    assert not bible.agree("address", [{"from_cue": 1, "form": "siz"}], [{"from_cue": 1, "form": "sen"}])
    # A repeated form is no switch, and the first step covers the film's start.
    assert bible.agree(
        "address", [{"from_cue": 30, "form": "siz"}, {"from_cue": 90, "form": "siz"}], [{"from_cue": 1, "form": "siz"}]
    )


def test_form_at_uses_the_first_step_before_it_starts():
    steps = [{"from_cue": 10, "form": "siz"}, {"from_cue": 50, "form": "sen"}]
    assert [bible.form_at(steps, n) for n in (1, 10, 49, 50, 900)] == ["siz", "siz", "siz", "sen", "sen"]


def test_cues_show_context_speaker_and_time(work):
    out = bible.cues(work, [1, 5], context=1)
    assert [r["n"] for r in out] == [1, 2, 4, 5]
    assert out[0] == {"n": 1, "at": "00:00:00", "speaker": "V1", "src": "Nora, sit down."}
    assert out[-1]["speaker"] == "Sam · V1"


def test_apply_records_changes_additions_and_ties(work):
    write_second(
        work,
        [ans("address:Sam>Nora", [{"from_cue": 1, "form": "sen"}]), ans("voice:V1", "Sam"), ans("term:sport", "koçum")],
        [{"id": "name:judge", "kind": "name", "question": "How is the judge addressed?", **ans("name:judge", "Hâkim Bey")}],
    )
    bible.compare(work)
    judged = [
        {"id": "address:Sam>Nora", "answer": [{"from_cue": 1, "form": "sen"}], "evidence": [3], "how": "evidence"},
        {"id": "name:judge", "answer": "Hâkim Bey", "evidence": [4, 5], "how": "safe default"},
    ]
    (work / "judged.json").write_text(json.dumps({"decisions": judged}), encoding="utf-8")
    out = bible.apply(work)
    assert out["changed"] == ["address:Sam>Nora"] and out["added"] == ["name:judge"]
    assert out["ties"] == [
        {
            "id": "name:judge",
            "question": "How is the judge addressed?",
            "answer": "Hâkim Bey",
            "cues": [{"n": 4, "at": "00:00:09"}, {"n": 5, "at": "00:00:12"}],
        }
    ]
    final = {d["id"]: d for d in json.loads((work / "decisions.json").read_text(encoding="utf-8"))["decisions"]}
    assert final["address:Sam>Nora"]["confidence"] == "sure" and final["name:judge"]["confidence"] == "tie"
    writer = json.loads((work / "decisions.writer.json").read_text(encoding="utf-8"))
    assert writer["decisions"][0]["answer"] == [{"from_cue": 1, "form": "siz"}]


def test_apply_refuses_when_the_judge_skipped_a_question(work):
    write_second(
        work, [ans("address:Sam>Nora", [{"from_cue": 1, "form": "sen"}]), ans("voice:V1", "Sam"), ans("term:sport", "koçum")]
    )
    bible.compare(work)
    (work / "judged.json").write_text(json.dumps({"decisions": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="no answer for: address:Sam>Nora"):
        bible.apply(work)


def test_apply_with_nothing_to_judge_needs_no_judged_file(work):
    write_second(
        work, [ans("address:Sam>Nora", [{"from_cue": 1, "form": "siz"}]), ans("voice:V1", "Sam"), ans("term:sport", "koçum")]
    )
    bible.compare(work)
    assert bible.apply(work) == {"agreed": 3, "judged": 0, "changed": [], "added": [], "ties": []}


@pytest.mark.parametrize(
    "text, form",
    [
        ("Oturun lütfen, sizi bekliyorduk.", "siz"),
        ("İyi misiniz?", "siz"),
        ("İyi misin?", "sen"),
        ("Sana söylüyorum.", "sen"),
        ("Ne yapıyorsun?", "sen"),
        ("Ne yapıyorsunuz?", "siz"),
        ("Kadın geldi.", None),
        ("Sen ve siz.", None),
        ("SENİ GÖRDÜM.", "sen"),
    ],
)
def test_detect_form(text, form):
    assert bible.detect_form(text) == form


def test_address_warnings_use_the_named_listener_and_skip_plural_siz(work):
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts = {
        1: ["Nora, otur."],  # V1 is Sam, Nora named, Sam → Nora is siz: flagged
        2: ["Evet, efendim. Sen?"],  # two speakers: skipped
        3: ["İyi misiniz?"],  # Sam, nobody named, siz may be plural: not flagged
        4: ["Koçum, gel buraya. Sen de."],  # no speaker hint: skipped
        5: ["Nora, kovuldunuz. Sizi uyarmıştım."],  # matches the bible
    }
    warns = bible.address_warnings(work, texts, rows)
    assert warns == []  # cue 1 has no detectable form ("otur" is an imperative)
    texts[1] = ["Nora, sen otur."]
    texts[3] = ["İyi misin?"]
    warns = bible.address_warnings(work, texts, rows)
    assert [(w["cue"], w["detail"]) for w in warns] == [
        (1, "Sam → Nora: bible says siz, Turkish uses sen"),
        (3, "Sam → anyone here: bible says siz, Turkish uses sen"),
    ]


def test_address_warnings_need_decisions(tmp_path):
    assert bible.address_warnings(tmp_path, {1: ["Sen"]}, {}) == []


def test_shift_moves_cues_and_stops_at_zero():
    cues = srt.parse_text("1\n00:00:00,200 --> 00:00:01,000\nHi\n\n2\n00:00:05,000 --> 00:00:06,500\nBye\n")
    out = srt.shift(cues, -500)
    assert [c.ts for c in out] == ["00:00:00,000 --> 00:00:00,500", "00:00:04,500 --> 00:00:06,000"]
    assert [c.lines for c in out] == [["Hi"], ["Bye"]]
    assert cues[0].start == 200  # the input is left as it was
