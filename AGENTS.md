# Subtitle It - for agents

> **This document owns:** the commands, the conventions an agent cannot
> infer from the code, and the gotchas.

## Commands

- test: `uv run --group dev pytest`
- lint: `uv run --group dev ruff check .`
- format (check): `uv run --group dev ruff format --check .`
- try the plugin from this clone: `claude --plugin-dir .`
- preview release notes: `python .github/scripts/release_notes.py <version>`

## Conventions

- **Never name a film.** Not in a doc, the changelog, a code comment, a
  test name, fixture text, a commit message, a PR title or body, or
  release notes. Say "one 2026 film" or "one test film" and keep the
  measurement. Examples use invented titles such as "Harbour Lights".
- **Never borrow from a film either.** Example and fixture text uses
  invented people and invented lines: no real film's character names,
  quoted dialogue, song words or telling plot details.
- Download figures are totals only: no film, no site, no uploader name.
- Anything with one right answer is a script in `scripts/`, with a test.
  Language work is an agent in `agents/` or a skill in `skills/`.
- Every script prints a JSON result and saves it with `--result <file>`.
- Never commit subtitles, video or credentials.
- Docs: no paragraph over three sentences, thresholds in tables, and each
  number in one doc only. [CONTRIBUTING.md](CONTRIBUTING.md) has the rest.

## Gotchas

- Claude Code loads plugins when a session starts. A session that is
  already open does not see a change to the plugin.
- A release bumps the version in four places, and CI checks they match.
  [CONTRIBUTING.md](CONTRIBUTING.md) lists them.
- `tests/test_no_film_names.py` fails on a title followed by its year in
  brackets, in any Markdown file or code comment.

## Docs

- [docs/INDEX.md](docs/INDEX.md) - the map; read it before the folder.
