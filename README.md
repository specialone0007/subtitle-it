# Turkish Subtitles

A Claude Code plugin that turns a film's subtitles, in any language, into
natural Turkish subtitles on the source file's own timings.

```
/turkish-subtitles:subtitle Anatomy of a Fall
```

(Plain `/subtitle` also works when no other command uses that name.)

It finds the film, finds source subtitles (a track inside the video, a file
next to it, or OpenSubtitles; as a last resort, it transcribes the film's
own speech), builds a short "film bible" (characters, who
says sen or siz to whom, fixed terms), has a second reader check it blind
and a judge settle any difference, translates the film in parallel chunks,
runs automatic checks, has one reviewer read the whole film, and saves
`Anatomy of a Fall.tr.srt` next to the video.

It does not stop to ask you anything once setup is done, except which
film you mean when the name matches several different films (Alien and
Aliens), and it does not spoil the film in chat. What it could not settle
for certain goes under "Check after watching" in the film's `report.md`.

[How a run works](docs/architecture.md) walks through each step.

## What it needs

- [Claude Code](https://code.claude.com/docs). A feature film takes about
  one million new tokens plus about eight million cheaper cached reads. The
  parallel translators use the largest share, about two fifths, so a plan
  with room for that helps. Polishing an existing Turkish file uses less.
- uv and ffmpeg (Setup below). OpenSubtitles and audio hints are optional.
- Subtitles in a text format (SRT, ASS, WebVTT, or a text track inside the
  video). Image subtitles (PGS, VobSub) are not read.

## Setup

1. **Install the plugin** in your shell:

   ```
   claude plugin marketplace add specialone0007/turkish-subtitles
   claude plugin install turkish-subtitles@turkish-subtitles
   ```

   Claude Code loads plugins when a session starts, so start a new session after
   installing; a session that is already open does not see the plugin.
2. **uv** (runs the scripts and installs their packages on first use):
   - Windows: `winget install astral-sh.uv`
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. **ffmpeg and ffprobe** on PATH (reads subtitle tracks inside videos):
   - Windows: `winget install Gyan.FFmpeg`
   - macOS: `brew install ffmpeg` · Debian/Ubuntu: `sudo apt install ffmpeg`
4. **OpenSubtitles** (optional, for films without subtitles on disk). Create a free API key at
   <https://www.opensubtitles.com/consumers> and a free account. The first time a film needs it,
   the plugin prints a setup command with the full path to run in your own terminal; it asks for
   the key and login without showing them. From a clone of this repo the command is:

   ```
   uv run scripts/opensubtitles.py setup --config ~/.config/turkish-subtitles
   ```

   A key alone allows 5 downloads a day; with the free account login, 20. Downloads are cached.
5. **Audio hints** (optional: tells the translators which voice speaks each line). Create a free
   read token at <https://huggingface.co/settings/tokens>, accept the terms of
   <https://huggingface.co/pyannote/speaker-diarization-3.1> and
   <https://huggingface.co/pyannote/segmentation-3.0> with the same account, then run the setup
   command in your own terminal (the plugin prints it with the full path; it asks for the token
   without showing it):

   ```
   uv run scripts/speakers.py setup --config ~/.config/turkish-subtitles
   ```

   The first run downloads a few GB (PyTorch, pyannote and a Whisper model). With an NVIDIA GPU it
   takes a few minutes per film; on the CPU about as long as the film. When the subtitles are
   out of sync with the audio, it moves them to match and says so in the report.

   Speech-to-text, the last resort when no subtitle file exists anywhere, needs no setup and no
   token. Its first use downloads a few GB: PyTorch, unless the audio hints already did, plus a
   Whisper model of about 1.6 GB. With an NVIDIA GPU a film takes a few minutes, on the CPU about as
   long as the film or more.
To work on the plugin itself, load it from a clone for one session with
`claude --plugin-dir ./turkish-subtitles`.

## Where files go

- `~/.config/turkish-subtitles/` (on Windows `C:\Users\<you>\.config\turkish-subtitles\`):
  `preferences.md` (media folders, translator model, audio hints, swearing, titles, learned rules),
  `credentials.json` (OpenSubtitles and Hugging Face; only the scripts read it), `backups/` (old Turkish
  files replaced by a new one). Kept when the plugin is uninstalled.
- The plugin's data folder (`~/.claude/plugins/data/turkish-subtitles-.../`): one work
  folder per film with the bible, the delivered copy and a report, plus the download
  cache and `results/`, where each script saves its last JSON result. The skill reads
  those files rather than the scripts' printed output, so tools that shorten
  command output do not get in the way. **Uninstalling the plugin deletes it.**
- Next to the video: `<film>.tr.srt`. Nothing else is written into your film folders.

## What leaves your machine

Subtitle text goes to Claude as part of your Claude Code session.
OpenSubtitles receives the video's hash, title or IMDb id when it searches.
Audio hints and speech-to-text run locally and send no audio anywhere; the
speech model is downloaded once from Hugging Face, with no token. Credentials are typed
into your own terminal, never into the chat, and kept in `credentials.json`;
the OpenSubtitles key and login go only to OpenSubtitles, and the Hugging
Face token only to Hugging Face.
[SECURITY.md](SECURITY.md) has the details and how to report a problem.

## Learning from your fixes

After watching, fix lines in the `.tr.srt` with any editor, then run
`/turkish-subtitles:subtitle learn Anatomy of a Fall`. The skill proposes
general rules from your edits ("Always use 'Tamam' for 'OK'?") and saves
only the ones you accept. Each new run also checks for edited files.

## Development

```
uv run --group dev pytest
uv run --group dev ruff check .
uv run --group dev ruff format --check .
```

CI runs the same three commands on Linux and Windows. See
[CONTRIBUTING.md](CONTRIBUTING.md) to send a change, and
[CHANGELOG.md](CHANGELOG.md) for what changed in each version.

Layout:

```
.claude-plugin/plugin.json      plugin manifest
.claude-plugin/marketplace.json marketplace that lists the plugin
skills/subtitle/SKILL.md        the run (steps 0-11)
skills/subtitle/setup.md        one-time setup, read only when a step needs it
skills/subtitle/learn.md        learn mode
skills/subtitle/pack-tr.md      Turkish language rules
agents/                         subagent types: bible writer, second reader, judge, voice mapper,
                                translator, polish fixer, reviewer (instructions and allowed tools)
scripts/srt.py                  parse, encodings, pairing by time, chunking
scripts/sources.py              find films, extract tracks, validate sources
scripts/opensubtitles.py        OpenSubtitles login, search, download
scripts/prepare.py              build the work folder and chunks
scripts/bible.py                questions, blind comparison and judging for the film bible; adds the voices
scripts/polish.py               start from an existing Turkish subtitle: seed it, list cues to fix
scripts/assemble.py             assemble, checks, review file, delivery
scripts/learn.py                find user edits for learn mode
scripts/speakers.py             voices per cue from the audio, sync check
scripts/transcribe.py           subtitles from the audio when no file exists, the last resort
scripts/result.py               print each script's JSON result and save it to --result
tests/                          pytest suite
docs/architecture.md            how a run works
```

## License

Copyright 2026 Furkan Reha

Apache-2.0: the Apache License, version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).
