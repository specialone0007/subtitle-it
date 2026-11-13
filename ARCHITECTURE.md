# How a run works

![How a run goes: find the film, get subtitles, audio hints, film bible, translate, check, review, deliver](docs/assets/run-strip.svg)

One command starts a run, and about a quarter of an hour later a Turkish
subtitle file sits next to the video. This page walks through what happens
in between, step by step. The step numbers match `skills/translate/SKILL.md`,
the skill Claude follows in your conversation for `/subtitle-it:translate`.

Turkish is the first supported language, and more are planned. Every run
today writes Turkish: the language rules sit in a Turkish language pack,
`pack-tr.md`, and the agents' instructions are written for Turkish.

## Who does what

![The cast: the scripts are plain Python, the local models listen to the audio on your machine, and Claude does the language work as seven kinds of agent](docs/assets/cast.svg)

The work is split by one rule: anything with one right answer is a script,
and anything that needs a feel for language is an agent.

- **Scripts** (`scripts/`) read subtitle files, match timings, cut chunks,
  check the translation, write the file and record the run's time. They
  are plain Python, tested, and print a JSON result.
- **Local models** listen to the audio on your machine: pyannote finds who
  speaks when, and Whisper checks the sync or, as a last resort, writes the
  subtitles from speech.
- **Subagents** do the language work: the film bible, the second reader,
  the judge, the voice mapper, one translator per chunk (or one polish
  fixer) and one reviewer. Each runs as its own agent type from `agents/`:
  the file holds its instructions and the few tools it may use, and leaves
  out the general Claude Code instructions and your CLAUDE.md files, which
  it does not need. The skill passes only the paths. Each one writes its
  files and replies with a short summary.

The main conversation never reads a whole subtitle file. It reads the
scripts' results, the bible and the review, so a full film fits in one
session.

## The whole run on one page

![The whole run on one page, in four acts: find, understand, translate, finish. Blue is a script, green a local model on your machine, red is Claude](docs/assets/run-map.svg)

Read it top to bottom. A dashed gold frame means the boxes inside it run at the same time. The numbers match the steps below.

## The steps

### 0. Start

Checks that uv and ffprobe are installed, finds your settings folder
(moving the one from before the plugin was renamed into place, once),
reads your preferences, and mentions any delivered file you have edited
since.

### 1. Find the film

`sources.py find` searches your media folders.

- Copies of one film are picked without asking.
- Different films with a matching name (Alien and Aliens) are the one
  question a run asks.
- A film given by path from a folder not listed yet adds that folder
  (`sources.py remember`).
- A listed folder that is not there, such as an unplugged drive, is named
  when nothing is found.

### 2. Source subtitles

The run needs source subtitles to translate from, and tries three places
in order.

1. **On disk.** `sources.py local` reads text tracks inside the video, files
   next to it, and files in a `Subs` or `Subtitles` folder beside it.
2. **OpenSubtitles.** `opensubtitles.py` searches by the video's hash, then
   by IMDb id or title.
3. **The film's own speech.** With nothing usable from either,
   `transcribe.py` writes subtitles with Whisper, the last resort.

Then it settles the timings:

- The timing file is the one whose timing is most certain to fit this exact
  video.
- Other files are paired onto it by time only when `srt.py fit` says they
  line up after one constant shift (it ignores sound descriptions and
  songs). A shifted file is written with `srt.py shift` first.
- `prepare.py build` writes the work folder: `cues.json` (every cue with its
  source and English text) and `chunks.json` (about 250 cues each, cut at
  the longest pause).
- Unless your preferences say `Hearing-impaired tags: keep`, `build` takes
  sound descriptions in square brackets (`[door slams]`) and bracketed
  names (`[Sandra]`, `[1. Man]`) out of every text. From a file that is
  hearing-impaired it also takes descriptions in parentheses (`(sighs)`)
  and labels in capitals (`SANDRA:`), but keeps a parenthesis that ends in
  ? or !, or holds a sentence with words on both sides, and capitals that
  do not look like a name (`OK:`, `DAY 3:`). Each label is kept as the
  cue's speaker hint. A cue that is only sounds is marked and left
  out of the translation and of the delivered file. `sources.py` calls a file hearing-impaired when at least 3% of its
  cues hold such tags or labels, whatever its name says.
- Whatever that setting says, `build` follows the Netflix Turkish style
  guide on bare sounds: a cue that is only "Oh.", "Hmm?" or "Uh, um..." is
  left out the same way (`left_out: "sound"`), since the audience hears
  it. A yes or no said as a sound ("Uh-huh.") right after a question stays,
  and the translator writes it as a word. A cue whose words are all song
  lyrics is marked `song`; step 6–7 decides which songs are translated.

The step also looks for a human-made Turkish subtitle. It tries at most two
files, a hash match first, and stops at the first one that passes
`srt.py fit`: one constant shift lines it up, and it covers at least 80%
of the timing file's spoken cues. Then the run is a polish run (see
steps 6–7).

### 3. Speaker hints (optional)

`speakers.py` finds who speaks each line from the audio and checks the
subtitles are in sync with it, from five 3-minute stretches spread over the
film.

- Subtitles more than 300 ms off are shifted with `srt.py shift`, and the
  voices are matched again.
- A voice can gather several characters. When a voice has at least six
  cues with a speaker label and no character holds two thirds of them, its
  cues get no voice hint, and the address-form check leaves them alone.
  A hint that is wrong in one cue out of three is worse than none.
- Everything runs on your machine.
- It runs in the background while the bible is written, since it takes
  several minutes.

### 4. Film bible

A subagent reads the film once and writes down the decisions every
translator must share:

- `bible.md`: characters, who says sen or siz to whom, fixed terms.
- `glossary.json`.
- `decisions.json`: each decision as a question, its answer, the cues that
  support it and how sure it is.
- `songs.json`, when the film has song cues: the songs that carry the
  story (sung on screen, or lyrics the scene plays against), by cue range.

sen/siz is read from the tone of each scene, not only the relationship on
paper: people at ease say sen, and a pair can shift for one scene (a cold
siz in a fight) and back. The fallback for an unclear pair is siz only for
formal relations; adults of about the same age at ease get sen.

It works from the text while the audio step runs. Once the voices are in, a
voice mapper subagent decides which character each voice is, and
`bible.py voices` adds those answers to the bible, so the check in step 5
covers them too.

### 5. Check the bible

A bible written by one reader can be confidently wrong, so a second reader
answers the same questions without seeing it.

1. `bible.py questions` strips the answers.
2. A second reader, who never sees the bible, answers the same questions
   from the subtitles. It starts as soon as the bible is written, while the
   audio step may still run.
3. The voice questions come from `bible.py voice-questions`, and another
   round of the second reader answers them beside the voice mapper.
4. `bible.py compare` locks what both agree on, and names the questions
   the second reader skipped, so it is asked those once more.
5. A judge reads only the cited cues for the rest and decides from the
   evidence or by a safe default.
6. `bible.py apply` writes the result. Anything settled by a safe default
   goes into the report.

### 6–7. Translate

First `prepare.py songs` applies the preferences' `Songs` (`story`,
`skip` or `all`): with `story`, every song cue not in `songs.json` is
marked `left_out: "song"`, gets no chunk line and is not delivered. Then
`chunks` writes the chunks again without them.

One subagent per chunk, all started at once. Each gets the Turkish language
pack (`pack-tr.md`), the bible, your preferences and its neighbours' chunks
for context.

The translators run at low reasoning effort (`effort: low` in
`agents/translator.md`), whatever effort the session uses. The fix rounds
of step 9 use the same agent, so they do too. On one 2-hour film (1,838
cues) this cost about 17% less per film than medium effort and finished
steps 6 to 10 1.4 minutes sooner, with no measurable loss in a blind test
of 100 cues (medium preferred on 20, low on 15, 65 equal). A Translator
model of `sonnet` also runs at low effort; that is untested.

**In a polish run** there are no translators:

- `polish.py seed` puts the Turkish file's text on the timing file's cues.
  Timing cues the file does not cover get no text; the check counts them
  as missing, and the polish fixer translates them.
- `polish.py flags` lists the cues to fix: check fails, lines left in
  English, crude lines the Turkish tones down, and lines that may sit on
  the wrong cue.
- One polish fixer subagent changes only those.
- The step 10 reviewer starts in the same message and reads the film while
  the fixer works. Where both change a flagged cue, the reviewer's
  version wins, and it fixes that cue's flags too.

### 8–9. Assemble and check

`assemble.py check` joins the chunks and checks every cue.

- **Hard fails** are missing, extra or empty cues, italics or dialogue
  dashes that differ from the source, a cue that cannot be laid out (see
  below), and square brackets in the Turkish, or a speaker label or a
  description in parentheses where the source cue had tags removed. They go
  back to the chunk's translator, and after two rounds one more round runs
  on a stronger model.
- **Warnings** are reading speed above 17 characters a second (every
  such cue, even when the source is as fast), glossary variants, sen or
  siz against the bible, a plain "hala" or "aşık" that probably lacks its
  circumflex, and a few Turkish style checks. They go to the reviewer.

The last part of the check lays out every cue as it is shown
(`layout.py`): at most 2 lines of 42 characters, and in a two-speaker cue
one line per speaker. A cue whose text fits two lines is rewrapped.
Turkish line breaks follow the Netflix Turkish guide (`turkish.py`): a
break after a sentence end or a comma comes first, then one before a
conjunction, and no second line starts with a word that leans on the
one before ("gibi", "diye", "mi", "de"). A two-line cue that already fits
but breaks badly is rewrapped when a better break fits. A
two-speaker cue that does not fit is split at the speaker change into one
cue per speaker. Its time is shared in proportion to each part's length,
and a part that would get under a second gets a second, taken from the
others. The file's usual gap goes between the parts. The split is made
only when every part lasts at least a second and reads at 17 characters a
second or less. Anything else is a hard fail. The draft is numbered from 1 as delivered, and
`cue_map.json` leads each delivered cue back to the timing file's cue; the
rest of the work folder keeps the timing file's numbers.

### 10. Review

One subagent reads the whole film side by side with the source and fixes
what the chunk translators could not see. The bible is its default for
sen/siz, but the scene decides: it never turns a natural sen into siz only
to match the bible, and lists each cue where it departs from the bible.
It fixes reading-speed warnings with shorter wording, and family words
("amca" or "dayı") and circumflexes that differ from the bible or the pack.

In a polish run, `polish.py soft` then lists the lines that are still
softer than the English swearing. The polish fixer restores them once, and
any line still soft goes to "Check after watching".

### 11. Deliver

`assemble.py deliver` writes `<film>.srt` next to the video, with exactly
the video's name so TVs pick it up, as UTF-8 with a BOM. Any file already
there is moved to a backups folder, and the result says what it was:
`earlier delivery`, `Turkish` or `not Turkish` (an English `<film>.srt`,
say). For an `.srt` input the name keeps the input's, with `tr` as its
language, so the input is never written over. The cue map is kept with the
delivered copy, and with a backup of an earlier delivery, so the report,
learn mode and old files can still name each cue. `assemble.py where`
turns a work folder cue number into its delivered number and time. `report.md` ends with "Check after
watching": what could not be settled for certain, with timestamps, kept out
of the chat so nothing is spoiled.

Before it, a "Time and usage" section gives the run's wall-clock time and
the time of each step group, from marks `usage.py step` made at the start
of each group, and each agent kind's count, tokens and time, from the
agents' completion notices. It names what a run cannot see: the main
session's own tokens and the split into new and cached tokens, so it gives
no cost in money. `usage.py summary` also saves the same figures as
`usage.json` in the work folder, so several films can be compared.

## Learn mode

After you fix lines in a delivered file, `/subtitle-it:learn <film>`
runs `learn.py diff`, proposes up to five general rules from your edits,
and saves the ones you accept in your preferences. Every later run uses
them. It is its own skill, `skills/learn/SKILL.md`, so a translate run does
not carry its steps. It reads the language pack and the preferences
template from `skills/translate/` rather than keeping copies. The one-time
setup steps live in `setup.md` beside the translate skill, read only when
a step needs them.

## Files

- Your settings and credentials: `~/.config/subtitle-it/`. A settings
  folder from before the plugin was renamed is moved there once, by
  `settings.py`, without opening the files in it.
- One work folder per film, the download cache and the scripts' results:
  the plugin's data folder, which Claude Code deletes when you uninstall the
  plugin.
- Next to the video: only `<film>.srt` (`<film>.tr.srt` before 0.6.2;
  learn mode still finds those through each run's `delivered.json`).
