"""The subagent types in agents/: each one the skill names exists, and each
keeps to a short tool list without the general Claude Code instructions."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
SKILL = ROOT / "skills" / "subtitle" / "SKILL.md"
ALLOWED_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.name} has no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


def test_every_agent_named_in_the_skill_exists():
    named = set(re.findall(r"`turkish-subtitles:([a-z-]+)`", SKILL.read_text(encoding="utf-8")))
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
