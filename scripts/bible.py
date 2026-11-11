# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the film bible's decisions with a second, independent reader.

    uv run bible.py questions --work W
    uv run bible.py compare   --work W
    uv run bible.py cues      --work W --cues 12,340 [--context 2]
    uv run bible.py apply     --work W
    uv run bible.py voices    --work W

The bible writer records each decision in W/decisions.json with the cues
that support it. `questions` writes W/questions.json: the same questions with
no answers, for the second reader, who answers them in W/second.json.
`compare` writes W/compare.json: the decisions both readers agree on, and the
ones a judge must settle. The judge looks at the cited cues with `cues` and
writes W/judged.json. `apply` puts the judge's answers into decisions.json and
lists the ties: questions the cues could not settle, decided by a safe default.

When the audio step runs alongside the bible writer, the writer sees no
voices. The voice mapper then writes W/voices.json, and `voices` adds its
decisions to decisions.json and its lines to bible.md, before `questions`.

decisions.json:

    {"characters": [{"name": "Sam", "aliases": ["SAM", "Sammy"]}],
     "decisions": [
       {"id": "address:Sam>Nora", "kind": "address", "speaker": "Sam", "listener": "Nora",
        "question": "Does Sam say sen or siz to Nora?",
        "answer": [{"from_cue": 1, "form": "siz"}, {"from_cue": 400, "form": "sen"}],
        "evidence": [12, 405], "confidence": "sure"},
       {"id": "voice:V3", "kind": "voice", "question": "Who is voice V3?",
        "answer": "Sam", "evidence": [40, 41], "confidence": "likely"}]}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402

KINDS = {"address", "voice", "name", "term"}
FORMS = {"sen", "siz"}
CONFIDENCE = {"sure", "likely", "guess"}
# `apply` marks a judge's safe default as a tie. Readers never write it.
STORED_CONFIDENCE = CONFIDENCE | {"tie"}
# Two readers rarely put a sen-to-siz switch on the same cue. Switches this
# many cues apart or fewer are taken as the same scene.
ADDRESS_TOLERANCE = 40


# --- reading and checking the files --------------------------------------


def _load(path: Path):
    if not path.exists():
        raise SystemExit(f"{path.name} is missing in {path.parent}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path.name} is not valid JSON: {e}") from e


def _load_object(path: Path) -> dict:
    data = _load(path)
    if not isinstance(data, dict):
        raise SystemExit(f"{path.name} must hold a JSON object, not {type(data).__name__}")
    return data


def _check_answer(kind: str, answer, where: str) -> list[str]:
    if answer is None:
        return []
    if kind == "address":
        if not isinstance(answer, list) or not answer:
            return [f"{where}: an address answer is a list of {{from_cue, form}}"]
        problems = []
        last = 0
        for seg in answer:
            if not isinstance(seg, dict) or not isinstance(seg.get("from_cue"), int) or seg.get("form") not in FORMS:
                problems.append(f"{where}: each step needs an int from_cue and a form of sen or siz")
                continue
            if seg["from_cue"] <= last and last:
                problems.append(f"{where}: from_cue must go up")
            last = seg["from_cue"]
        return problems
    if not isinstance(answer, str) or not answer.strip():
        return [f"{where}: the answer is a non-empty string"]
    return []


def check_decision(d: dict, where: str, full: bool = True, allowed: set[str] = CONFIDENCE) -> list[str]:
    """Problems with one decision. `full` is False for the second reader's
    answers, which carry only id, answer, evidence and confidence."""
    if not isinstance(d, dict) or not isinstance(d.get("id"), str):
        return [f"{where}: each entry needs a string id"]
    where = f"{where} {d['id']}"
    problems = []
    if full:
        if d.get("kind") not in KINDS:
            problems.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if not isinstance(d.get("question"), str):
            problems.append(f"{where}: question must be a string")
        if d.get("kind") == "address" and not (isinstance(d.get("speaker"), str) and isinstance(d.get("listener"), str)):
            problems.append(f"{where}: an address decision names its speaker and listener")
    if not isinstance(d.get("evidence"), list) or not all(isinstance(n, int) for n in d.get("evidence", [None])):
        problems.append(f"{where}: evidence is a list of cue numbers")
    if d.get("confidence") not in allowed:
        problems.append(f"{where}: confidence must be one of {sorted(allowed)}")
    return problems


def load_decisions(work: Path) -> dict:
    data = _load_object(work / "decisions.json")
    problems = []
    if not isinstance(data.get("characters"), list) or not isinstance(data.get("decisions"), list):
        raise SystemExit("decisions.json needs a characters list and a decisions list")
    for c in data["characters"]:
        aliases = c.get("aliases", []) if isinstance(c, dict) else None
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"].strip():
            problems.append("decisions.json: each character needs a non-empty string name")
        elif not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            problems.append(f"decisions.json character {c['name']}: aliases is a list of strings")
    ids = set()
    for d in data["decisions"]:
        problems += check_decision(d, "decisions.json", allowed=STORED_CONFIDENCE)
        if isinstance(d, dict):
            problems += _check_answer(d.get("kind"), d.get("answer"), f"decisions.json {d.get('id')}")
            if d.get("answer") is None:
                problems.append(f"decisions.json {d.get('id')}: the bible writer answers every question")
            if d.get("id") in ids:
                problems.append(f"decisions.json: id {d.get('id')} is used twice")
            ids.add(d.get("id"))
    if problems:
        raise SystemExit("decisions.json has problems:\n" + "\n".join(problems[:20]))
    return data


# --- questions -----------------------------------------------------------

QUESTION_FIELDS = ("id", "kind", "question", "speaker", "listener")


def questions(work: Path) -> dict:
    data = load_decisions(work)
    qs = [{k: d[k] for k in QUESTION_FIELDS if k in d} for d in data["decisions"]]
    (work / "questions.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
    by_kind: dict[str, int] = {}
    for q in qs:
        by_kind[q["kind"]] = by_kind.get(q["kind"], 0) + 1
    return {"questions": len(qs), "by_kind": by_kind, "file": str(work / "questions.json")}


# --- compare -------------------------------------------------------------


def form_at(answer: list[dict], n: int) -> str | None:
    """The address form an answer gives for cue n: the last step that starts
    at or before n, or the first step for cues before any step starts."""
    steps = sorted(answer, key=lambda s: s["from_cue"])
    form = steps[0]["form"]
    for s in steps:
        if s["from_cue"] <= n:
            form = s["form"]
    return form


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().strip("\"'“”‘’").casefold())


def _steps(answer: list[dict]) -> list[tuple[int, str]]:
    """An address answer as (from_cue, form) switches: steps that repeat the
    form before them are dropped, and the first step covers the film from
    its start."""
    out: list[tuple[int, str]] = []
    for st in sorted(answer, key=lambda x: x["from_cue"]):
        if not out:
            out.append((1, st["form"]))
        elif st["form"] != out[-1][1]:
            out.append((st["from_cue"], st["form"]))
    return out


def _head(s: str) -> str:
    """An answer up to its first bracket, semicolon or comma: "Leo (Sam's
    friend)" -> "leo"."""
    return _norm(re.split(r"[(;,]", s, maxsplit=1)[0])


def _first_character(s: str, characters: list[dict]) -> str | None:
    """The character an answer names first, by name or alias as whole words,
    or None when it names none."""
    best: tuple[int, str] | None = None
    text = s.casefold()
    for c in characters:
        for word in [c["name"], *c.get("aliases", [])]:
            if not word.strip():
                continue
            m = re.search(rf"(?<!\w){re.escape(word.casefold())}(?!\w)", text)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), c["name"])
    return best[1] if best else None


def agree(kind: str, a, b, characters: list[dict] | None = None) -> bool:
    """Same answer. Address answers agree when they give the same forms in
    the same order, each switch within ADDRESS_TOLERANCE cues of the other.
    Voice answers agree when they name the same character first, or read the
    same up to a bracket: "Harlan Pike" and "Uncle Harlan Pike" agree,
    "Edwin Van Dorn" and "Ruth Calloway (talking Sam into the trip)" do not."""
    if a is None or b is None:
        return False
    if kind == "address":
        sa, sb = _steps(a), _steps(b)
        return [f for _, f in sa] == [f for _, f in sb] and all(abs(x - y) <= ADDRESS_TOLERANCE for (x, _), (y, _) in zip(sa, sb))
    if _norm(a) == _norm(b):
        return True
    if kind == "voice":
        if _head(a) and _head(a) == _head(b):
            return True
        who_a = _first_character(a, characters or [])
        return who_a is not None and who_a == _first_character(b, characters or [])
    return False


def _side(d: dict) -> dict:
    return {"answer": d.get("answer"), "evidence": d.get("evidence", []), "confidence": d.get("confidence")}


def compare(work: Path) -> dict:
    data = load_decisions(work)
    second = _load_object(work / "second.json")
    answers = second.get("answers", [])
    extra = second.get("extra", [])
    if not isinstance(answers, list) or not isinstance(extra, list):
        raise SystemExit("second.json needs an answers list and an extra list")
    kinds = {d["id"]: d["kind"] for d in data["decisions"]}
    problems = []
    for a in answers:
        problems += check_decision(a, "second.json", full=False)
        if isinstance(a, dict) and a.get("id") in kinds:
            problems += _check_answer(kinds[a["id"]], a.get("answer"), f"second.json {a['id']}")
        elif isinstance(a, dict):
            problems.append(f"second.json {a.get('id')}: not a question in questions.json; put new questions under extra")
    for e in extra:
        problems += check_decision(e, "second.json extra")
        if isinstance(e, dict):
            problems += _check_answer(e.get("kind"), e.get("answer"), f"second.json extra {e.get('id')}")
            if e.get("id") in kinds:
                problems.append(f"second.json extra {e.get('id')}: this id is already a question; give it a new id")
    if problems:
        raise SystemExit("second.json has problems:\n" + "\n".join(problems[:20]))

    second_by_id = {a["id"]: a for a in answers}
    agreed, to_judge = [], []
    for d in data["decisions"]:
        s = second_by_id.get(d["id"])
        if s is not None and agree(d["kind"], d["answer"], s.get("answer"), data["characters"]):
            agreed.append(d["id"])
            continue
        item = {k: d[k] for k in QUESTION_FIELDS if k in d}
        item["writer"] = _side(d)
        item["second"] = _side(s) if s is not None and s.get("answer") is not None else None
        item["why"] = "the readers disagree" if item["second"] else "the second reader gave no answer"
        to_judge.append(item)
    for e in extra:
        item = {k: e[k] for k in QUESTION_FIELDS if k in e}
        item["writer"] = None
        item["second"] = _side(e)
        item["why"] = "only the second reader asked this"
        to_judge.append(item)

    out = {"agreed": agreed, "to_judge": to_judge}
    # A new comparison makes any earlier verdicts stale.
    (work / "judged.json").unlink(missing_ok=True)
    (work / "compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "decisions": len(data["decisions"]),
        "agreed": len(agreed),
        "to_judge": len(to_judge),
        "judge_ids": [t["id"] for t in to_judge],
        "file": str(work / "compare.json"),
    }


# --- cues for the judge --------------------------------------------------


def cues(work: Path, numbers: list[int], context: int) -> list[dict]:
    rows = _load(work / "cues.json")
    speakers_file = work / "speakers.json"
    speakers = _load(speakers_file) if speakers_file.exists() else {}
    by_n = {r["n"]: r for r in rows}
    wanted = sorted({m for n in numbers for m in range(n - context, n + context + 1) if m in by_n})
    out = []
    for m in wanted:
        r = by_n[m]
        sp = speakers.get(str(m), {})
        who = " · ".join(x for x in (sp.get("name") or sp.get("label"), sp.get("voice")) if x)
        row = {"n": m, "at": r["ts"][:8], "speaker": who, "src": " / ".join(r["source"] or r["timing_lines"])}
        if r.get("en") is not None and r["en"] != r["source"]:
            row["en"] = " / ".join(r["en"])
        out.append(row)
    return out


# --- apply ---------------------------------------------------------------


def apply(work: Path) -> dict:
    data = load_decisions(work)
    cmp = _load(work / "compare.json")
    to_judge = {t["id"]: t for t in cmp["to_judge"]}
    judged_file = work / "judged.json"
    judged = _load_object(judged_file).get("decisions", []) if to_judge or judged_file.exists() else []
    if not isinstance(judged, list):
        raise SystemExit("judged.json needs a decisions list")
    by_id = {d["id"]: d for d in data["decisions"]}
    problems = []
    for j in judged:
        if not isinstance(j, dict) or j.get("id") not in to_judge:
            problems.append(f"judged.json {j.get('id') if isinstance(j, dict) else j}: not a question in compare.json")
            continue
        kind = to_judge[j["id"]]["kind"]
        problems += _check_answer(kind, j.get("answer"), f"judged.json {j['id']}")
        if j.get("answer") is None:
            problems.append(f"judged.json {j['id']}: the judge answers every question")
        if j.get("how") not in ("evidence", "safe default"):
            problems.append(f"judged.json {j['id']}: how must be 'evidence' or 'safe default'")
        if not isinstance(j.get("evidence"), list) or not all(isinstance(n, int) for n in j.get("evidence", [None])):
            problems.append(f"judged.json {j['id']}: evidence is a list of cue numbers")
    missing = sorted(set(to_judge) - {j.get("id") for j in judged if isinstance(j, dict)})
    if missing:
        problems.append(f"judged.json has no answer for: {', '.join(missing)}")
    if problems:
        raise SystemExit("judged.json has problems:\n" + "\n".join(problems[:20]))

    writer_copy = work / "decisions.writer.json"
    if not writer_copy.exists():
        writer_copy.write_text((work / "decisions.json").read_text(encoding="utf-8"), encoding="utf-8")

    rows = {r["n"]: r for r in _load(work / "cues.json")}
    changed, added, ties = [], [], []
    for j in judged:
        conf = "sure" if j["how"] == "evidence" else "tie"
        t = to_judge[j["id"]]
        if j["id"] in by_id:
            d = by_id[j["id"]]
            if not agree(d["kind"], d["answer"], j["answer"]):
                changed.append(j["id"])
            d.update(answer=j["answer"], evidence=j["evidence"], confidence=conf)
        else:
            d = {k: t[k] for k in QUESTION_FIELDS if k in t}
            d.update(answer=j["answer"], evidence=j["evidence"], confidence=conf)
            data["decisions"].append(d)
            by_id[d["id"]] = d
            added.append(j["id"])
        if conf == "tie":
            at = [{"n": n, "at": rows[n]["ts"][:8]} for n in j["evidence"][:3] if n in rows]
            ties.append({"id": j["id"], "question": t["question"], "answer": j["answer"], "cues": at})
    (work / "decisions.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"agreed": len(cmp["agreed"]), "judged": len(judged), "changed": changed, "added": added, "ties": ties}


# --- voices added after the bible ---------------------------------------

VOICE_ID_RE = re.compile(r"^voice:V\d+$")


def _load_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"{path.name} is missing in {path.parent}")
    return path.read_text(encoding="utf-8")


def _without_section(lines: list[str], title: str) -> list[str]:
    out, skip = [], False
    for line in lines:
        if line.startswith("## "):
            skip = line[3:].strip().startswith(title)
        if not skip:
            out.append(line)
    return out


def add_voices(work: Path) -> dict:
    """Put the voice mapper's answers (W/voices.json) into decisions.json and
    bible.md. Voice decisions already there are replaced, so it can run twice."""
    data = load_decisions(work)
    vo = _load_object(work / "voices.json")
    lines, new = vo.get("lines"), vo.get("decisions")
    problems = []
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        problems.append("voices.json: lines is a list of strings")
    if not isinstance(new, list):
        raise SystemExit("voices.json needs a decisions list")
    ids = set()
    for d in new:
        problems += check_decision(d, "voices.json")
        if not isinstance(d, dict) or not isinstance(d.get("id"), str):
            continue  # check_decision already named the problem
        if d.get("kind") != "voice" or not VOICE_ID_RE.match(str(d.get("id"))):
            problems.append(f"voices.json {d.get('id')}: only voice decisions, with ids like voice:V3")
        problems += _check_answer("voice", d.get("answer"), f"voices.json {d.get('id')}")
        if d.get("answer") is None:
            problems.append(f"voices.json {d.get('id')}: every voice question needs an answer")
        if d.get("id") in ids:
            problems.append(f"voices.json: id {d.get('id')} is used twice")
        ids.add(d.get("id"))
    if problems:
        raise SystemExit("voices.json has problems:\n" + "\n".join(problems[:20]))
    bible_file = work / "bible.md"
    text = _without_section(_load_text(bible_file).splitlines(), "Voices")
    kept = [d for d in data["decisions"] if d.get("kind") != "voice"]
    replaced = len(data["decisions"]) - len(kept)
    data["decisions"] = kept + new
    (work / "decisions.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # The Voices section goes right after Characters, as the bible brief orders it.
    section = ["## Voices", *[x if x.startswith("- ") else f"- {x}" for x in lines]] if lines else []
    chars = next((i for i, x in enumerate(text) if x.startswith("## Characters")), None)
    if chars is None:
        at = len(text)
    else:
        at = next((i for i in range(chars + 1, len(text)) if text[i].startswith("## ")), len(text))
    text[at:at] = section
    bible_file.write_text("\n".join(text) + "\n", encoding="utf-8")
    return {"voices": len(new), "replaced": replaced, "bible_lines": len(lines)}


# --- address forms in the Turkish text ------------------------------------

SIZ_RE = re.compile(r"\b(siz|sizi|size|sizin|sizde|sizden|sizinle|sizce)\b|\w(sınız|siniz|sunuz|sünüz)\b")
SEN_RE = re.compile(
    r"\b(sen|seni|sana|senin|sende|senden|seninle|sence|mısın|misin|musun|müsün)\b"
    r"|\w(yorsun|acaksın|eceksin|malısın|melisin)\b"
)


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def detect_form(text: str) -> str | None:
    """sen or siz when the Turkish text uses only one of them, else None.
    Plain imperatives and most verb endings are left out: they are too easy
    to mistake for other words."""
    low = tr_lower(text)
    has_siz, has_sen = bool(SIZ_RE.search(low)), bool(SEN_RE.search(low))
    if has_siz == has_sen:
        return None
    return "siz" if has_siz else "sen"


class AddressBook:
    """Who speaks a cue, to whom, and the form the bible expects."""

    def __init__(self, data: dict):
        self.alias: dict[str, str] = {}
        for c in data.get("characters", []):
            name = c.get("name")
            if not isinstance(name, str):
                continue
            for a in [name, *c.get("aliases", [])]:
                if isinstance(a, str) and len(a.strip()) >= 3:
                    self.alias[a.strip().casefold()] = name
        self.voice: dict[str, str] = {}
        self.address: dict[tuple[str, str], list[dict]] = {}
        for d in data.get("decisions", []):
            if d.get("kind") == "voice" and isinstance(d.get("answer"), str) and d["id"].startswith("voice:"):
                self.voice[d["id"].split(":", 1)[1]] = self.name(d["answer"]) or d["answer"]
            elif d.get("kind") == "address" and isinstance(d.get("answer"), list):
                # A listener need not be a listed character ("the jury"):
                # keep its own name so the speaker's other forms still count.
                sp = self.name(d["speaker"]) or d["speaker"].strip()
                li = self.name(d["listener"]) or d["listener"].strip()
                self.address[(sp, li)] = d["answer"]
        self._mention = [(re.compile(r"\b" + re.escape(a) + r"\b"), n) for a, n in self.alias.items()]

    def name(self, s: str | None) -> str | None:
        return self.alias.get(s.strip().casefold()) if isinstance(s, str) else None

    def speaker(self, entry: dict) -> str | None:
        label = entry.get("name") or entry.get("label")
        if isinstance(label, str) and "/" in label:
            return None  # two speakers in one cue
        return self.name(label) or self.voice.get(entry.get("voice") or "")

    def listener(self, speaker: str, text: str) -> str | None:
        low = text.casefold()
        named = {n for rx, n in self._mention if n != speaker and rx.search(low)}
        return named.pop() if len(named) == 1 else None

    def expected(self, speaker: str, listener: str | None, n: int) -> str | None:
        if listener is not None:
            steps = self.address.get((speaker, listener))
            return form_at(steps, n) if steps else None
        forms = {form_at(steps, n) for (sp, _), steps in self.address.items() if sp == speaker}
        return forms.pop() if len(forms) == 1 else None


def address_warnings(work: Path, texts: dict[int, list[str]], rows: dict[int, dict]) -> list[dict]:
    """Cues whose Turkish uses the other form than the bible gives for that
    speaker. With no listener named in the line, only sen where the bible
    says siz is flagged, since siz is also the plural you."""
    if not (work / "decisions.json").exists():
        return []
    try:
        data = load_decisions(work)
    except SystemExit:
        # The bible check reports a broken file; the Turkish checks go on
        # without address warnings rather than stop the film.
        return []
    book = AddressBook(data)
    if not book.address:
        return []
    speakers_file = work / "speakers.json"
    speakers = json.loads(speakers_file.read_text(encoding="utf-8")) if speakers_file.exists() else {}
    out = []
    for n, tr in sorted(texts.items()):
        row = rows.get(n)
        sp = book.speaker(speakers.get(str(n), {}))
        if row is None or sp is None:
            continue
        said = " ".join(row.get("en") or row.get("source") or row.get("timing_lines") or [])
        said += " " + " ".join(row.get("source") or [])
        li = book.listener(sp, said)
        exp = book.expected(sp, li, n)
        got = detect_form(" ".join(tr))
        if exp is None or got is None or exp == got:
            continue
        if li is None and got == "siz":
            continue
        out.append(
            {"cue": n, "check": "address form", "detail": f"{sp} → {li or 'anyone here'}: bible says {exp}, Turkish uses {got}"}
        )
    return out


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("questions", "compare", "apply", "voices"):
        sub.add_parser(name).add_argument("--work", type=Path, required=True)
    c = sub.add_parser("cues")
    c.add_argument("--work", type=Path, required=True)
    c.add_argument("--cues", required=True, help="comma-separated cue numbers")
    c.add_argument("--context", type=int, default=2)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd == "questions":
        result.emit(questions(a.work), a.result)
    elif a.cmd == "compare":
        result.emit(compare(a.work), a.result)
    elif a.cmd == "cues":
        try:
            numbers = [int(x) for x in a.cues.split(",") if x.strip()]
        except ValueError as e:
            raise SystemExit("--cues takes cue numbers separated by commas") from e
        result.emit(cues(a.work, numbers, a.context), a.result)
    elif a.cmd == "voices":
        result.emit(add_voices(a.work), a.result)
    else:
        result.emit(apply(a.work), a.result)


if __name__ == "__main__":
    main()
