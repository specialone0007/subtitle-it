"""Checks that keep a film consistent and its sentences whole: split
sentences, one rendering per term, name suffixes, TDK spellings, and the
address check's speaker in two-person scenes."""

import json
from pathlib import Path

import pytest

import assemble
import bible
import prepare
import srt
import turkish

# --- spelling slips --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "slips"),
    [
        ("Herşeyi biliyorum.", [("Herşeyi", "Her şeyi")]),
        ("Sağol, dostum.", [("Sağol", "Sağ ol")]),
        ("Hiçbirşey yok.", [("Hiçbirşey", "Hiçbir şey")]),
        ("Yine de geldim, yinede gelirim.", [("yinede", "yine de")]),
        ("Bir çok insan geldi.", [("Bir çok", "Birçok")]),
        ("Hiç bir şey demedi.", [("Hiç bir", "Hiçbir")]),
        ("Yanlız kaldım.", [("Yanlız", "Yalnız")]),
        ("<i>Şuanda buradayım.</i>", [("Şuanda", "Şu anda")]),
        ("Her şey yolunda, sağ ol.", []),
        ("Birçok kez, hiçbir zaman.", []),
        ("Bir, çok uzak.", []),
    ],
)
def test_spelling_slips(text, slips):
    assert turkish.spelling_slips(text) == slips


# --- name suffixes ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "slips"),
    [
        ("Joey'in güvercinleri.", [("Joey'in", "Joey'nin")]),
        ("Joey'e söyle.", [("Joey'e", "Joey'ye")]),
        ("Charley'in arabası.", [("Charley'in", "Charley'nin")]),
        ("John'nun evi.", [("John'nun", "John'un")]),
        ("Ray'yi gördüm.", [("Ray'yi", "Ray'i")]),
        ("Joey'nin güvercinleri, Joey'ye söyle.", []),
        ("Ray'in evi, John'un arabası.", []),
        ("Edie'nin abisi.", []),
        ("Mike'ın arabası.", []),  # a final "e" may be silent: left alone
        ("FBI'ın adamı, D'yi bul.", []),  # letters and acronyms
        ("Joey'ninki burada.", []),
        ("Ahmet Bey'in evi, Terry Bey'e söyle.", []),  # the title "Bey" ends in a consonant
    ],
)
def test_name_suffix_slips(text, slips):
    assert turkish.name_suffix_slips(text) == slips


def test_ends_in_vowel_sound():
    assert turkish.ends_in_vowel_sound("Joey") and turkish.ends_in_vowel_sound("Edie")
    assert turkish.ends_in_vowel_sound("Ayla")
    assert turkish.ends_in_vowel_sound("Ray") is False and turkish.ends_in_vowel_sound("John") is False
    assert turkish.ends_in_vowel_sound("Mike") is None and turkish.ends_in_vowel_sound("Hugh") is None


# --- one rendering per term ------------------------------------------------


def test_family_drift_flags_the_less_used_form():
    texts = {1: ["Abim geldi."], 2: ["Abi, dur!"], 3: ["Ağabeyin nerede?"], 4: ["Celbi aldım."], 5: ["Celpnameyi getir."]}
    got = turkish.family_drift(texts)
    # abi wins on count; celp and celpname tie, and the first listed wins.
    assert got == [(3, "ağabey", "abi", 2), (5, "celpname", "celp", 1)]


def test_family_drift_follows_the_bible_over_the_count():
    texts = {1: ["Abim geldi."], 2: ["Abi, dur!"], 3: ["Ağabeyin nerede?"]}
    assert turkish.family_drift(texts, bible_text="ağabey") == [(1, "abi", "ağabey", 1), (2, "abi", "ağabey", 1)]


def test_family_drift_is_quiet_with_one_form():
    assert turkish.family_drift({1: ["Abim geldi."], 2: ["Abiler burada."]}) == []


@pytest.mark.parametrize(
    ("text", "answer", "found"),
    [
        ("Celbi aldın mı?", "celp", True),
        ("Kanarya gibi öttü.", "ötmek", True),
        ("İşçi seçimine gel.", "işçi seçimi", True),
        ("Celpname geldi.", "celp", True),
        ("Kâğıdı aldın mı?", "celp", False),
        ("Her şey yolunda.", "S ve D", True),  # no word to look for
    ],
)
def test_has_rendering(text, answer, found):
    assert turkish.has_rendering(text, answer) is found


def term_decisions(*decisions: dict) -> dict:
    return {"characters": [{"name": "Terry", "aliases": ["TERRY"]}], "decisions": list(decisions)}


def term(id: str, question: str, answer: str, kind: str = "term") -> dict:
    return {"id": id, "kind": kind, "question": question, "answer": answer, "evidence": [1], "confidence": "sure"}


def test_term_renderings_read_quoted_terms_and_skip_scene_answers(tmp_path: Path):
    data = term_decisions(
        term("term:subpoena", 'Turkish for "subpoena"?', "celp"),
        term("term:canary", 'Turkish for "canary" / "sing"?', "kanarya / ötmek"),
        term("term:loft", 'Turkish for "loft"?', "kümes for the birds; çatı for the room"),
        term("term:shape-up", 'Turkish for "shape-up"?', "işçi seçimi (sabah)"),
        term("name:father", 'How is "Father" said?', "Peder", kind="name"),
    )
    (tmp_path / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    assert bible.term_renderings(tmp_path) == {
        "subpoena": {"celp"},
        "canary": {"kanarya"},
        "sing": {"ötmek"},
        "shape-up": {"işçi seçimi"},
    }


# --- a work folder for run_checks ------------------------------------------


def make_work(tmp_path: Path, english: list[str], turkish_lines: list[str]) -> Path:
    blocks = []
    for i, en in enumerate(english, 1):
        s = (i - 1) * 3
        blocks.append(f"{i}\n00:00:{s:02d},000 --> 00:00:{s + 2:02d},500\n{en}\n")
    src = tmp_path / "film.en.srt"
    src.write_text("\n".join(blocks), encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, src, None, None)
    (w / "out").mkdir(exist_ok=True)
    tr = "".join(f"{i}\n{t}\n\n" for i, t in enumerate(turkish_lines, 1))
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    return w


def warned(w: Path, kind: str) -> dict[int, str]:
    return {x["cue"]: x["detail"] for x in assemble.run_checks(w)["warnings"] if x["check"] == kind}


def test_check_warns_on_spelling_and_name_suffix(tmp_path: Path):
    w = make_work(tmp_path, ["Thanks, I know everything.", "Joey's birds."], ["Sağol, herşeyi biliyorum.", "Joey'in kuşları."])
    assert sorted(warned(w, "spelling")) == [1] and "her şeyi" in warned(w, "spelling")[1]
    assert warned(w, "name suffix") == {2: '"Joey\'in": the name ends in another sound when said; write "Joey\'nin"'}


def test_check_warns_when_a_term_lacks_the_bible_rendering_and_on_drift(tmp_path: Path):
    english = ["You got a subpoena.", "Subpoenas again?", "My brother is here.", "Where's your brother?", "Brother, wait."]
    tr = ["Sana celp geldi.", "Yine mi kâğıt?", "Abim burada.", "Ağabeyin nerede?", "Abi, bekle."]
    w = make_work(tmp_path, english, tr)
    data = term_decisions(term("term:subpoena", 'Turkish for "subpoena"?', "celp"))
    (w / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    assert sorted(warned(w, "term rendering")) == [2]
    assert warned(w, "term drift") == {4: "'ağabey' here, 'abi' in 2 other cues: use one form for the whole film"}


# --- split sentences -------------------------------------------------------


def test_sentence_groups_follow_the_punctuation(tmp_path: Path):
    english = ["I went down to the docks", "and I saw him there.", "Hello.", "If you go", "to the roof", "♪ la la", "Fine.",
               "- Wait... / - What?", "Nothing."]  # fmt: skip
    w = make_work(tmp_path, english, ["x"] * len(english))
    timing, _ = srt.parse(w / "timing.srt")
    rows = {r["n"]: r for r in json.loads((w / "cues.json").read_text(encoding="utf-8"))}
    rows[8]["en"] = ["- Wait...", "- What?"]
    # A run cut off by a song (cues 4-5) is no sentence to check; a
    # two-speaker cue whose first turn trails off runs on (cues 8-9).
    assert assemble.sentence_groups(timing, rows) == [[1, 2], [8, 9]]


def test_split_sentence_flags_a_part_written_twice(tmp_path: Path):
    english = ["When the hearing starts tomorrow", "you will tell them everything."]
    tr = ["Yarın duruşma başlayınca her şeyi anlatacaksın.", "Duruşma başlayınca her şeyi anlatacaksın."]
    w = make_work(tmp_path, english, tr)
    got = warned(w, "split sentence")
    assert sorted(got) == [1, 2]
    assert '"duruşma başlayınca" is in cue 1 and cue 2' in got[1]
    assert got[1].endswith("so each part appears exactly once")


def test_split_sentence_flags_an_empty_part_and_a_moved_name(tmp_path: Path):
    english = ["I told the whole story to everyone at the bar", "and then Terry", "walked out."]
    tr = ["Barda herkese bütün hikâyeyi Terry anlattım", "<i></i>-", "sonra da çıkıp gitti."]
    w = make_work(tmp_path, english, tr)
    problems = assemble.split_sentence_problems(
        [1, 2, 3],
        {1: [tr[0]], 2: ["-"], 3: [tr[2]]},
        {r["n"]: r for r in json.loads((w / "cues.json").read_text(encoding="utf-8"))},
    )
    assert "cue 2 has no words for its part" in problems
    assert '"Terry" is said in cue 2 but written in cue 1' in problems


def test_split_sentence_is_quiet_when_each_part_is_once(tmp_path: Path):
    english = ["When the hearing starts tomorrow", "you will tell them everything."]
    w = make_work(tmp_path, english, ["Yarın duruşma başlayınca", "onlara her şeyi anlatacaksın."])
    assert warned(w, "split sentence") == {}


def test_split_sentence_allows_a_repeat_the_source_repeats_too(tmp_path: Path):
    english = ["The pigeons on the roof", "and the pigeons in the loft are mine."]
    w = make_work(tmp_path, english, ["Damdaki güvercinler", "ve kümesteki güvercinler benim."])
    assert warned(w, "split sentence") == {}


# --- the address check in two-person scenes --------------------------------


def address_work(tmp_path: Path, lines: list[str], speakers: dict) -> tuple[Path, dict]:
    rows = []
    for i, en in enumerate(lines, 1):
        s = (i - 1) * 3
        rows.append(
            {"n": i, "ts": "", "start": s * 1000, "end": (s + 2) * 1000, "timing_lines": [en], "source": [en], "en": None}
        )
    (tmp_path / "cues.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "speakers.json").write_text(json.dumps(speakers), encoding="utf-8")
    data = {
        "characters": [{"name": "Terry", "aliases": ["TERRY"]}, {"name": "Edie", "aliases": ["EDIE"]}],
        "decisions": [
            {"id": "address:Terry>Edie", "kind": "address", "speaker": "Terry", "listener": "Edie", "question": "?",
             "answer": [{"from_cue": 1, "form": "siz"}], "evidence": [1], "confidence": "sure"},
            {"id": "address:Edie>Terry", "kind": "address", "speaker": "Edie", "listener": "Terry", "question": "?",
             "answer": [{"from_cue": 1, "form": "sen"}], "evidence": [1], "confidence": "sure"},
            {"id": "voice:V9", "kind": "voice", "question": "?", "answer": "Terry", "evidence": [1], "confidence": "likely"},
        ],
    }  # fmt: skip
    (tmp_path / "decisions.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path, {r["n"]: r for r in rows}


def test_a_question_and_its_answer_with_one_voice_are_unsure(tmp_path: Path):
    lines = ["Are you going to the dance?", "No, I can't.", "Why not?"]
    w, rows = address_work(tmp_path, lines, {"1": {"voice": "V9"}, "2": {"voice": "V9"}, "3": {"voice": "V9", "label": "Terry"}})
    assert bible.unsure_turns(rows, json.loads((w / "speakers.json").read_text(encoding="utf-8"))) == {1, 2}
    # Cue 2 is Edie's answer heard as Terry's voice: sen there is no warning.
    texts = {1: ["Dansa gidiyor musun?"], 2: ["Hayır, gidemem. Sen?"]}
    assert bible.address_warnings(w, texts, rows) == []


def test_a_name_spoken_about_is_not_the_listener(tmp_path: Path):
    w, rows = address_work(tmp_path, ["You and Edie and the rest of them."], {"1": {"voice": "V9"}})
    reading = bible.address_readings(w, {1: ["Sen, Edie ve diğerleri."]}, rows)[0]
    assert reading["speaker"] == "Terry" and reading["listener"] is None


def test_a_two_speaker_cue_has_no_speaker(tmp_path: Path):
    w, rows = address_work(tmp_path, ["- Edie, sit down. - You sit down."], {"1": {"voice": "V9"}})
    rows[1]["timing_lines"] = rows[1]["source"] = ["- Edie, sit down.", "- You sit down."]
    assert bible.address_readings(w, {1: ["- Edie, sen otur.", "- Sen otur."]}, rows)[0]["speaker"] is None
