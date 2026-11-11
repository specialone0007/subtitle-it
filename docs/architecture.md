# How a run works

The plugin is one skill (`skills/subtitle/SKILL.md`) that Claude follows in
your conversation. The work is split two ways:

- **Scripts** (`scripts/`) do everything that has one right answer:
  reading subtitle files, matching timings, cutting chunks, checking the
  translation and writing the file. They are plain Python, tested, and
  print a JSON result.
- **Subagents** do the language work: the film bible, the second reader,
  the judge, the voice mapper, one translator per chunk (or one polish
  fixer) and one reviewer.
  Each runs as its own agent type from `agents/`: the file holds its
  instructions and the few tools it may use, and leaves out the general
  Claude Code instructions and your CLAUDE.md files, which it does not
  need. The skill passes only the paths. Each one writes its files and
  replies with a short summary.

The main conversation never reads a whole subtitle file. It reads the
scripts' results, the bible and the review, so a full film fits in one
session.

```mermaid
flowchart TD
    A[0. Start: tools, preferences, edited films] --> B[1. Find the film]
    B --> C[2. Source subtitles<br>video track, file next to it, OpenSubtitles, audio]
    C --> D[3. Speaker hints<br>voices and sync check, optional, in the background]
    C --> E[4. Film bible<br>bible.md, glossary.json, decisions.json]
    D --> V[Voice mapper<br>which character each voice is]
    E --> V
    V --> F[5. Check the bible<br>blind second reader, judge on differences]
    F --> G[6-7. Translate<br>one subagent per chunk, in parallel]
    G --> H[8-9. Assemble and check<br>up to 3 fix rounds]
    H --> I[10. Whole-film review]
    I --> J[11. Deliver<br>.tr.srt next to the video, report.md]
```

## The steps

The numbers match the steps in `SKILL.md`.

- **0. Start.** Checks that uv and ffprobe are installed, reads your
  preferences, and mentions any delivered file you have edited since.
- **1. Find the film.** `sources.py find` searches your media folders. Copies
  of one film are picked without asking; different films with a matching
  name (Alien and Aliens) are the one question a run asks. A film given by
  path from a folder not listed yet adds that folder (`sources.py remember`),
  and a listed folder that is not there, such as an unplugged drive, is
  named when nothing is found.
- **2. Source subtitles.** `sources.py local` reads text tracks inside the
  video, files next to it, and files in a `Subs` or `Subtitles` folder
  beside it; `opensubtitles.py` searches by the video's hash, then by IMDb
  id or title. With nothing usable from either, `transcribe.py` writes
  subtitles from the film's own speech with Whisper, the last resort. The
  timing file is the one whose timing is most certain to fit this exact
  video. Other files are paired onto it by time only
  when `srt.py fit` says they line up after one constant shift (it ignores
  sound descriptions and songs); a shifted file is written with
  `srt.py shift` first. Then
  `prepare.py build` writes the work folder: `cues.json` (every cue with
  its source and English text) and `chunks.json` (about 250 cues each, cut
  at the longest pause). The step also looks for a human-made Turkish
  subtitle. When one passes `srt.py fit`, the run is a polish run (see
  steps 6–7).
- **3. Speaker hints** (optional). `speakers.py` finds who speaks each line
  from the audio and checks the subtitles are in sync with it, from five
  3-minute stretches spread over the film. Subtitles
  more than 300 ms off are shifted with `srt.py shift` and the voices are
  matched again. Everything runs on your machine. It runs in the
  background while the bible is written, since it takes several minutes.
- **4. Film bible.** A subagent writes `bible.md` (characters, who says sen or
  siz to whom, fixed terms), `glossary.json`, and `decisions.json`: each
  decision as a question, its answer, the cues that support it and how
  sure it is. It works from the text while the audio step runs. Once the
  voices are in, a voice mapper subagent decides which character each voice
  is, and `bible.py voices` adds those answers to the bible, so the check
  in step 5 covers them too.
- **5. Check the bible.** `bible.py questions` strips the answers. A second
  reader, who never sees the bible, answers the same questions from the
  subtitles. It starts as soon as the bible is written, while the audio
  step may still run. The voice questions come from `bible.py
  voice-questions`, and a second second reader answers them beside the
  voice mapper. `bible.py compare` locks what both agree on. A judge reads only
  the cited cues for the rest and decides from the evidence or by a safe
  default. `bible.py apply` writes the result; anything settled by a safe
  default goes into the report.
- **6–7. Translate.** One subagent per chunk, all started at once, each with
  the Turkish language pack (`pack-tr.md`), the bible, your preferences and
  its neighbours' chunks for context. In a polish run there are no
  translators: `polish.py seed` puts the Turkish file's text on the timing
  file's cues, `polish.py flags` lists the cues to fix (check fails, lines
  left in English, crude lines the Turkish tones down, lines that may sit
  on the wrong cue), and one polish fixer subagent changes only those. The
  step 10 reviewer starts in the same message and reads the film while the
  fixer works; where both change a flagged cue, the fixer's version wins.
- **8–9. Assemble and check.** `assemble.py check` joins the chunks and checks
  every cue. Hard fails are missing, extra or empty cues, italics or
  dialogue dashes that differ from the source, and too many lines; they go
  back to the chunk's translator, and after two rounds one more round runs
  on a stronger model. Warnings (long lines, fast reading speed, glossary
  variants, sen or siz against the bible, and a few Turkish style checks)
  go to the reviewer.
- **10. Review.** One subagent reads the whole film side by side with the
  source and fixes what the chunk translators could not see.
  In a polish run, `polish.py soft` then lists the lines that are still
  softer than the English swearing. The polish fixer restores them once,
  and any line still soft goes to "Check after watching".
- **11. Deliver.** `assemble.py deliver` writes `<film>.tr.srt` next to the
  video and moves any older Turkish file to a backups folder. `report.md`
  ends with "Check after watching": what could not be settled for
  certain, with timestamps, kept out of the chat so nothing is spoiled.

## Learn mode

After you fix lines in a delivered file, `/turkish-subtitles:subtitle learn
<film>` runs `learn.py diff`, proposes up to five general rules from your
edits, and saves the ones you accept in your preferences. Every later run
uses them.

## Files

- Your settings and credentials: `~/.config/turkish-subtitles/`.
- One work folder per film, the download cache and the scripts' results:
  the plugin's data folder, which Claude Code deletes when you uninstall the
  plugin.
- Next to the video: only `<film>.tr.srt`.
