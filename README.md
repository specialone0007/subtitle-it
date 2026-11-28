# Subtitle It

![Title card: Subtitle It, a Claude Code plugin that turns a film's subtitles into natural Turkish](docs/assets/title-card.svg)

<p align="center">
  <b>Name a film. Get Turkish subtitles that sound like people talking.</b>
</p>

<p align="center">
  <a href="https://github.com/specialone0007/subtitle-it/actions/workflows/ci.yml"><img src="https://github.com/specialone0007/subtitle-it/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="https://github.com/specialone0007/subtitle-it/releases/latest"><img src="https://img.shields.io/github/v/release/specialone0007/subtitle-it" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/specialone0007/subtitle-it" alt="License: Apache-2.0"></a>
</p>

<p align="center">
  <a href="#quick-start"><img src="docs/assets/btn-quick-start.svg" alt="Quick start" width="190"></a>
  <a href="docs/reference/ARCHITECTURE.md"><img src="docs/assets/btn-architecture.svg" alt="Architecture: how a run works" width="190"></a>
  <a href="docs/INDEX.md"><img src="docs/assets/btn-docs.svg" alt="All docs" width="190"></a>
  <a href="CHANGELOG.md"><img src="docs/assets/btn-changelog.svg" alt="Changelog" width="190"></a>
</p>

A Claude Code plugin that reads a film's subtitles in any language and
writes natural Turkish ones. You type one command:

```
/subtitle-it:translate Harbour Lights
```

When the run ends, `Harbour Lights.srt` sits next to
`Harbour Lights.mkv`, under exactly the video's name.

![Same line, two translations. The English line "Well... you're coming, right?" becomes "Kuyu... geliyorsun, sağ?" word for word, and "Şey... geliyorsun, değil mi?" with the plugin](docs/assets/scene.svg)

## What you get

![Eight film frames: natural Turkish, one voice for the whole film, two short lines cue for cue with the source, signs and title cards, no questions and no spoilers, an honest report with timestamps, it learns from the lines you fix, and your film stays on your machine](docs/assets/features.svg)

After watching, fix lines in the file and run
`/subtitle-it:learn Harbour Lights`. Fixes you repeat become rules.

## The numbers

![A run, by the numbers: about 32 minutes, about 12 dollars at API list prices on Opus (from 9 of the runs), about 1,600 cues, 0 questions asked. Measured over 38 runs of 28 films in November 2026, on Windows](docs/assets/ticket.svg)

![Box office: 2,748 downloads of subtitles made with the plugin, across 23 films on 6 subtitle sites, counted on 27 November 2026](docs/assets/box-office.svg)

On a Claude subscription a run uses your plan's usage, not dollars.
[Numbers](docs/reference/NUMBERS.md) has every figure and how it was
measured.

## Quick start

1. **Install the plugin** in your shell:

   ```
   claude plugin marketplace add specialone0007/subtitle-it
   claude plugin install subtitle-it@subtitle-it
   ```

2. **Install uv and ffmpeg:**

   | System | Commands |
   | --- | --- |
   | Windows | `winget install astral-sh.uv` and `winget install Gyan.FFmpeg` |
   | macOS | `curl -LsSf https://astral.sh/uv/install.sh \| sh` and `brew install ffmpeg` |
   | Debian, Ubuntu | `curl -LsSf https://astral.sh/uv/install.sh \| sh` and `sudo apt install ffmpeg` |

3. **Run it.** Start a new Claude Code session and type
   `/subtitle-it:translate <film>`.

[Setup](docs/getting-started/SETUP.md) has the optional extras and what
to do when a step fails.

## How a run goes

![How a run goes: find the film, get subtitles, audio hints, film bible, translate, check, review, listen, deliver](docs/assets/run-strip.svg)

Thirteen steps, numbered 0 to 12, in four acts. Before a line is
translated, the run writes the film's bible:

![A page of a film bible for an invented film, Harbour Lights: who says sen or siz to whom, one Turkish word for each term, and a second reader who checks it without seeing the answers](docs/assets/film-bible.svg)

![The cast: the scripts are plain Python, the local models listen to the audio on your machine, and Claude does the language work as nine kinds of agent](docs/assets/cast.svg)

When a human-made Turkish subtitle already exists, the run polishes that
file instead of translating from scratch.

## What leaves your machine

![The video, the audio and your credentials file stay on your machine. Subtitle text and a capped number of still frames go to Claude, in your own session. Your film folder gets one new file, the subtitle](docs/assets/stays-home.svg)

[Files and privacy](docs/reference/PRIVACY.md) lists everything that is
sent, to whom, and when.

## Start here

1. **[Setup](docs/getting-started/SETUP.md)** - your first film.
2. **[How a run works](docs/reference/ARCHITECTURE.md)** - every step on
   one page.
3. **[All docs](docs/INDEX.md)** - the index of every page.
4. **[AGENTS.md](AGENTS.md)** - for contributors and coding agents.

## The small print

<details>
<summary><b>What it needs</b></summary>

- **[Claude Code](https://code.claude.com/docs),** on a plan with room
  for a run.
- **uv and ffmpeg,** from the quick start.
- **Subtitles in a text format:** SRT, ASS, WebVTT or a text track inside
  the video. Image subtitles (PGS, VobSub) are not read. With no subtitle
  anywhere, it writes one from the audio.
- **Windows, macOS or Linux.** Full runs have only been tested on
  Windows. On macOS and Linux, CI runs the test suite, and a full run is
  untested.

It translates from any language, into Turkish only. You are responsible
for having the right to use the films and subtitles you run it on.

</details>

<details>
<summary><b>Working on the plugin</b></summary>

| Folder | What is there |
| --- | --- |
| `skills/` | The two commands, `translate` and `learn`, and the Turkish language rules |
| `agents/` | The nine agent types: their instructions and allowed tools |
| `scripts/` | The Python scripts, one job each |
| `tests/` | The pytest suite |
| `docs/` | The docs and the pictures |

Load the plugin from a clone with `claude --plugin-dir .`.
[CONTRIBUTING.md](CONTRIBUTING.md) has the checks and how to send a
change. [SECURITY.md](SECURITY.md) covers credentials and how to report
a problem.

</details>

## License

Apache-2.0, copyright 2026 Furkan Reha. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).

<details>
<summary><b>Third-party parts</b></summary>

The plugin bundles no third-party code or models; the scripts download
what they need when they first run.

- The pyannote speaker models are gated on Hugging Face and come under
  their own terms, which you accept there with your own account.
- Whisper and faster-whisper, used for speech-to-text, are MIT-licensed.
- ffmpeg is not bundled; you install it yourself.

</details>

## Credits

<p align="center">
  <a href="https://www.linkedin.com/in/furkanreha/"><img src="docs/assets/credits.svg" alt="Credits. Written and directed by Furkan Reha. Starring Claude, pyannote, Whisper, ffmpeg and uv. Subtitles from your own disk, or OpenSubtitles under your own account. No films were spoiled in the making of these subtitles."></a>
</p>

<p align="center">
  <a href="https://www.linkedin.com/in/furkanreha/"><img src="docs/assets/btn-linkedin.svg" alt="Furkan Reha on LinkedIn" width="300"></a>
</p>
