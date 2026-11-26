"""The listener step: listen parts, the gate, the meaning check's file,
and the order the listener's fix files apply in."""

import json
import os
from pathlib import Path

import assemble
import prepare


def film(tmp_path: Path, english: list[str], turkish: list[str]) -> Path:
    """A film of 2.5-second cues, 3 seconds apart. A cue may run on into
    the pause up to the usual gap (a quarter second at most): room for 46
    characters at 17 a second; the last cue, half a second more, 51."""
    blocks = []
    for i, en in enumerate(english, 1):
        s = (i - 1) * 3000
        blocks.append(f"{i}\n{_ts(s)} --> {_ts(s + 2500)}\n{en}\n")
    src = tmp_path / "film.en.srt"
    src.write_text("\n".join(blocks), encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, src, None, None)
    (w / "out").mkdir(exist_ok=True)
    (w / "out" / "tr_01.txt").write_text("".join(f"{i}\n{t}\n\n" for i, t in enumerate(turkish, 1)), encoding="utf-8")
    return w


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _rows(path: Path) -> dict[int, dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return {int(r[0]): dict(zip(head, r)) for r in (ln.split("\t") for ln in lines[1:])}


def _listen(w: Path, blocks: str) -> None:
    (w / "out" / "fix_listen_01.txt").write_text(blocks, encoding="utf-8")


def _touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


# --- listenparts ------------------------------------------------------------


def test_listen_parts_cut_the_film_with_budget_group_and_echo(tmp_path: Path):
    english = [f"Line {i}." for i in range(1, 101)]
    english[2] = english[79] = "Call the ship's doctor."
    english[9], english[10] = "When the ferry leaves tomorrow", "you will tell them everything."
    turkish = [f"Satır {i}." for i in range(1, 101)]
    turkish[2] = turkish[79] = "Gemi doktorunu çağırın."
    turkish[19] = "Bunu sana daha önce de söylemiştim, dinlemedin ama."  # 51 characters
    w = film(tmp_path, english, turkish)
    # The review shortened cue 20 into a stiff line; a rerun's old files go.
    (w / "out" / "fix_review_01.txt").write_text("20\nSöyledim.\n\n", encoding="utf-8")
    (w / "out" / "fix_listen_07.txt").write_text("5\nEski.\n\n", encoding="utf-8")
    (w / "out" / "fix_listencheck.txt").write_text("5\nEski.\n\n", encoding="utf-8")

    got = assemble.listen_parts(w, size=50)

    assert [(p["first"], p["last"]) for p in got["parts"]] == [(1, 50), (51, 100)]
    assert not (w / "out" / "fix_listen_07.txt").exists() and not (w / "out" / "fix_listencheck.txt").exists()
    before = json.loads((w / "out" / "listen_before.json").read_text(encoding="utf-8"))
    assert before["fix_files"] == ["fix_review_01.txt"] and before["texts"]["20"] == ["Söyledim."]
    one, two = _rows(Path(got["parts"][0]["file"])), _rows(Path(got["parts"][1]["file"]))
    # 17 a second over 2.75 seconds; the draft's 51 characters may come
    # back; the last cue may run half a second into the silence after it.
    assert one[21]["budget"] == "46" and one[20]["budget"] == "51" and two[100]["budget"] == "51"
    assert one[10]["group"] == one[11]["group"] == "10-11" and one[12]["group"] == ""
    # A repeated line names its echo in the other part.
    assert one[3]["echo"] == "80" and two[80]["echo"] == "3"
    assert one[20]["turkish"] == "Söyledim."
    # Not a polish run: no line is the human translator's.
    assert one[20]["human"] == "" and before["human"] == [] and got["human_cues"] == 0
    en = _rows(Path(got["parts"][0]["en_file"]))
    assert en[10]["source"] == "When the ferry leaves tomorrow"


# --- listengate -------------------------------------------------------------


GATE_EN = ["Call the ship's doctor.", "Hello there.", "Call the ship's doctor.", "When the ferry leaves tomorrow",
           "you will tell them everything.", "<i>It's cold.</i>", "Wait.", "Okay."]  # fmt: skip
GATE_TR = ["Gemi tabibini çağırın.", "Merhaba.", "Gemi tabibini çağırın.", "Yarın vapur kalkınca",
           "onlara her şeyi anlatacaksın.", "<i>Hava soğuk.</i>", "Dur.", "Tamam."]  # fmt: skip


def test_listen_gate_drops_each_edit_that_breaks_a_check_and_keeps_the_rest(tmp_path: Path):
    w = film(tmp_path, GATE_EN, GATE_TR)
    assemble.listen_parts(w, size=50)
    _listen(
        w,
        "1\nGemi doktorunu çağırın.\n\n"  # its repeated line (cue 3) still says it the old way
        "2\nSelam.\n\n"
        "5\nVapur kalkınca her şeyi anlat.\n\n"  # cue 4's part said twice
        "6\nHava soğuk.\n\n"  # lost the source's italics
        "7\nBekle bir saniye, sana söyleyeceğim çok önemli bir şey var.\n\n"  # 59 characters, budget 46
        "8\nTamam.\n\n"  # unchanged: not an edit
        "99\nFazla.\n\n",
    )

    gate = assemble.listen_gate(w)

    assert gate["dropped"] == {
        "hard fail: italic tags": [6],
        "not a listen cue": [99],
        "over budget": [7],
        "repeat drift": [1],
        "split sentence": [5],
    }
    assert gate["edits"] == 6 and gate["kept_cues"] == [2] and gate["left_unblamed"] == []
    # The file now holds only the edit that passed, and the Turkish has it.
    assert (w / "out" / "fix_listen_01.txt").read_text(encoding="utf-8") == "2\nSelam.\n\n"
    texts, _ = assemble.load_translation(w)
    assert texts[2] == ["Selam."] and texts[1] == ["Gemi tabibini çağırın."] and texts[6] == ["<i>Hava soğuk.</i>"]


def test_listen_gate_drops_an_edit_that_breaks_a_bible_repeat(tmp_path: Path):
    w = film(tmp_path, GATE_EN, GATE_TR)
    (w / "bible.md").write_text("## Tone notes\n- Repeated lines take identical Turkish: the doctor (1, 3)\n", encoding="utf-8")
    assemble.listen_parts(w, size=50)
    # The bible says cues 1 and 3 are said word for word: cue 1 alone may not move.
    _listen(w, "1\nGemi doktorunu çağırın.\n\n2\nSelam.\n\n")

    gate = assemble.listen_gate(w)

    assert gate["dropped"] == {"bible repeat": [1]}
    assert gate["kept_cues"] == [2]


def test_listen_gate_checks_again_after_dropping(tmp_path: Path):
    english = ["Hello.", "Fine.", "My brother is here.", "<i>Where's your brother?</i>", "Brother, wait."]
    turkish = ["Merhaba.", "İyi.", "Ağabeyim burada.", "<i>Abin nerede?</i>", "Abi, bekle."]
    w = film(tmp_path, english, turkish)
    assemble.listen_parts(w, size=50)
    # Together the two edits make the film say "ağabey" everywhere. Cue 4's
    # loses its italics and goes; cue 5's alone then leaves cue 4 the odd
    # "abi" out, a warning on a cue it never touched.
    _listen(w, "4\nAğabeyin nerede?\n\n5\nAğabey, bekle.\n\n")

    gate = assemble.listen_gate(w)

    assert gate["dropped"] == {"hard fail: italic tags": [4], "term drift": [5]}
    assert gate["passes"] == 3 and gate["kept"] == 0
    assert (w / "out" / "fix_listen_01.txt").read_text(encoding="utf-8") == ""


def test_run_checks_without_writing_checks_the_text_it_is_given(tmp_path: Path):
    w = film(tmp_path, ["Hello.", "Okay."], ["Merhaba.", "Tamam."])
    got = assemble.run_checks(w, {1: ["Merhaba."], 2: ["TAMAM."]}, write=False)
    assert [(x["cue"], x["check"]) for x in got["warnings"]] == [(2, "caps")]
    assert not any((w / name).exists() for name in ("draft.tr.srt", "cue_map.json", "checks.json"))
    # The reading speed warning carries its number for the gate.
    fast = assemble.run_checks(w, {1: ["Merhaba, bugün nasılsın, iyi misin bakalım, ha?"], 2: ["Tamam."]}, write=False)
    speed = [x for x in fast["warnings"] if x["check"] == "reading speed"]
    assert speed and speed[0]["cps"] > 17


# --- listencheck, listendrop and the review notes ---------------------------


def test_listen_check_lists_each_kept_edit_with_its_ties(tmp_path: Path):
    w = film(tmp_path, GATE_EN, GATE_TR)
    assemble.listen_parts(w, size=50)
    _listen(w, "1\nGemi doktorunu çağırın.\n\n3\nGemi doktorunu çağırın.\n\n")
    assert assemble.listen_gate(w)["kept_cues"] == [1, 3]

    got = assemble.listen_check(w)

    assert got["edits"] == 2 and got["write_to"].endswith("fix_listencheck.txt")
    text = Path(got["file"]).read_text(encoding="utf-8")
    first = text.split("#1\n")[1].split("\n\n")[0].splitlines()
    assert first == [
        "speaker: ",
        "src: Call the ship's doctor.",
        "before: Gemi tabibini çağırın.",
        "after: Gemi doktorunu çağırın.",
        "next: 2: Merhaba.",
        "with: 3",
    ]
    assert "prev: 2: Merhaba." in text.split("#3\n")[1]


def test_listen_drop_and_reviews_count_the_listener(tmp_path: Path):
    w = film(tmp_path, GATE_EN, GATE_TR)
    assemble.listen_parts(w, size=50)
    _listen(w, "2\nSelam.\n\n6\nHava soğuk.\n\n7\nBekle.\n\n8\nPeki.\n\n")
    assemble.listen_gate(w)
    # The meaning check writes cue 8's old line back.
    (w / "out" / "fix_listencheck.txt").write_text("8\nTamam.\n\n", encoding="utf-8")
    # The last check fails cue 7: its edit goes.
    assert assemble.listen_drop(w, [7, 40]) == {"dropped": [7]}
    assert "7\n" not in (w / "out" / "fix_listen_01.txt").read_text(encoding="utf-8")

    assemble.join_reviews(w)

    review = (w / "review.md").read_text(encoding="utf-8")
    listener = review.split("## Listener\n\n")[1]
    assert "- Edits kept: 2 of 8 spoken cues (2, 8)" in listener
    assert "- Dropped by the gate, hard fail: italic tags: 1 (6)" in listener
    assert "- Dropped by the gate, hard fail at the last check: 1 (7)" in listener
    assert "- Written back by the meaning check: 1 (8)" in listener
    assert assemble.load_translation(w)[0][8] == ["Tamam."]


# --- a polish run: the listener leaves the human lines -----------------------


def polish_film(tmp_path: Path, english: list[str], human: list[str], unplaced: set[int]) -> Path:
    """A polish run's work folder: the human file's lines placed on the
    timing file as the seed (out/tr_00.txt), but for the cues in
    `unplaced`, which the human file had no line for."""
    w = film(tmp_path, english, human)
    out = w / "out"
    seed = "".join(f"{i}\n{t}\n\n" for i, t in enumerate(human, 1) if i not in unplaced)
    (out / "tr_00.txt").write_text(seed, encoding="utf-8")
    (out / "tr_01.txt").unlink()
    (w / "polish_placement.json").write_text("{}", encoding="utf-8")
    return w


def _polish_hundred(tmp_path: Path) -> Path:
    english = [f"Line {i}." for i in range(1, 101)]
    english[9], english[10] = "When the ferry leaves tomorrow", "you will tell them everything."
    human = [f"Satır {i}." for i in range(1, 101)]
    human[9], human[10] = "Yarın vapur kalkınca", "onlara her şeyi anlatacaksın."
    w = polish_film(tmp_path, english, human, unplaced={5})
    # The fixer wrote the cue the human file missed; a reviewer changed
    # half of the sentence on cues 10-11, and cue 20.
    (w / "out" / "fix_polish.txt").write_text("5\nBeş.\n\n", encoding="utf-8")
    (w / "out" / "fix_review_01.txt").write_text("11\nher şeyi anlatacaksın.\n\n20\nYirmi.\n\n", encoding="utf-8")
    return w


def test_listen_parts_mark_the_human_lines_of_a_polish_run(tmp_path: Path):
    w = _polish_hundred(tmp_path)

    got = assemble.listen_parts(w, size=50)

    # Cues 51-100 are all the human file's lines: that part gets no listener.
    assert [(p["first"], p["last"]) for p in got["parts"]] == [(1, 50)]
    assert got["parts_all_human"] == 1 and got["human_cues"] == 96
    one = _rows(Path(got["parts"][0]["file"]))
    assert one[1]["human"] == one[12]["human"] == "yes"
    # Lines the run wrote, and the untouched half of a changed sentence.
    assert one[5]["human"] == one[10]["human"] == one[11]["human"] == one[20]["human"] == ""
    before = json.loads((w / "out" / "listen_before.json").read_text(encoding="utf-8"))
    assert 5 not in before["human"] and 12 in before["human"] and 60 in before["human"]


def test_listen_gate_drops_an_edit_to_a_human_line(tmp_path: Path):
    w = _polish_hundred(tmp_path)
    assemble.listen_parts(w, size=50)
    _listen(w, "12\nOn ikinci satır.\n\n20\nYirmi işte.\n\n60\nAltmış.\n\n")

    gate = assemble.listen_gate(w)

    assert gate["dropped"] == {"human line": [12, 60]}
    assert gate["kept_cues"] == [20] and gate["human_cues"] == 96
    assert (w / "out" / "fix_listen_01.txt").read_text(encoding="utf-8") == "20\nYirmi işte.\n\n"
    summary = assemble.listen_summary(w)
    assert "- Human lines read for the scene and left as they are: 96" in summary


# --- the order fix files apply in --------------------------------------------


def test_listener_files_apply_after_the_files_it_listened_to(tmp_path: Path):
    w = film(tmp_path, ["Hello.", "Okay."], ["Merhaba.", "Tamam."])
    out = w / "out"
    (out / "fix_review_01.txt").write_text("1\nSelam.\n\n", encoding="utf-8")
    (out / "fix_post_01.txt").write_text("2\nPeki.\n\n", encoding="utf-8")
    t = (out / "tr_01.txt").stat().st_mtime
    _touch(out / "fix_review_01.txt", t + 10)
    _touch(out / "fix_post_01.txt", t + 20)
    assemble.listen_parts(w, size=50)
    _touch(out / "listen_before.json", t + 30)
    # The listener's files carry older times than the review's (a copied
    # folder, a clock change): they still apply after what they listened to.
    (out / "fix_listen_01.txt").write_text("1\nSelam sana.\n\n2\nOlur.\n\n", encoding="utf-8")
    (out / "fix_listencheck.txt").write_text("2\nPeki.\n\n", encoding="utf-8")
    _touch(out / "fix_listen_01.txt", t + 5)
    _touch(out / "fix_listencheck.txt", t + 1)
    # A fix round after the listener still wins.
    (out / "fix_post_02.txt").write_text("1\nSelamlar.\n\n", encoding="utf-8")
    _touch(out / "fix_post_02.txt", t + 40)

    order = [p.name for p in assemble.fix_order(out)]

    assert order == ["fix_review_01.txt", "fix_post_01.txt", "fix_listen_01.txt", "fix_listencheck.txt", "fix_post_02.txt"]
    assert assemble.load_translation(w)[0] == {1: ["Selamlar."], 2: ["Peki."]}
