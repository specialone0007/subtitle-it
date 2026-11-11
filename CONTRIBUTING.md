# Contributing

Issues and pull requests are welcome.

## Set up

You need [uv](https://docs.astral.sh/uv/). The scripts declare their own
packages at the top of each file, so there is nothing else to install.

```
uv run --group dev pytest
uv run --group dev ruff check .
uv run --group dev ruff format --check .
```

To try a change in Claude Code, start a session with
`claude --plugin-dir .` from the repository folder.

## How the work is split

Scripts in `scripts/` do the exact work: parsing, timing, pairing, checks
and delivery. Each one prints a JSON result and, with `--result <file>`,
saves it. Language work stays with Claude: the skill in `skills/subtitle/`
and the briefs its subagents read. [docs/architecture.md](docs/architecture.md)
walks through a run.

## Pull requests

- One change per pull request, with tests for new behaviour.
- Commit messages follow `type(scope): subject`, for example
  `fix(srt): keep italics across line breaks`.
- Never commit subtitles, video or credentials. `.gitignore` blocks the
  common file types.
