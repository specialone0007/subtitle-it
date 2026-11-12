# Changelog

## 0.5.1 (2026-11-13)

- A sound description that runs over two lines (`[Woman calling out,` /
  `indistinct]`) is now read as one and taken out. Before, each
  half was read alone, matched nothing, and the cue stayed in the work as
  if it were speech. Parentheses get the same treatment in a
  hearing-impaired file, unless the whole of them reads as speech.
- When the source is a separate file that has only sounds on a cue, the
  cue is now left out even if the timing file's text there is a sound in
  parentheses that a plain file keeps (`(Laughs)`).
- `assemble.py check` now cleans the text of every cue again, so a cue
  that holds only sounds is caught even in a work folder built by an
  older version. Turkish text for such a cue is rejected: it is never
  delivered and is no longer sent to the polish fixer.
- In a polish run, a cue with no Turkish now shows
  `tr: <none: write this cue>`, its flag says to write it, and the second
  line of `polish_flags.txt` lists every such cue by number. `polish.py
  flags` returns them as `missing_cues`, and so does `assemble.py check`,
  which before named only the first 30 hard fails. The polish fixer's
  brief starts with these cues and has it check the list before it
  replies.
- When the reviewer and the polish fixer both write a cue, the
  reviewer's version now wins, whichever of them finished first. The
  reviewer fixes that cue's flags too when it rewrites one. Before, the
  fixer won, while the fixer's brief said nothing about it.
- A dialogue line that starts with a description, `- (Laughs) - What?`,
  now becomes `- What?` instead of `- - What?`.
- WAIT, NO, HEY and YES (and BEKLE, HAYIR, EVET, SON DAKİKA) before a
  colon or in brackets are no longer read as a speaker's name. A label is
  matched whole as well as by its first word, and in Turkish capitals too
  (`[Dikkat]`). A place with a number (`[Pier 12]`, `[Gate 3]`) is no
  longer a speaker either; `[Guard 2]` still is.

## 0.5.0 (2026-11-12)

- Hearing-impaired text is now taken out before any agent sees it.
  Sound descriptions in square brackets (`[door slams]`) and bracketed
  names (`[Sandra] text`, `[1. Man] text`, `[Guard 2] text`) go from every
  file. Descriptions in parentheses (`(sighs)`) and labels in capitals
  (`SANDRA:`) go only from a file that is hearing-impaired; elsewhere they
  stay, since plain files use them for dialogue. Even there a parenthesis
  that ends in ? or !, or holds a sentence with words on both sides, is
  kept, and capitals before a colon count as a label only when they look
  like a name: letters only, at most 3 words, and not a word such as OK,
  WARNING, DAY or PART. Each label stays as the cue's speaker hint. A cue
  that is only sounds is left out of the translation and of the delivered
  file; a cue with sounds and speech keeps the speech, and song lines with
  words stay. The new preference `Hearing-impaired tags: keep` turns this
  off and keeps today's behaviour. With `remove`, the default, a Turkish
  cue with square brackets is a hard fail, and so is a label or a
  description in parentheses where the source cue had tags removed.
- A file is now called hearing-impaired by its content, when at least 3%
  of its cues hold such tags or labels, not only by its name or track tag.
  The build result and the report say so.
- Every delivered cue now has at most 2 lines of 42 characters, and a cue
  with two speakers one line per speaker. A cue that does not fit is
  rewrapped, or, when it has two speakers, split at the speaker change
  into one cue per speaker, with the time shared by length (a part that
  would get under a second gets a second) and the file's usual gap
  between them. A split needs every part to last at least a second and
  read at 17 characters a second or less; otherwise the cue goes back to
  be shortened. The language pack no longer allows 3 lines.
- The delivered file is now numbered on its own. `cue_map.json` (and
  `delivered_map.json` after delivery, and a `.map.json` beside a backed-up
  earlier delivery) leads each delivered cue back to the timing file's
  cue. The new `assemble.py where` command gives a cue's delivered numbers
  and time for the report, and `learn.py diff` names both numbers.
- A polish run now seeds a two-speaker cue that an earlier delivery split
  back as one line per speaker.
- A Turkish file to polish now needs to cover 80% of the spoken cues
  instead of 90%, and the run tries at most 2 files instead of 3, a hash
  match first. The reason a file does not fit now reads, for example,
  "covers 89.5% of the spoken cues, needs 80.0%". Cues the file does not
  cover are translated by the polish fixer, as before.
- A voice from the audio that mixes several characters (six or more
  labelled cues, none of them two thirds) now gives no speaker hint at
  all, so the address-form check no longer judges its cues. The audio
  step's result counts these in `voices_dropped`.
- `bible.py compare` now lists the questions the second reader left
  unanswered, and the skill asks it those once more.
- The translator and the polish fixer may now rewrite their own output
  file when they spot a mistake in it.
- Each run now records its time and usage. The new `scripts/usage.py`
  marks the start of each step group and keeps each subagent's tokens and
  time from its completion notice. `report.md` gets a "Time and usage"
  section with the wall-clock time per step group, and the agents' count,
  tokens and time per kind. It says which figures a run cannot see (the
  main session's own tokens, and new against cached tokens) instead of
  estimating them. The same figures go to `usage.json` in the work folder.

## 0.4.0 (2026-11-12)

- Path arguments that start with `~`, such as
  `--config ~/.config/turkish-subtitles`, now mean your home folder in
  every script, even when the shell passes the `~` through unexpanded.
- A built-in subtitle track whose language tag is not a plain two- or
  three-letter code is now saved as `und`, so the tag can no longer shape
  the file name.
- The skill now writes paths in commands inside single quotes, and stops
  and asks you to rename a file whose path holds `$`, a backtick or a line
  break.
- The credentials file is created readable only by you from the start,
  not made private after it is written. OpenSubtitles download links must
  be https, and the API host from the login is used only when it is
  `opensubtitles.com` or one of its subdomains, so your key and login
  token never go to another host.
- OpenSubtitles API requests, which carry your key and login token, now
  follow a redirect only to `opensubtitles.com` over https and stop with
  an error on any other. The subtitle file download sends no key or
  token and follows only https redirects.
- A downloaded subtitle file larger than 5 MB is refused with an error
  and not saved.
- The bible writer and second reader no longer have the web-fetch tool;
  a web search is enough for cast and plot.
- `SECURITY.md` now says the credentials file is plain text and that the
  audio hints load the pyannote checkpoints with full pickle loading. The
  README names the third-party models and tools and their terms.
- The README and `SECURITY.md` now say that the film's title and year go
  to a web search.
- The README and `SECURITY.md` also say that uv may download a Python
  build when no installed one fits, and that the subtitle file comes from
  the https host OpenSubtitles links to, with no key or token sent.
- Docs: the README is rewritten for a first-time reader, with pictures in
  a film look (an example scene, one run's numbers, the cast, a map of the
  whole run, link buttons and end credits). The architecture doc moved
  from `docs/architecture.md` to `ARCHITECTURE.md` at the top level, with
  one heading per step. The README's "Setup" section is now "Quick start".
  Nothing about a run changes.
- CI now also runs on macOS, and installs ffmpeg on every system. A new
  test, `tests/test_ffmpeg.py`, builds a 5-second video with a text subtitle
  track and reads it back with the real ffmpeg and ffprobe, so a difference
  between systems shows up in CI rather than in a run.
- The translators now run at low reasoning effort (`effort: low` in
  `agents/translator.md`), whatever effort the session uses. The fix rounds
  use the same agent, so they do too. On a 2-hour test film this cut the
  translators from $3.88 to $2.16 at list prices, about 17% of a film's
  cost, and steps 6 to 10 finished 1.4 minutes sooner. In a blind test of
  100 cues, three judges preferred the medium-effort file on 20, the
  low-effort file on 15 and found 65 equal, a gap within their disagreement
  (sign test p = 0.5). A Translator model of `sonnet` now also runs at low
  effort; that pairing is untested.
- Tidy-up: learn mode and the one-time setup steps (media folders,
  OpenSubtitles credentials, the Hugging Face token) moved out of
  `SKILL.md` into `learn.md` and `setup.md`. The skill points to the right
  section and reads those files only when it needs them. A run does the
  same steps as before; this keeps `SKILL.md` focused on the run itself
  and does not change what a run costs.
- The bible check starts earlier. The second reader now answers the bible
  writer's questions as soon as the bible is written, while the audio step
  may still be running. The voice questions come from the audio step's
  voices (`bible.py voice-questions`), and a second reader round answers
  them beside the voice mapper. On a 2-hour test film this cut the steps
  from the audio step to the judged bible from 13.1 to 9.2 minutes, about
  2.5 minutes of it from the change itself; agreed, judged and tie counts
  stayed the same within run-to-run spread.
- Fix rounds 1 and 2 now say which model they use: the preferences'
  "Translator model", the same as the translators. The skill named a model
  only for round 3 (Opus), so the first two rounds could run on either.
- The audio step's sync check now catches subtitles that are a second or
  more off the speech. It used to match each cue to the nearest speech
  start, and once the shift neared the gap between lines that start belonged
  to the neighbouring line: on a 2-hour test film, shifts of 1.5 to 5
  seconds either way all read as in sync. It now tries every constant offset
  within 20 seconds and keeps the one under which most speech starts land on
  a cue, as `srt.py fit` does for two files. On a 2-hour test film every
  shift from 0.6 to 5 seconds is found within 5 ms of its size (measured
  from the unshifted file, which sits 100 ms early), and the unshifted file
  stays in sync. When no offset clearly beats the rest it says so instead of
  guessing.
- A polish run is faster. The polish fixer and the whole-film reviewer now
  work at the same time on one film instead of one after the other, and
  the audio step's sync check transcribes five 3-minute stretches instead
  of the whole film (about 30 seconds instead of 2.5 minutes on a GPU).
  The skill also tells the main conversation never to wait with `sleep`.
- The skill now always pairs an English hearing-impaired file as the
  cross-check when one exists besides the timing file, even when the
  timing file is itself English. Its speaker names feed the sen/siz checks,
  which had none before on such a film.
- The skill now tries up to 3 Turkish results before translating from
  scratch. A first result cut from another version of the film no longer
  turns a polish run into a full translation.
- A polish run now also lists the cues around a wrong sen or siz. When the
  address check finds the wrong form on one cue, the other cues of that
  scene that use the same form go to the fixer too, if the bible cannot say
  who they address. A scene ends at a pause of more than 6 seconds. Human
  files often keep one form through a whole quarrel, and the check alone
  caught only 9 of the reviewer's 40 sen/siz changes on a 2-hour test film.
- A polish run no longer leaves a line softer than the source's swearing.
  The toned-down check now knows strong and mild words, so "fuck" turned
  into "lanet olsun" is flagged. After the review, `polish.py soft` lists
  the lines still soft, the polish fixer restores them, and the report lists
  any left. On a 2-hour test film the human file had 52 such lines; 11 were
  left after the fixer and the reviewer, before this last pass.
- The bible check now counts two voice answers as the same when they name
  the same character first or read the same up to a bracket, semicolon or
  comma, so "Harlan Pike" and "Uncle Harlan Pike" no longer go to the judge.
  A name followed by 's, as in "Sam's mother", names no one. On a 2-hour
  test film the readers now agree on 23 of 32 voices instead of 8.
- `learn.py scan` no longer lists an older run's work folder as edited by
  you when a later run delivered to the same file. Only the last delivery
  to each file counts.
- The README's token note now gives the measured numbers.
- A run now starts from a human-made Turkish subtitle when one fits the
  film's timing: from the video's own files, else from OpenSubtitles. It
  skips the translators. A polish fixer agent changes only the flagged cues,
  and the reviewer also restores toned-down lines and checks lines on the
  wrong cue. On a 2-hour test film that used about half the subagent tokens
  of a full run. Without a fitting Turkish file the run translates as
  before.
- New `scripts/polish.py` for that path. `seed` puts the Turkish text on the
  timing file's cues and copies the timing file's italics and dialogue
  dashes where that is a mechanical change. `flags` lists only the cues a
  fixer must change: hard check fails, glossary and sen/siz warnings, long
  lines, lines left in English, crude or sexual lines the Turkish tones
  down, and cues where a Turkish line may sit on the wrong cue. On a 2-hour
  test film it flags 134 of 1,838 cues.
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
  makes one from the film's own speech with Whisper
  (`scripts/transcribe.py`), the last resort. Translators are told the text
  may be misheard, and the report says the subtitles came from the audio.
- A film given by path from a folder that is not in your media folders adds
  that folder, so later runs find films there by name
  (`sources.py remember`). A film in its own folder adds the folder above
  it.
- When no film matches, the run names any media folder that was not there,
  such as an unplugged drive, instead of only saying nothing was found.
- Step 2 also reads subtitle files in a `Subs` or `Subtitles` folder beside
  the video, up to two levels down, where a film's subtitles often sit
  (`Subs/English.srt`, or numbered subtitle files in a subfolder). Before,
  only files next to the video and named after it were found, so the run
  fell back to OpenSubtitles.

## 0.3.0

- A second reader answers the bible's questions blind, and a judge settles
  any difference from the cited cues (`scripts/bible.py`, step 5 of the
  skill).
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
