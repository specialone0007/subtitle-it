"""The bible check loop: questions, compare, the judge's cues, apply, and
the address-form warnings in the Turkish text."""

import json
from pathlib import Path

import pytest

import bible


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


CAST = [{"name": "Sam", "aliases": ["Sammy"]}, {"name": "Nora"}, {"name": "Harlan Pike"}]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Harlan Pike", "Uncle Harlan Pike"),
        ("Sam", "Sammy, on the phone; a few background lines in 25-26"),
        ("Nora", "Nora (also a background voice in 40-42, and Sam once)"),
        ("shop clerk", "Shop clerk (the tall one)"),
    ],
)
def test_voice_answers_agree_when_they_name_the_same_character(a, b):
    assert bible.agree("voice", a, b, CAST)
    assert bible.agree("voice", b, a, CAST)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Sam", "Nora (talking Sam into the trip)"),
        ("bus driver", "Mabel, the woman driving the bus"),
        ("the guard", "The guard captain"),
        ("Sam", "Samuel"),
        ("Sam", "Sam's mother"),
        ("Sam", "Sam’s mother"),
        ("Sam", "Leo (Sam's friend)"),
        ("Sam", "a clerk, Sam's cousin"),
    ],
)
def test_voice_answers_differ_when_they_name_someone_else(a, b):
    assert not bible.agree("voice", a, b, CAST)


def test_tolerant_matching_is_only_for_voices():
    assert not bible.agree("term", "koçum", "koçum (friendly)", CAST)


def test_compare_agrees_on_a_voice_described_two_ways(work):
    write_second(
        work,
        [
            ans("address:Sam>Nora", [{"from_cue": 1, "form": "siz"}]),
            ans("voice:V1", "SAM (on the phone)"),
            ans("term:sport", "koçum"),
        ],
    )
    assert bible.compare(work)["agreed"] == 3


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


def test_apply_does_not_count_a_reworded_voice_as_changed(work):
    write_second(
        work,
        [ans("address:Sam>Nora", [{"from_cue": 1, "form": "siz"}]), ans("voice:V1", "Nora"), ans("term:sport", "koçum")],
    )
    bible.compare(work)
    judged = [{"id": "voice:V1", "answer": "Sam on the phone", "evidence": [1, 5], "how": "evidence"}]
    (work / "judged.json").write_text(json.dumps({"decisions": judged}), encoding="utf-8")
    assert bible.apply(work)["changed"] == []


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


def test_address_readings_keep_the_cues_the_check_cannot_judge(work):
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    texts = {1: ["Nora, sen otur."], 2: ["Evet. Sen?"], 4: ["Koçum, sen de gel."], 5: ["Otur."]}
    got = {r["cue"]: r for r in bible.address_readings(work, texts, rows)}
    assert sorted(got) == [1, 2, 4]  # cue 5 has no form
    assert (got[1]["speaker"], got[1]["listener"], got[1]["expected"], got[1]["got"]) == ("Sam", "Nora", "siz", "sen")
    assert bible.address_off(got[1])
    assert got[2]["speaker"] is None and got[4]["expected"] is None
    assert not bible.address_off(got[2]) and not bible.address_off(got[4])


def test_address_warnings_need_decisions(tmp_path):
    assert bible.address_warnings(tmp_path, {1: ["Sen"]}, {}) == []


def test_questions_and_apply_accept_a_stored_tie(work):
    data = decisions()
    data["decisions"][2]["confidence"] = "tie"
    (work / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    assert bible.questions(work)["questions"] == 3


def test_readers_may_not_write_a_tie(work):
    write_second(work, [ans("address:Sam>Nora", [{"from_cue": 1, "form": "siz"}], confidence="tie")])
    with pytest.raises(SystemExit, match="confidence must be one of"):
        bible.compare(work)


def test_load_refuses_bad_characters(work):
    data = decisions()
    data["characters"][0]["aliases"] = None
    (work / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit, match="aliases is a list of strings"):
        bible.questions(work)


@pytest.mark.parametrize(
    "broken",
    [
        lambda d: d["characters"][0].update(aliases=None),
        lambda d: d["decisions"][0].pop("speaker"),
        lambda d: d["decisions"][0].update(answer=[{"from_cue": 1, "form": "siz"}, {"from_cue": "9", "form": "sen"}]),
    ],
)
def test_address_warnings_skip_a_broken_decisions_file(work, broken):
    data = decisions()
    broken(data)
    (work / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    rows = {r["n"]: r for r in json.loads((work / "cues.json").read_text(encoding="utf-8"))}
    assert bible.address_warnings(work, {1: ["Nora, sen otur."]}, rows) == []


def test_address_warnings_skip_invalid_json(work):
    (work / "decisions.json").write_text("{not json", encoding="utf-8")
    assert bible.address_warnings(work, {1: ["Nora, sen otur."]}, {}) == []


@pytest.mark.parametrize("text", ["[]", "null", "3"])
def test_address_warnings_skip_a_file_that_is_not_an_object(work, text):
    (work / "decisions.json").write_text(text, encoding="utf-8")
    assert bible.address_warnings(work, {1: ["Nora, sen otur."]}, {}) == []
    with pytest.raises(SystemExit, match="must hold a JSON object"):
        bible.questions(work)


def test_reader_files_must_be_objects(work):
    (work / "second.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="second.json must hold a JSON object"):
        bible.compare(work)
    write_second(work, [ans("voice:V1", "Sam")])
    bible.compare(work)
    (work / "judged.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="judged.json must hold a JSON object"):
        bible.apply(work)
    (work / "judged.json").write_text('{"decisions": 3}', encoding="utf-8")
    with pytest.raises(SystemExit, match="judged.json needs a decisions list"):
        bible.apply(work)


def test_a_new_compare_drops_old_verdicts(work):
    (work / "judged.json").write_text("{}", encoding="utf-8")
    write_second(
        work, [ans("address:Sam>Nora", [{"from_cue": 1, "form": "siz"}]), ans("voice:V1", "Sam"), ans("term:sport", "koçum")]
    )
    bible.compare(work)
    assert not (work / "judged.json").exists()
    assert bible.apply(work)["agreed"] == 3


def test_cli_writes_questions_and_the_result_file(work, tmp_path):
    out = tmp_path / "res" / "q.json"
    bible.main(["--result", str(out), "questions", "--work", str(work)])
    assert json.loads(out.read_text(encoding="utf-8"))["questions"] == 3


BIBLE_MD = "# Film (2024), original language: en\n## Characters\n- Sam: man, 50s\n## sen / siz\n- Sam → Nora: siz\n"


def write_voices(work: Path, decisions: list[dict], lines: list[str] | None = None) -> None:
    (work / "voices.json").write_text(json.dumps({"lines": lines or [], "decisions": decisions}), encoding="utf-8")


def voice(v: str, answer: str, confidence: str = "likely") -> dict:
    return {
        "id": f"voice:{v}",
        "kind": "voice",
        "question": f"Which character is voice {v}?",
        "answer": answer,
        "evidence": [1],
        "confidence": confidence,
    }


def test_voices_replace_the_voice_decisions_and_go_after_characters(work):
    (work / "bible.md").write_text(BIBLE_MD, encoding="utf-8")
    write_voices(work, [voice("V1", "Nora"), voice("V2", "Sam", "guess")], ["V1 = Nora (cues 1)", "- V2 = Sam (cues 5)"])
    out = bible.add_voices(work)
    assert out == {"voices": 2, "replaced": 1, "bible_lines": 2}
    data = json.loads((work / "decisions.json").read_text(encoding="utf-8"))
    assert [d["id"] for d in data["decisions"]] == ["address:Sam>Nora", "term:sport", "voice:V1", "voice:V2"]
    assert bible.questions(work)["by_kind"] == {"address": 1, "term": 1, "voice": 2}
    text = (work / "bible.md").read_text(encoding="utf-8")
    assert "## Characters\n- Sam: man, 50s\n## Voices\n- V1 = Nora (cues 1)\n- V2 = Sam (cues 5)\n## sen / siz" in text


def test_voices_run_twice_keeps_one_voices_section(work):
    (work / "bible.md").write_text(BIBLE_MD, encoding="utf-8")
    write_voices(work, [voice("V1", "Nora")], ["V1 = Nora"])
    bible.add_voices(work)
    write_voices(work, [voice("V1", "Sam")], ["V1 = Sam"])
    assert bible.add_voices(work)["replaced"] == 1
    text = (work / "bible.md").read_text(encoding="utf-8")
    assert text.count("## Voices") == 1 and "V1 = Sam" in text and "V1 = Nora" not in text


def test_voices_refuse_other_kinds_bad_ids_and_missing_answers(work):
    (work / "bible.md").write_text(BIBLE_MD, encoding="utf-8")
    term = {**voice("V1", "x"), "id": "term:sport", "kind": "term"}
    listed = {**voice("V4", "Sam"), "id": ["voice:V4"]}
    write_voices(work, [term, {**voice("V2", "Sam"), "id": "voice:Sam"}, {**voice("V3", "Sam"), "answer": None}, listed])
    with pytest.raises(SystemExit) as e:
        bible.add_voices(work)
    msg = str(e.value)
    assert "term:sport: only voice decisions" in msg
    assert "voice:Sam: only voice decisions" in msg
    assert "voice:V3: every voice question needs an answer" in msg
    assert "each entry needs a string id" in msg
    assert json.loads((work / "decisions.json").read_text(encoding="utf-8")) == decisions()
    assert (work / "bible.md").read_text(encoding="utf-8") == BIBLE_MD


def test_voices_refuse_lines_that_are_not_a_list(work):
    (work / "bible.md").write_text(BIBLE_MD, encoding="utf-8")
    (work / "voices.json").write_text(json.dumps({"lines": "V1 = Nora", "decisions": [voice("V1", "Nora")]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="lines is a list of strings"):
        bible.add_voices(work)
    assert json.loads((work / "decisions.json").read_text(encoding="utf-8")) == decisions()
    assert (work / "bible.md").read_text(encoding="utf-8") == BIBLE_MD


def test_voices_go_at_the_end_without_a_characters_section(work):
    (work / "bible.md").write_text("# Film (2024)\n## sen / siz\n- Sam → Nora: siz\n", encoding="utf-8")
    write_voices(work, [voice("V1", "Nora")], ["V1 = Nora"])
    bible.add_voices(work)
    text = (work / "bible.md").read_text(encoding="utf-8")
    assert text.endswith("- Sam → Nora: siz\n## Voices\n- V1 = Nora\n")


def test_voices_need_the_bible(work):
    write_voices(work, [voice("V1", "Nora")])
    with pytest.raises(SystemExit, match="bible.md is missing"):
        bible.add_voices(work)
    assert json.loads((work / "decisions.json").read_text(encoding="utf-8")) == decisions()
