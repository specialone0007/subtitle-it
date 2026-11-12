---
name: learn
description: Turn the user's own fixes in a delivered Turkish subtitle (.tr.srt) into rules that later translate runs follow. Use when the user runs "/subtitle-it:learn <film>", or says they fixed lines in a subtitle this plugin delivered and want it to learn from them.
argument-hint: "<film name>"
---

# Learn from your fixes

You run this in the user's conversation, with no subagents. Unlike a
translate run, this skill asks: it proposes rules and saves only the ones
the user says yes to. The user has watched the film, but keep quotes to the
edited lines you propose rules from.

## Fixed paths

- Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts` (SCRIPTS below)
- Shared files: `${CLAUDE_PLUGIN_ROOT}/skills/translate` (SHARED below): the language pack `pack-tr.md` and `preferences-template.md`. They belong to the translate skill; read them there.
- Data: `${CLAUDE_PLUGIN_DATA}`; each film's work folder is `${CLAUDE_PLUGIN_DATA}/films/<slug>` (WORK below)
- User config: `~/.config/subtitle-it`, or the `folder` step 1 gives (CONFIG below; the scripts expand the `~` themselves)

Run every script as
`uv run 'SCRIPTS/<name>.py' --result '${CLAUDE_PLUGIN_DATA}/results/<name>-<command>.json' <command> ...`
and read that file for the result, not what the command prints. Write
every path and film title in full inside single quotes; a single quote
inside one becomes `'\''` (close the quote, add an escaped quote, open it
again): `'Ali'\''nin filmi'`. Never read, print or edit
`CONFIG/credentials.json`.

Arguments: $ARGUMENTS

## Steps

1. Run `uv --version && uv run 'SCRIPTS/settings.py' --result '${CLAUDE_PLUGIN_DATA}/results/settings-folder.json' folder`. If uv is missing, point the user to the README's Quick start section and stop. CONFIG is the result's `folder`. When `moved_from` is set, the settings folder from before the plugin was renamed was moved into place: say so in one line. When `error` is set, say it in one line and go on.
2. If `CONFIG/preferences.md` does not exist, copy `SHARED/preferences-template.md` there and tell the user in one line. Read `CONFIG/preferences.md` and `SHARED/pack-tr.md`.
3. Find WORK for the film: `sources.py slug '<film title>'` gives the slug. With no film in the arguments, or no work folder for that slug, run `learn.py scan --data '${CLAUDE_PLUGIN_DATA}'`: it lists each delivered file the user edited (`file`) with its work folder (`work`). Take the one for the film the user named. When they named none, or the film they named is not in the list, say so in one line, list the files and ask which one. None listed: say there is nothing to learn yet and stop.
4. Run `learn.py diff --work 'WORK'`. From `repeated_swaps` and the edits, propose at most 5 general rules (each edit's `cue` is its number in the delivered file, `timing_cue` the work folder's number for it), each with its count and one example, for instance: "You changed 'Peki' to 'Tamam' in 6 places. Always use 'Tamam' for 'OK'?" Skip one-off fixes, rules already in the preferences, and rules the language pack already sets.
5. Add to "Learned rules" in `CONFIG/preferences.md` only the ones the user says yes to.
6. Run `learn.py done --work 'WORK'` so the same edits are not proposed again.
