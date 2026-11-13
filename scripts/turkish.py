"""Turkish-only rules for laying out and checking the delivered subtitle,
kept in one place so another target language gets its own module.

From the Netflix Turkish Timed Text Style Guide:

- I.12 line breaks: never start the second line with a postposition or a
  particle that belongs to the word before it ("gibi", "diye", "mi", "de"),
  break before a conjunction rather than after it, and never leave one
  word alone on a line. A break right after a sentence end is always
  fine ("Güzel bir gündü." / "Değil mi?"). "bir" stays with the word after it. Song lines
  keep the song's own line breaks.
- I.22 accents: "hâlâ" (still) and "hala" (aunt), "âşık" (in love) and
  "aşık" (knucklebone) differ only by the circumflex, and the plain
  spelling is the common slip.
"""

from __future__ import annotations

import re

# Words that lean on the word before them: a line must not start with one.
POSTPOSITIONS = {
    "gibi", "diye", "kadar", "için", "ile", "göre", "rağmen", "beri", "dek",
    "değil", "üzere", "karşın", "dolayı", "ötürü", "boyunca", "benzeri",
}  # fmt: skip
PARTICLES = {"de", "da", "ki", "mi", "mı", "mu", "mü"}
# Question particles with a person or tense ending ("misin", "mıydı").
QUESTION_RE = re.compile(r"m[ıiuü](y?[ıiuü]m|s[ıiuü]n|y?[ıiuü]z|s[ıiuü]n[ıiuü]z|d[ıiuü]r|yd[ıiuü]|ym[ıiuü]ş)?")
# Nouns spelled like a question particle with an ending ("müdür", director).
NOT_PARTICLES = {"müdür"}
# A second line may well start with one of these.
CONJUNCTIONS = {"ve", "ama", "fakat", "ancak", "çünkü", "yoksa", "veya", "ya", "hem", "eğer", "yani", "oysa"}

WORD_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜâîûÂÎÛ]+")
TAG_RE = re.compile(r"<[^>]*>|\{[^}]*\}")


def lower(word: str) -> str:
    """Turkish lower case: "I" is "ı" and "İ" is "i"."""
    return word.replace("I", "ı").replace("İ", "i").lower()


def _first_word(text: str) -> str:
    m = WORD_RE.search(TAG_RE.sub("", text))
    return lower(m.group()) if m else ""


def leans_back(word: str) -> bool:
    """The word belongs to the one before it, so no line may start with it."""
    if word in NOT_PARTICLES:
        return False
    return word in POSTPOSITIONS or word in PARTICLES or bool(QUESTION_RE.fullmatch(word))


def starts_with_conjunction(text: str) -> bool:
    return _first_word(text) in CONJUNCTIONS


def bad_break(first: str, second: str) -> str | None:
    """Why breaking a line between `first` and `second` reads badly, or None."""
    first, second = TAG_RE.sub("", first), TAG_RE.sub("", second)
    if "♪" in first + second:
        return None  # a lyric keeps the song's own lines
    if first.rstrip().endswith((".", "!", "?", "…")):
        return None  # a break after a sentence end is always a good one ("Değil mi?")
    if [lower(w) for w in WORD_RE.findall(first)[-1:]] == ["bir"]:
        return 'the first line ends with "bir", which belongs to the line below'
    if leans_back(_first_word(second)):
        return f'the second line starts with "{_first_word(second)}", which belongs to the line above'
    for line in (first, second):
        if len(WORD_RE.findall(line)) == 1:
            return f'"{line.strip()}" stands alone on a line'
    return None


# Plain spellings that are almost always a missing circumflex, with the
# word that was most likely meant.
ACCENT_SLIPS = {
    "hala": 'hâlâ ("still"), unless it means "aunt"',
    "aşık": 'âşık ("in love"), unless it means "knucklebone"',
    "aşığım": "âşığım",
    "aşıksın": "âşıksın",
    "aşığı": "âşığı",
    "aşığın": "âşığın",
}


def accent_slips(text: str) -> list[tuple[str, str]]:
    """Each plain spelling in `text` that probably lacks its circumflex,
    with what was most likely meant."""
    words = WORD_RE.findall(TAG_RE.sub("", text))
    return [(w, ACCENT_SLIPS[lower(w)]) for w in words if lower(w) in ACCENT_SLIPS]
