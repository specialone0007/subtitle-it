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

From the TDK spelling rules, for the checks:

- Common spelling slips: "herşey" for "her şey", "sağol" for "sağ ol",
  "bir çok" for "birçok", "yanlız" for "yalnız".
- Name suffixes follow how the name sounds: "Joey'nin", "Ray'in".
- One form of a word with two ("abi" or "ağabey", "celp" or "celpname")
  for the whole film, and the bible's rendering of each term it decided.
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


# Spellings the TDK dictionary writes otherwise, which slip into subtitles
# often: words written together that are two ("her şey", "sağ ol"), two
# that are one ("birçok", "hiçbir"), and common misspellings. A pattern
# matches a whole word in lower case and keeps any ending after it
# ("herşeyi" -> "her şeyi").
SPELLING_SLIPS = [
    (re.compile(r"(hiç)?(bir|her)şey(\w*)"), lambda m: f"{m[1] or ''}{m[2]} şey{m[3]}"),
    (re.compile(r"bişey(\w*)"), lambda m: f"bir şey{m[1]}"),
    (re.compile(r"sağol(\w*)"), lambda m: f"sağ ol{m[1]}"),
    (re.compile(r"birarada"), lambda m: "bir arada"),
    (re.compile(r"herzaman"), lambda m: "her zaman"),
    (re.compile(r"hergün"), lambda m: "her gün"),
    (re.compile(r"birdaha"), lambda m: "bir daha"),
    (re.compile(r"birsürü"), lambda m: "bir sürü"),
    (re.compile(r"şuan(da)?"), lambda m: f"şu an{m[1] or ''}"),
    (re.compile(r"yinede"), lambda m: "yine de"),
    (re.compile(r"yada"), lambda m: "ya da"),
    (re.compile(r"yanlız(\w*)"), lambda m: f"yalnız{m[1]}"),
    (re.compile(r"yalnış(\w*)"), lambda m: f"yanlış{m[1]}"),
    (re.compile(r"herkez(\w*)"), lambda m: f"herkes{m[1]}"),
    (re.compile(r"malesef"), lambda m: "maalesef"),
    (re.compile(r"orjinal(\w*)"), lambda m: f"orijinal{m[1]}"),
    (re.compile(r"deyil(\w*)"), lambda m: f"değil{m[1]}"),
    (re.compile(r"pekala"), lambda m: "pekâlâ"),
]
# Two words the TDK writes as one.
JOINED = {("bir", "çok"): "birçok", ("hiç", "bir"): "hiçbir", ("hiç", "biri"): "hiçbiri", ("her", "hangi"): "herhangi",
          ("bir", "kaç"): "birkaç"}  # fmt: skip


def spelling_slips(text: str) -> list[tuple[str, str]]:
    """Each spelling in `text` that the TDK writes otherwise, with the
    TDK form: [("herşey", "her şey"), ("bir çok", "birçok")]."""
    plain = TAG_RE.sub("", text)
    out = []
    words = list(WORD_RE.finditer(plain))
    for m in words:
        low = lower(m.group())
        for rx, fix in SPELLING_SLIPS:
            hit = rx.fullmatch(low)
            if hit:
                out.append((m.group(), fix(hit)))
                break
    for a, b in zip(words, words[1:]):
        pair = (lower(a.group()), lower(b.group()))
        if pair in JOINED and plain[a.end() : b.start()] == " ":
            out.append((f"{a.group()} {b.group()}", JOINED[pair]))
    return out


# --- apostrophe suffixes on names -----------------------------------------

NAME_SUFFIX_RE = re.compile(r"(?<![\w'’])([A-ZÇĞİÖŞÜ][\wçğıöşüâîû]*)['’]([a-zçğıöşüâîû]+)")
VOWELS = set("aeıioöuüâîû")
GENITIVE = {"in", "ın", "un", "ün"}


def ends_in_vowel_sound(name: str) -> bool | None:
    """Whether a name ends in a vowel when said aloud, which decides the
    suffix after its apostrophe: "Joey'nin", "Ray'in". None when the
    spelling cannot tell: a final "e" is silent in "Mike" and said in
    "Ayşe", and a final "h" or "w" may be either."""
    low = lower(name)
    last = low[-1]
    if last == "y":
        # "Joey", "Terry", "Charley" end in an "i" sound; "Ray", "Roy" and
        # "Guy" in a "y" that Turkish hears as a consonant.
        return len(low) < 2 or low[-2] not in "aou"
    if last == "e":
        return True if low.endswith(("ie", "ee")) else None
    if last in "hw":
        return None
    return last in VOWELS


def name_suffix_slips(text: str) -> list[tuple[str, str]]:
    """Each name whose apostrophe suffix does not fit how the name ends
    when said aloud, with the suffix it needs: after a vowel sound a
    suffix that starts with a vowel takes "n" (genitive) or "y"
    ("Joey'in" -> "Joey'nin", "Joey'e" -> "Joey'ye"); after a consonant
    it takes neither ("John'nun" -> "John'un"). Names in capitals (FBI)
    are read letter by letter and left alone."""
    out = []
    for m in NAME_SUFFIX_RE.finditer(TAG_RE.sub("", text)):
        name, suffix = m.group(1), m.group(2)
        if name.isupper():
            continue  # a letter or an acronym, said by its letter names ("D'yi", "FBI'ın")
        vowel = ends_in_vowel_sound(name)
        if vowel and suffix[0] in VOWELS:
            buffer = "n" if suffix[:2] in GENITIVE and suffix[2:] in ("", "ki") else "y"
            out.append((m.group(), f"{name}'{buffer}{suffix}"))
        elif vowel is False and len(suffix) > 1 and suffix[1] in VOWELS:
            if (suffix[0] == "n" and suffix[:3] in {"nin", "nın", "nun", "nün"}) or suffix[0] == "y":
                out.append((m.group(), f"{name}'{suffix[1:]}"))
    return out


# --- one rendering per term ------------------------------------------------

# Words with two accepted spellings or forms that a film should not mix:
# whichever the draft uses most wins, and the others are flagged. Each
# pattern matches a whole word in lower case, endings included.
VARIANT_FAMILIES = [
    {"abi": re.compile(r"abi(?:[mn]|si|ler\w*|y[ei]|nin|ciğim|cim)?"), "ağabey": re.compile(r"ağabey\w*")},
    {"celp": re.compile(r"cel(?:p|bi\w*|be|pler\w*)"), "celpname": re.compile(r"celpname\w*")},
    {"abla": re.compile(r"abla(?:[mn]|sı|lar\w*|y[aı]|nın|cığım|cım)?"), "ablacım": re.compile(r"ablacı(?:m|ğım)")},
]


def family_drift(texts: dict[int, list[str]], bible_text: str = "") -> list[tuple[int, str, str, int]]:
    """Cues that use a less common member of a variant family than the rest
    of the film: (cue, word used, the film's usual form, how many cues use
    that). A member the bible's answers use (`bible_text`) wins whatever
    the counts."""
    bible_words = [lower(w) for w in WORD_RE.findall(bible_text)]
    out = []
    for family in VARIANT_FAMILIES:
        prefer = {m for m, rx in family.items() if any(rx.fullmatch(w) for w in bible_words)}
        used: dict[str, list[int]] = {}
        for n, lines in texts.items():
            words = [lower(w) for w in WORD_RE.findall(TAG_RE.sub("", " ".join(lines)))]
            for member, rx in family.items():
                if any(rx.fullmatch(w) for w in words):
                    used.setdefault(member, []).append(n)
        if len(used) < 2:
            continue
        order = list(family)
        main = max(used, key=lambda k: (k in prefer, len(used[k]), -order.index(k)))
        for member, cues in used.items():
            if member != main:
                out += [(n, member, main, len(used[main])) for n in cues if n not in used[main]]
    return sorted(out)


def stem(word: str) -> str:
    """The part of a Turkish word its endings attach to, loosely: a last
    vowel or a last hard consonant that softens ("celp" -> "celbi") is
    dropped from words of four letters or more."""
    w = lower(word)
    if len(w) >= 5 and w.endswith(("mek", "mak")):
        return w[:-3]  # a verb: "ötmek" -> "öt" ("ötecek", "öttü")
    return w[:-1] if len(w) >= 4 and w[-1] in "pçtkaeıioöuü" else w


def has_rendering(text: str, answer: str) -> bool:
    """`text` holds a form of `answer`, by the stem of any of its words of
    three letters or more. An answer with no such word ("S ve D") cannot
    be checked and always passes."""
    stems = [stem(w) for w in WORD_RE.findall(answer) if len(w) >= 3]
    words = [lower(w) for w in WORD_RE.findall(TAG_RE.sub("", text))]
    return not stems or any(w.startswith(s) for s in stems for w in words)
