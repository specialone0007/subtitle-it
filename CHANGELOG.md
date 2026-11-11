# Changelog

## Unreleased

- A polish run now also lists the cues around a wrong sen or siz. When the
  address check finds the wrong form on one cue, the other cues of that
  scene that use the same form go to the fixer too, if the bible cannot say
  who they address. A scene ends at a pause of more than 6 seconds. Human
  files often keep one form through a whole quarrel, and the check alone
  caught only 9 of the reviewer's 40 sen/siz changes on a 2-hour test film.
- A polish run no longer leaves a line softer than the source's swearing.
  The toned-down check now knows strong and mild words, so "fuck" turned
  into "lanet olsun" is flagged. After the review, `polish.py soft` lists
  the lines still soft, the polish fixer restores them, and the report
  lists any left. On a 2-hour test film the human file had 52 such lines; 11 were
  left after the fixer and the reviewer, before this last pass.
- A run now starts from a human-made Turkish subtitle when one fits the
  film's timing: from the video's own files, else from OpenSubtitles. It
  skips the translators. A polish fixer agent changes only the flagged
  cues, and the reviewer also restores toned-down lines and checks lines on
  the wrong cue. On a 2-hour test film that used about half the subagent tokens of
  a full run. Without a fitting Turkish file the run translates as before.
- New `scripts/polish.py` for that path. `seed` puts the Turkish text on the timing file's cues and
  copies the timing file's italics and dialogue dashes where that is a
  mechanical change. `flags` lists only the cues a fixer must change: hard
  check fails, glossary and sen/siz warnings, long lines, lines left in
  English, crude or sexual lines the Turkish tones down, and cues where a
  Turkish line may sit on the wrong cue. On a 2-hour test film it flags 134 of 1,838
  cues.
- Another subtitle file is now paired onto the timing file when
  `srt.py fit` says it lines up after one constant shift, found by searching
  ±60 s. It ignores sound descriptions and songs, and allows lines that are
  split differently. The old check (`paired_share` above 0.8) refused 5 of
  7 files that fit in a test on real films, mostly because of a different
  intro length or hearing-impaired sound cues.
- Each subagent now runs as its own agent type (`agents/`), with only the
  tools it needs and without the general Claude Code instructions or your
  CLAUDE.md files. Each subagent used to start with about 54k tokens of
  context before reading anything; the instructions it actually follows
  are about 1k. The briefs moved from `skills/subtitle/briefs/` into those
  files.
- The audio step now runs in the background while the bible writer works
  from the text. A voice mapper then matches each voice to a character, and
  `bible.py voices` adds those answers to the bible before it is checked.
  The two steps used to run one after the other.
- When no usable subtitle file exists on disk or on OpenSubtitles, the run
  makes one from the film's own speech with Whisper (`scripts/transcribe.py`),
  the last resort. Translators are told the text may be misheard, and the
  report says the subtitles came from the audio.
- A film given by path from a folder that is not in your media folders adds
  that folder, so later runs find films there by name
  (`sources.py remember`). A film in its own folder adds the folder above it.
- When no film matches, the run names any media folder that was not there,
  such as an unplugged drive, instead of only saying nothing was found.
- Step 2 also reads subtitle files in a `Subs` or `Subtitles` folder beside
  the video, up to two levels down, where a film's subtitles often sit
  (`Subs/English.srt`, or numbered subtitle files in a subfolder). Before, only files
  next to the video and named after it were found, so the run fell back to
  OpenSubtitles.

## 0.3.0

- A second reader answers the bible's questions blind, and a judge settles
  any difference from the cited cues (`scripts/bible.py`, step 5 of the skill).
- A normal run no longer asks anything after setup. It asks only which film
  you mean when the name matches several different films.
- Out-of-sync subtitles are shifted to match the audio, and the voices are
  matched again.
- `assemble.py check` warns when a line uses sen where the bible gives siz,
  or the reverse.
- `report.md` ends with "Check after watching", and the chat message has no
  spoilers.
- CI runs the tests, lint and format checks on Linux and Windows.

## 0.2.0

- Audio hints: a voice per cue from the film's audio, and a check that the
  subtitles are in sync with it (`scripts/speakers.py`).
- Each script saves its JSON result to a file, so output filters in the
  shell cannot cut it.

## 0.1.0

- First version: find the film and its source subtitles, build the film
  bible, translate in parallel chunks, check, review and deliver.
- Learn mode turns your edits into rules for the next film.
