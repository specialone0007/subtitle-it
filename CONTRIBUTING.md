# Contributing

Issues and pull requests are welcome.

A good bug report gives the plugin version, your system, the command you
ran, what happened, and the part of the film's `report.md` about it. Never
attach videos, subtitle files you may not share, or credentials. The issue
forms ask for exactly this; security problems go to [SECURITY.md](SECURITY.md).

## Set up

You need [uv](https://docs.astral.sh/uv/). The scripts declare their own
packages at the top of each file, so there is nothing else to install.

```
uv run --group dev pytest
uv run --group dev ruff check .
uv run --group dev ruff format --check .
```

To try a change in Claude Code, start a session from the repository
folder with `claude --plugin-dir .`.

## How the work is split

Scripts in `scripts/` do the exact work: parsing, timing, pairing, checks
and delivery. Each one prints a JSON result and, with `--result <file>`,
saves it. Language work stays with Claude: the two skills in `skills/`
(`translate` and `learn`) and the agent types in `agents/` that the
translate skill's subagents run as. [ARCHITECTURE.md](ARCHITECTURE.md)
walks through a run.

## Pull requests

- One change per pull request, with tests for new behaviour.
- Commit messages follow `type(scope): subject`, for example
  `fix(srt): keep italics across line breaks`.
- Never commit subtitles, video or credentials. `.gitignore` blocks the
  common file types.

## Releases

- A release bumps the version in four places, which CI checks match:
  `.claude-plugin/plugin.json`, `pyproject.toml`, `USER_AGENT` in
  `scripts/opensubtitles.py`, and a new first entry in `CHANGELOG.md`.
- Each changelog entry opens with a paragraph in plain words that a user
  can follow without knowing the code: what changes for them. Technical
  bullets come after it.
- Merging to `main` does the rest: `.github/workflows/release.yml` tags the
  commit `v<version>` and publishes a GitHub release. Its notes are the
  opening paragraph, the bullets folded under "Technical notes", how to
  update, and links to the changelog entry and the changes since the last
  tag. Preview them with `python .github/scripts/release_notes.py <version>`.
