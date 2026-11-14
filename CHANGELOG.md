# Changelog

## 0.7.3 (2026-11-14)

Fixes for warnings the checks raised on correct Turkish in a full run,
13 of them at delivery on one film.

- Family words win over generic terms: when a bible decision gives
  "brother" one rendering for the whole film and a pair's family-word
  decision gives "abi", the `term rendering` and `term variant` checks
  accept the pair's word. `bible.py apply` lists such clashes as
  `term_conflicts` for the report, and the bible writer is told never to
  give a bare family word one rendering for the whole film. The Turkish
  choices a family question quotes ("abi" or "kardeş") are no longer
  read as source terms.
- One word, several senses: decisions that quote a term with and without
  an article ("the loft", "loft") count as one term, so either sense's
  rendering passes. The run's three `term rendering` warnings on this were
  all correct Turkish.
- The address check stays silent on a cue that is most likely the other
  person's turn: its speaker comes from the voice alone, the cue next to
  it has the same voice, its form is the one the other side of the pair
  uses back, and that person is in the scene. The cost: a speaker's own
  slip into the other side's form, on two cues in a row with that person
  in the scene, is silent too. The reviewer still reads sen and siz for
  the whole film.
- The README has a Languages section: from any language, into Turkish
  today, a list meant to grow. The plugin and marketplace descriptions
  say the same.

## 0.7.2 (2026-11-14)

Fixes from a side-by-side reading of two full runs on one film: lines
that lost meaning to reading speed, sentences split badly over cues, and
words the film did not write one way.

- Meaning before reading speed: the translator, the polish fixer, the
  reviewer and the Turkish pack shorten a fast line only by rephrasing or
  by dropping filler. A clause, a question, a name or a second sentence is
  never dropped; a fast line that keeps the meaning stays a warning.
- Split sentences: a new `split sentence` warning covers each run of cues
  whose source sentence goes on without a full stop. It fires when the
  Turkish writes one part twice, leaves a cue with nothing of its own, or
  puts a name in another cue than the one that says it. The fixer and the
  reviewer take the run as one unit: the whole sentence first, then each
  part exactly once.
- The bible lists slang and idioms with their meaning in the film
  ("pigeon" for a sucker, "chasers", "the bottom of the church" for the
  basement), and decides once who is older in each pair of siblings, with
  one spelling ("abi", not "abi" and "ağabey").
- One rendering per term: `term rendering` warns when a cue's source says
  a term the bible decided and the Turkish has none of its rendering;
  `term drift` warns on a second form of a word the film otherwise writes
  one way (abi/ağabey, celp/celpname).
- Name suffixes follow how the name sounds: `name suffix` warns on
  "Joey'in" (write "Joey'nin") and "John'nun" (write "John'un").
- TDK spellings: `spelling` warns on common slips such as "sağol",
  "herşey", "bir çok", "yanlız" and "malesef".
- The address-form check no longer warns when it may have the wrong
  speaker: a question and its answer heard as one voice, a two-speaker
  cue, or a name spoken about rather than to ("you and Father Barry").
- The run goes on as soon as an agent's output files are written and
  stop changing (`usage.py wait`), rather than waiting for the agent's
  completion notice, which can come many minutes later. A notice that
  comes late is still recorded; one that never comes is recorded as `-`.
- Earlier deliveries under another name, such as `Film.tr.srt` from before
  0.6.2 or from the plugin's old name turkish-subtitles, are recognised
  from every work folder's record. `sources.py local` marks them as this
  plugin's earlier delivery, and a delivery to the default name next to
  the video (`deliver --video`) moves them to the backups folder and says
  so in the report. A delivery to another destination moves nothing.
- `scripts/compare.py` is a local tool for blind comparisons: it writes
  shuffled side-by-side rows of two or three delivered files with the
  English, keeps the key apart, and turns a judge's verdicts back into
  per-version and head-to-head numbers. It refuses to write inside the
  repository, so no film text is committed.

## 0.7.1 (2026-11-14)

Four rules from the Netflix Turkish Timed Text Style Guide that change how
the subtitle reads.

- Reading speed: the check warns about every cue above 17 characters a
  second (I.17). It no longer lets a cue pass because the source line is as
  fast; the viewer reads Turkish.
- Line breaks (I.12): a new `turkish.py` holds the Turkish-only rules. The
  rewrap prefers a break after a sentence end or a comma, then one before a
  conjunction, and never starts the second line with a postposition or a
  particle ("gibi", "diye", "mi", "de") or leaves one word alone on a line.
  A two-line cue that already fits but breaks badly is rewrapped when a
  better break fits. The pack and the translator brief state the rule.
- Accents (I.22): the pack lists the circumflexes that change the meaning
  ("hâlâ" and "hala", "âşık", "kâr", "resmî"), and the check warns about a
  plain "hala" or "aşık" so the reviewer can tell "still" from "aunt".
- Family words (I.22): the bible writer decides "amca" or "dayı", "hala"
  or "teyze", "abi" or "kardeş" for each relation the film shows, as a
  checked `term` decision, and the pack says what to use when the film
  does not show the side.

## 0.7.0 (2026-11-14)

Feedback from The Dog Stars: some scenes were too formal, background songs
were translated, and some lines were word for word and slow to read. The
fixes follow the Netflix Turkish Timed Text Style Guide where it has a rule.

- sen/siz follows the scene, not only the pair. The bible records each
  pair's usual form and the scenes where it shifts. When unsure, siz is
  kept for formal relations, and adults of about the same age at ease say
  sen. The reviewer no longer turns a translator's natural sen into siz to
  match the bible; it lists each cue where it departs from the bible.
- Songs: a new `Songs` preference, `story` by default. Only songs that carry
  the story (sung on screen, or lyrics the scene plays against) are
  translated; the bible writer lists them in `songs.json`, and
  `prepare.py songs` leaves the rest out of the translation and the
  delivered file. `skip` translates none, `all` every one. Lyrics follow
  Netflix formatting: italics, `♪` at both ends, a capital at each line
  start, no comma or full stop at a line end.
- Readable at a glance: the language pack now opens with this rule, and
  has before/after examples. Lines are reshaped into fewer, plainer words
  without losing what is said, a phrase repeated in a row is written once,
  and the reviewer fixes reading-speed warnings with shorter wording
  instead of leaving them.
- Bare sounds: `prepare.py build` leaves out a cue that is only "Oh.",
  "Hmm?" or "Uh, um...". A yes or no said as a sound ("Uh-huh.") right
  after a question stays and is written as a word. The report counts the
  bare sounds and songs left out, and `assemble.py where` names the reason.

## 0.6.2 (2026-11-13)

- The Turkish subtitle is now delivered with exactly the video's name:
  `Film.mkv` gets `Film.srt`, not `Film.tr.srt`. Many TVs (Samsung, LG)
  only load a subtitle file named like the video, and showed the film's
  built-in English subtitles instead. For an `.srt` input the name still
  swaps the language part for `tr`, so the input is not written over.
- The delivered file is saved as UTF-8 with a BOM, so TVs show ş, ğ and ı
  instead of guessing another encoding.
- A file already at the destination, such as an English `Film.srt`, is
  moved to the backups folder as an old Turkish file was. The `deliver`
  result says what it was (`old_file`: `earlier delivery`, `Turkish` or
  `not Turkish`), and the run tells you where a non-Turkish one went.
- `sources.py local` no longer takes the plugin's own earlier delivery
  (`Film.srt`, or a `Film.tr.srt` from an older run) as a source or as a
  Turkish file to polish, and treats a `Film.srt` with Turkish text as an
  existing Turkish file. Learn mode still finds films delivered as
  `.tr.srt` before this release.

## 0.6.1 (2026-11-13)

- A subtitle file with a missing blank line between two cues is now read
  as two cues. Before, the second cue's number and timestamp became text
  of the first. A blank line in the middle of a cue no longer drops the
  text after it: that text stays with its cue. `prepare.py build` counts
  these repairs per file under `repairs` and `warnings`, and the run
  report says which file was malformed. `sources.py validate` and
  `srt.py info` show the count as `repairs`; a repaired file still passes
  validation.
- Delivering twice to the same file within one second no longer writes
  the second backup over the first: a backup name that is taken gets a
  counter (`Film.tr.20261113-120000-2.srt`).
- `opensubtitles.py` ends with its usual one-line error, and writes
  nothing, when the subtitle file link answers with an HTTP error or the
  network fails, when the API sends a reply that is not JSON, and when
  `credentials.json` is not valid JSON or has no API key. Before, each of
  these showed a Python traceback. A timeout is retried like other network
  errors.
- A download is cached through a temporary file, so a run stopped while
  writing it never leaves half a file that later runs would reuse.

## 0.6.0 (2026-11-13)

- The plugin is now called subtitle-it, since Turkish is the first
  supported language and more are planned. Every run still writes Turkish,
  to `<film>.tr.srt`. Install it with
  `claude plugin marketplace add specialone0007/subtitle-it` and
  `claude plugin install subtitle-it@subtitle-it`. The plugin's data
  folder follows the new name, so work folders from earlier runs under the
  old name (`turkish-subtitles`) are not carried over: the learn command
  cannot find films delivered before the rename.
- Upgrading: the old plugin stays installed beside the new one until you
  remove it. If you want rules from fixes to a film delivered before the
  rename, run the old plugin's `/turkish-subtitles:subtitle learn <film>`
  first, since uninstalling it deletes its work folders. Then run
  `claude plugin uninstall turkish-subtitles@turkish-subtitles` and
  `claude plugin marketplace remove turkish-subtitles`. Your settings
  folder is kept and moves on its own.
- The command is now `/subtitle-it:translate <film>`, and learning from
  your fixes has its own command, `/subtitle-it:learn <film>`, instead of
  `learn` as the first argument. With no film named, the learn command
  lists the delivered files you edited and asks which one. It reads the
  language pack and the preferences template from the translate skill's
  folder.
- Settings now live in `~/.config/subtitle-it`. The first command that
  needs them renames `~/.config/turkish-subtitles` to it when the new
  folder does not exist yet, without opening the files inside. If the
  rename fails, the old folder is used and the command says why.
- `NOTICE` carries the new name.

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
