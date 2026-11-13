"""Turkish-only rules from the Netflix Turkish style guide: line breaks
(I.12), the 17 characters a second limit (I.17) and accents (I.22)."""

from pathlib import Path

import pytest

import assemble
import layout
import prepare
import srt
import turkish


@pytest.mark.parametrize(
    ("first", "second", "bad"),
    [
        ("Senin", "gibi biri buraya gelmedi.", True),
        ("Bunu yapacak", "mısın gerçekten?", True),
        ("Ben", "de geliyorum, bekle beni.", True),
        ("<i>Onun için her şeyi yaptım ama o</i>", "<i>kadar umursamadı.</i>", True),
        ("Bunu sana söylemiştim ama", "hatırlamıyorsun.", True),
        ("Bunu sana söylemiştim", "ama hatırlamıyorsun.", False),
        ("Hayır.", "Bunu bir daha asla yapmayacağım.", False),
        ("Gel.", "Hemen.", False),
        ("Senin gibi biri", "buraya hiç gelmedi.", False),
        ("Hepiniz daha iyi bir", "şey için çaresizsiniz.", True),
        ("<i>♪ Öpüşelim", "Gerçek insanlar gibi ♪</i>", False),
    ],
)
def test_bad_break(first, second, bad):
    assert (turkish.bad_break(first, second) is not None) is bad


def test_question_particles_with_endings_lean_back():
    for word in ("misin", "mısınız", "muydu", "müyüm", "midir"):
        assert turkish.leans_back(word), word
    for word in ("misafir", "mutfak", "müdür"):
        assert not turkish.leans_back(word), word


def test_turkish_wrap_never_starts_a_line_with_a_word_that_leans_back():
    text = "Senin gibi birinin buraya kadar gelmesini hiç beklemiyordum"
    plain = srt.wrap(text, 42)
    tr = srt.wrap(text, 42, lang="tr")
    assert all(len(ln) <= 42 for ln in tr) and " ".join(tr) == text
    assert turkish.bad_break(*tr) is None
    # The plain wrap is unchanged for other languages.
    assert plain == srt.wrap(text, 42, lang=None)


def test_turkish_wrap_prefers_a_break_before_a_conjunction():
    text = "Bunu sana defalarca söylemiştim ama sen beni hiç dinlemedin"
    assert srt.wrap(text, 42, lang="tr") == ["Bunu sana defalarca söylemiştim", "ama sen beni hiç dinlemedin"]


def test_turkish_wrap_still_breaks_after_a_sentence_end_first():
    text = "Nereye gittin? Seni bütün gün boyunca her yerde aradım."
    assert srt.wrap(text, 42, lang="tr") == ["Nereye gittin?", "Seni bütün gün boyunca her yerde aradım."]


def test_layout_rebreaks_two_lines_that_read_badly():
    parts, why = layout.plan(0, 3000, ["Senin", "gibi biri buraya hiç gelmedi."], 80)
    assert why is None and parts[0].lines == ["Senin gibi biri buraya hiç gelmedi."]
    lines = ["Onun için her şeyi yaptım ama o", "kadar da umursamadı beni hiçbir zaman."]
    parts, why = layout.plan(0, 4000, lines, 80)
    assert why is None and turkish.bad_break(*parts[0].lines) is None
    assert " ".join(parts[0].lines) == " ".join(lines)


def test_layout_keeps_song_lines_as_the_song_breaks_them():
    lines = ["<i>♪ Öpüşelim", "Gerçek insanlar gibi ♪</i>"]
    assert layout.plan(0, 3000, lines, 80)[0][0].lines == lines


def test_layout_keeps_a_bad_break_it_cannot_improve():
    # Both words are long: no other break fits, so the lines stay as written.
    lines = ["Muvaffakiyetsizleştiricileştiriveremeyebileceklerimizden", "misiniz?"]
    parts, _ = layout.plan(0, 4000, lines, 80)
    assert parts[0].lines == lines


@pytest.mark.parametrize(
    ("text", "slips"),
    [
        ("Hala burada mısın?", ["Hala"]),
        ("Sana aşığım.", ["aşığım"]),
        ("<i>O hâlâ burada.</i>", []),
        ("Halam yarın geliyor.", []),
        ("Kar yağıyor.", []),
    ],
)
def test_accent_slips(text, slips):
    assert [w for w, _ in turkish.accent_slips(text)] == slips


FILM = """1
00:00:01,000 --> 00:00:03,000
Are you still here?

2
00:00:04,000 --> 00:00:05,000
I really cannot believe you did all of that.
"""


def test_check_warns_on_every_fast_line_and_on_accent_slips(tmp_path: Path):
    src = tmp_path / "film.en.srt"
    src.write_text(FILM, encoding="utf-8")
    w = tmp_path / "work"
    prepare.build(w, src, None, None)
    (w / "out").mkdir(exist_ok=True)
    tr = "1\nHala burada mısın?\n\n2\nBütün bunları yaptığına gerçekten inanamıyorum.\n"
    (w / "out" / "tr_01.txt").write_text(tr, encoding="utf-8")
    r = assemble.run_checks(w)
    warned = {(x["cue"], x["check"]) for x in r["warnings"]}
    assert (1, "accent") in warned
    # Cue 2 runs at 47 characters a second, and so does the English: the
    # warning stands anyway, since the viewer reads Turkish.
    assert (2, "reading speed") in warned
    assert (1, "reading speed") not in warned
