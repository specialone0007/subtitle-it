# Turkish Subtitles

A Claude Code plugin that turns a film's subtitles, in any language, into
natural Turkish subtitles on the source file's own timings.

```
/turkish-subtitles:subtitle Anatomy of a Fall
```

(Plain `/subtitle` also works when no other command uses that name.)

It finds the film, finds source subtitles (a track inside the video, a file
next to it, or OpenSubtitles), builds a short "film bible" (characters, who
says sen or siz to whom, fixed terms), asks you to check it, translates the
film in parallel chunks, runs automatic checks, has one reviewer read the
whole film, and saves `Anatomy of a Fall.tr.srt` next to the video.

## Setup

1. **uv** (runs the scripts and installs their packages on first use):
   - Windows: `winget install astral-sh.uv`
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **ffmpeg and ffprobe** on PATH (reads subtitle tracks inside videos):
   - Windows: `winget install Gyan.FFmpeg`
   - macOS: `brew install ffmpeg` · Debian/Ubuntu: `sudo apt install ffmpeg`
3. **OpenSubtitles** (optional, for films without subtitles on disk). Create a free API key at
   <https://www.opensubtitles.com/consumers> and a free account, then run this in your own terminal
   (it asks for the key and login without showing them):

   ```
   uv run scripts/opensubtitles.py setup --config ~/.config/turkish-subtitles
   ```

   A key alone allows 5 downloads a day; with the free account login, 20. Downloads are cached.
4. **Audio hints** (optional: tells the translators which voice speaks each line). Create a free
   read token at <https://huggingface.co/settings/tokens>, accept the terms of
   <https://huggingface.co/pyannote/speaker-diarization-3.1> and
   <https://huggingface.co/pyannote/segmentation-3.0> with the same account, then run this in your
   own terminal (it asks for the token without showing it):

   ```
   uv run scripts/speakers.py setup --config ~/.config/turkish-subtitles
   ```

   The first run downloads a few GB (PyTorch, pyannote and a Whisper model). With an NVIDIA GPU it
   takes a few minutes per film; on the CPU about as long as the film. It also reports when the
   subtitles are out of sync with the audio.
5. **Install the plugin.** From a clone of this repo:

   ```
   claude plugin marketplace add ./turkish-subtitles
   claude plugin install turkish-subtitles@turkish-subtitles
   ```

   Or for one session only: `claude --plugin-dir ./turkish-subtitles`.

## Where files go

- `~/.config/turkish-subtitles/` (on Windows `C:\Users\<you>\.config\turkish-subtitles\`):
  `preferences.md` (media folders, translator model, audio hints, swearing, titles, learned rules),
  `credentials.json` (OpenSubtitles and Hugging Face; only the scripts read it), `backups/` (old Turkish
  files replaced by a new one). Kept when the plugin is uninstalled.
- The plugin's data folder (`~/.claude/plugins/data/turkish-subtitles-.../`): one work
  folder per film with the bible, the delivered copy and a report, plus the download
  cache. **Uninstalling the plugin deletes it.**
- Next to the video: `<film>.tr.srt`. Nothing else is written into your film folders.

## Learning from your fixes

After watching, fix lines in the `.tr.srt` with any editor, then run
`/turkish-subtitles:subtitle learn Anatomy of a Fall`. The skill proposes
general rules from your edits ("Always use 'Tamam' for 'OK'?") and saves
only the ones you accept. Each new run also checks for edited files.

## Development

```
uv run --group dev pytest
uv run --group dev ruff check .
```

Layout:

```
.claude-plugin/plugin.json      plugin manifest
.claude-plugin/marketplace.json local marketplace for testing
skills/subtitle/SKILL.md        the run (steps 0-11) and learn mode
skills/subtitle/pack-tr.md      Turkish language rules
skills/subtitle/briefs/         bible, translator and reviewer instructions
scripts/srt.py                  parse, encodings, pairing by time, chunking
scripts/sources.py              find films, extract tracks, validate sources
scripts/opensubtitles.py        OpenSubtitles login, search, download
scripts/prepare.py              build the work folder and chunks
scripts/assemble.py             assemble, checks, review file, delivery
scripts/learn.py                find user edits for learn mode
scripts/speakers.py             voices per cue from the audio, sync check
scripts/result.py               print each script's JSON result and save it to --result
tests/                          pytest suite
```

## License

Copyright 2026 Furkan Reha

Apache-2.0: the Apache License, version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).
