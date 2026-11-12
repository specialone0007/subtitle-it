"""The subagent types in agents/: each one the skill names exists, and each
keeps to a short tool list without the general Claude Code instructions."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
SKILL = ROOT / "skills" / "translate" / "SKILL.md"
LEARN = ROOT / "skills" / "learn" / "SKILL.md"
ALLOWED_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.name} has no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


def test_every_agent_named_in_the_skill_exists():
    named = set(re.findall(r"`subtitle-it:([a-z-]+)`", SKILL.read_text(encoding="utf-8")))
    files = {p.stem for p in AGENTS.glob("*.md")}
    assert named == files


def test_agents_keep_a_short_tool_list_and_skip_claude_md():
    for path in AGENTS.glob("*.md"):
        fm = frontmatter(path)
        assert fm["name"] == path.stem
        assert fm["omitClaudeMd"] == "true"
        assert fm["model"] == "inherit"
        tools = {t.strip() for t in fm["tools"].split(",")}
        assert tools <= ALLOWED_TOOLS, f"{path.name}: {tools - ALLOWED_TOOLS}"


def test_only_the_translator_sets_its_own_effort():
    # The translators (and the fix rounds, which use the same agent) run at
    # low effort; every other agent takes the session's effort.
    efforts = {p.stem: fm["effort"] for p in AGENTS.glob("*.md") if "effort" in (fm := frontmatter(p))}
    assert efforts == {"translator": "low"}


def test_only_the_judge_runs_commands():
    with_bash = {p.stem for p in AGENTS.glob("*.md") if "Bash" in frontmatter(p)["tools"]}
    assert with_bash == {"bible-judge"}


def test_the_judge_is_told_to_print_utf8():
    text = (AGENTS / "bible-judge.md").read_text(encoding="utf-8")
    assert "PYTHONIOENCODING=utf-8" in text


def test_a_fix_round_never_gets_the_chunk_output_path():
    text = SKILL.read_text(encoding="utf-8")
    bullet = next(line for line in text.splitlines() if line.startswith("- Hard fails:"))
    assert "fix_r<round>_<NN>.txt" in bullet
    assert "flags_r<round>_<NN>.txt" in bullet
    assert "never its two `Write` lines" in bullet


def test_files_the_skill_sends_you_to_exist():
    text = SKILL.read_text(encoding="utf-8")
    named = set(re.findall(r"\$\{CLAUDE_SKILL_DIR\}/([\w.-]+\.md)", text))
    named |= set(re.findall(r"`([a-z]+\.md)`", text)) - {"SKILL.md", "bible.md", "report.md", "review.md", "preferences.md"}
    assert {"setup.md", "pack-tr.md", "preferences-template.md"} <= named
    for name in named:
        assert (SKILL.parent / name).exists(), name
    setup = (SKILL.parent / "setup.md").read_text(encoding="utf-8")
    headings = re.findall(r'see "([^"]+)" in', text)
    assert "see `setup.md`" not in text, "name the setup.md section a pointer sends you to"
    assert set(headings) == set(re.findall(r"^## (.+)$", setup, re.M))
    for heading in headings:
        assert f"## {heading}" in setup, heading


def test_learn_reads_the_shared_files_from_the_translate_skill():
    text = LEARN.read_text(encoding="utf-8")
    assert frontmatter(LEARN)["name"] == "learn"
    assert frontmatter(SKILL)["name"] == "translate"
    assert "`${CLAUDE_PLUGIN_ROOT}/skills/translate`" in text
    for name in re.findall(r"`SHARED/([\w.-]+\.md)`", text):
        assert (SKILL.parent / name).exists(), name
    assert sorted(p.name for p in LEARN.parent.iterdir()) == ["SKILL.md"], "learn keeps no copies of shared files"


def test_translate_points_to_the_learn_command_by_its_full_name():
    assert "`/subtitle-it:learn <film>`" in SKILL.read_text(encoding="utf-8")
    assert "learn" not in frontmatter(SKILL)["argument-hint"]
