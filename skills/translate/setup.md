# One-time setup

Read this only when SKILL.md sends you here. SCRIPTS, CONFIG and WORK mean
what they mean there.

## Media folders

- After `sources.py remember`: when its `added` is a folder, say in one
  line that later runs search it too. When its `too_broad` is a folder (a
  drive root or your home folder), say in one line that it was not added
  because searching all of it would be slow, and that a film folder can be
  added under "Media folders" in the preferences.
- No media folders yet for `sources.py find`: ask the user for the folder,
  save it under "Media folders" in `CONFIG/preferences.md`, and go on.

## OpenSubtitles credentials

If `opensubtitles.py` says credentials are missing, give the user the setup
command it printed and stop.

## Hugging Face token

`speakers.py` exit code 3 with `"skipped": "token missing"`: give the user
the `fix` command it printed, to run in their own terminal, and go on
without voices. Never ask for the token in chat.
