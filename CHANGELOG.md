# Changelog

## 0.13.0 (2026-11-19)

Title cards and signs are now read from the picture itself: texts only
one other track shows are checked against the video, and story texts no
track holds are added as cues of their own.

- `sources.py others` counts the other languages among the usable
  subtitle candidates and names one download, French then Spanish, only
  when fewer than two are found. `prepare.py build --timing-language L`
  records the count of tracks that fit in `build.json`.
- New `screen.py frames` saves frames with ffmpeg from the start to the
  first spoken line and for 2.5 minutes after the story's end, plus 5
  frames for each text only one other language shows; 300 frames at most,
  HDR tone-mapped when ffmpeg can. It writes `W/screen/frames.json` and
  batches of 20 frames.
- New agent `agents/screen-reader.md` reads the frames and writes one
  line per frame: the text word for word, its kind, whether the film
  wants it read, and the entry it shows. `screen.py collect` checks the
  lines, sends missing or bad frames back once, and joins neighbouring
  frames into readings.
- `prepare.py build --screen` adds an unsure or left-out entry as a cue
  when the picture shows it, and adds a story text no track holds as a
  cue of its own under the usual coverage and room rules. Credits, logos
  and background text are never added.
- In a `--shift-ms` rebuild a picture entry keeps its video time and its
  cue number, and is shown at its own time when the shifted lines leave
  room there, even before a cue with a lower number. No cue is ever
  renumbered, so the bible's cue citations stay true. The draft and the
  delivered file are written in time order, and `check` and the listen
  parts measure gaps, reading speed and sentences in time order.
- `deliver`'s report lists every entry the picture looked at, and each
  picture text the shift left with no room, with its video time, to be
  added by hand.
- The translate skill runs all of this in step 2 for a video input.

## 0.12.0 (2026-11-19)

Every on-screen text the other subtitle tracks show is now recorded, the
closing credit starts on the cut to black after the story, and delivered
files lose three kinds of stray marks.

- `prepare.py build` writes `W/on_screen.json` on every build: each text
  the other tracks show, with its time and its state, added as a cue or
  left out with a reason (one language only, no room, a subtitle credit,
  a song line, or shown during a song or a sound). A cue that is
  on-screen text is never marked a song, a sound or a bare sound, and
  `check` fails when one is not delivered.
- `build --shift-ms N` moves the earlier build's on-screen entries by N
  instead of finding them again, so a sync rebuild keeps every cue number,
  and running it twice gives the same files.
- `deliver` returns the report's on-screen section and stops before any
  file moves when `on_screen.json` is malformed. The review and listen
  parts mark on-screen cues.
- New `screen.py ends` reads the 2.5 minutes after the story's last line
  with ffmpeg and records the black stretches in `W/screen/ends.json`.
  The translate skill runs it in the background for a video input.
  `deliver` then starts "Görüşmek üzere." on the first black stretch
  within 30 s after the story, and falls back to the old rule when there
  is none or ffmpeg is missing. The result's `goodbye` says which placed it.
- A `♪` that opens a lyric and is not closed on its line now covers the
  rest of the cue, so a lyric cut off by speech is left out like any song;
  a `♪` at the end of a line closes the lyric.
- `check` fails a Turkish line with a listing slash (` / `) that the
  source and English lines lack, removes `{\an8}`-style position tags so
  every line stays at the bottom of the screen, and a film marked
  `"musical": true` in `songs.json` is delivered without music notes.

## 0.11.0 (2026-11-19)

Title cards and signs the English track leaves to the picture are now
translated when other subtitle tracks show them, and the closing credit
follows the story instead of the last end title.

- `prepare.py build --track LANG=PATH` and `--forced-track LANG=PATH`
  (both repeatable) add lines the timing file lacks as cues of their own,
  marked `on_screen` in `cues.json`. A line is added when tracks in two
  languages show it at the same time, or a forced track shows it; a line
  in one language only is counted in `build.json`, not added. Subtitle
  credits, song lines and bare sounds are never added, and an added cue
  needs 700 ms of room between its neighbours.
- The translate skill passes every other non-Turkish track as `--track`
  (forced-only ones as `--forced-track`), repeats them on the sync
  rebuild, and reports what was added. Chunks mark such a cue
  `[on-screen text]` with the other languages' wording below it.
- The closing credit "Görüşmek üzere." starts 3 s after the story's last
  line, the last cue that is not on-screen text (a kept song counts), in
  the first free 2 s from there, and ends 0.1 s before the next cue. With
  no free 2 s, or no story cue, it follows the last cue by 3 s as before.
  With `--video` it still stays inside the video's length.
- `delivered_map.json` numbers the draft around the credits wherever they
  fall, so `where` stays right when the closing credit is not the last cue.
- `build` clears `W/screen/` of an earlier run.

## 0.10.1 (2026-11-18)

The credits get more room at both ends.

- The opening credit "İyi seyirler." starts at 3 s instead of 1 s, so it
  shows from 0:03 to 0:07. A film that speaks before 7.5 s gets a shorter
  opening, 3 s at least, and one that speaks before 6.5 s none.
- The closing credit "Görüşmek üzere." starts 3 s after the last line
  instead of 1 s, so it no longer runs straight on from it.
- With `--video`, `deliver` reads the video's length with ffprobe and keeps
  the closing credit inside it: it moves earlier, to half a second after the
  last line at most, then ends with the video, kept for 3 s at least; with
  under 3.5 s between the last line and the video's end, there is none.

## 0.10.0 (2026-11-18)

The delivered file signs off with the translator's name, and a polish run
keeps the human file's wording unless a real check fails.

- The delivered file carries a short credit at both ends, one screen of
  4 s each: "İyi seyirler." over the translator's name from 1 s, and
  "Görüşmek üzere." over the name 1 s after the last line (the greeting
  alone when no name is set). A film that speaks before 5.5 s gets a
  shorter opening, 3 s at least, and one that speaks before 4.5 s none.
  Only the delivered file has it; the draft, the checks and the reviewers
  never see it.
- `assemble.py deliver --credit-name NAME` and `--no-credit`, set by the
  new `Credit` preference (`on` or `off`, with the name on the line below).
  The file holds no web address, since some subtitle sites remove files
  that do.
- `delivered_map.json` moves its numbers down past an opening credit and
  lists the credit cues under `credits`; `learn.py diff` skips them, so an
  edit to the credit teaches nothing.
- Polish run: a human line keeps its words unless it fails a real check; a
  word the bible prefers is not by itself a reason (reviewer item 15).
- Polish run: the listener now runs too. `listenparts` marks untouched
  human lines (`human` column) and skips parts that hold only such lines;
  `listengate` drops an edit to one.
- Polish run: repeat drift is a reviewer-only warning, like reading speed,
  so the polish fixer no longer copies one wording of a repeated line over
  every scene. Reviewers and translators match a line the viewer should
  recognise and word a stock phrase for its own scene.
- The bible writer gives address words ("abi", "dostum", "kanka") per pair
  of characters, never one word for every listener.
- Step 4 keeps the voice round's answers (`WORK/second.voices.json`) for
  step 5's `compare`, unless `bible.py voices` gave up.

## 0.9.0 (2026-11-16)

Lines read the way Turkish people say them: a listener reads the finished
Turkish as a viewer before delivery, and a fast line gets more time on
screen instead of a stiffer wording. On a full rerun of The Odyssey the
listen step changed about 1 line in 42 and the meaning check made fewer
errors than the delivered file; the delivered file, after about nine fix
rounds, still read slightly better.

- New step 11, Listen: one `listener` per part of about 480 cues reads
  the Turkish alone and rewrites lines that do not sound like the
  character speaking Turkish (`agents/listener.md`). `assemble.py
  listenparts` writes the parts with each cue's character budget, its
  sentence group and its repeated lines; `listengate` drops an edit that
  is over budget or gives its cue, sentence or repeated line a new
  problem in the checks; one reviewer (the meaning check) keeps each edit
  or writes the old line back; `listendrop` drops an edit the last check
  fails. `review.md` ends with the listener's counts. Not in a polish run.
- The meaning check writes back an edit that loses a clause, a tense, a
  "not" or the stance, makes a plural singular, narrows a word, adds a
  thing the source does not say, or loses who tells whom. The usage
  report counts it as its own kind, `listen-check`.
- The pack's "How Turkish people say it" gives three principles with one
  example each, plus one line per English habit, in fewer characters than
  before. The bible gets the film's world and register, a `speaks` note
  for up to 8 main characters and a tone note for a pair whose form
  misleads. Reviewer question 6 asks whether a Turkish person would say
  the line this way.
- New warnings: `repeat drift` (one source line written two ways in the
  film; it names the wording most of its cues use, the earliest on a tie,
  and warns only the cues off it) and `ve opening` (a spoken line opening
  with "Ve"; left to the reviewers in a polish run).
- A cue whose Turkish reads above 17 characters a second stays on screen
  until it reads at 17: at most half a second longer, keeping the file's
  usual gap before the next cue, 7 seconds on screen at most. Both
  speeds are measured over that time.
- Reviewer question 7 puts natural Turkish before reading speed: a line
  reaches 17 a second only by a shorter natural wording or by dropping
  filler, never by a stiffer shape, and is otherwise kept and listed as
  kept on purpose. The shortening formula is gone.
- The translators run at medium effort again: low effort tied medium on
  meaning, but not on how natural the Turkish sounds.
- A capitals speaker label followed directly by a tag
  ("BARD:<i>Sing to me.</i>") is stripped.
- A sen/siz reason line survives a later fix file that keeps the form but
  writes no reason, so `check` no longer warns on it. The usage report
  names step 10 "review in parts".

## 0.8.0 (2026-11-15)

Every line gets a careful look: the review runs in parts of about 250
cues, each with its own reviewer, and on the polish path the human Turkish
file decides sen and siz. Long films cost more: about 250,000 review tokens
per 1,000 cues.

- In a polish run the human Turkish file is the evidence for sen and siz.
  The fixer gets no address flags and the part reviewers no address notes;
  both keep a human line's form unless the English line shows the other
  one, and give the reason on an `#address:` line in their fix file.
  `bible.py compare` counts the human file's forms per pair for the judge,
  and `check` lists every changed form (`address_changes`), warning on
  those with no reason. The same-scene address flag is gone.
- A line the part reviewer or the polish fixer rewrites must read as a
  Turkish speaker would say it, not follow English word order or idiom,
  and drops a word the neighbouring cue already carries when Turkish
  would.
- The "story" song setting stays the default. The bible writer brief now
  says that in a musical every song the characters sing is translated, and
  that opening, end-credits and background songs are left out unless their
  words carry the plot.

- The sync check finds an offset in fast, overlapping talk. It now asks
  the best offset to stand out from chance (the median count over all
  offsets tried) instead of beating the runner-up by half again. On a
  test film 10.5 seconds off, the old rule said "no clear offset".
- Songs marked only with italics are found: a run of at least four
  whole-italic cues that end no sentence, in a file that marks no lyric
  with `♪`, `♫` or `#`.
- A built-in track flagged forced that holds the full dialogue is used as
  a source. `sources.py local` marks a candidate `forced_only` only when
  it also holds few cues (under 4 a minute of video).
- The `term rendering` check knows which cues each bible decision covers.
  Term decisions take `applies_to` (`"film"` or cue numbers and ranges);
  older bibles fall back to the evidence cues for one sense of a word and
  for a family word about one pair. Notes after a `;` or in parentheses
  no longer hide a decision, and cue numbers in them exempt those cues.
  A term the next cue of the same sentence carries counts. On four saved
  test runs this removed 23 of 24 term warnings (22 false, one arguable)
  and kept the one real one.
- Every line gets a careful look. The whole-film review is split into
  parts of about 250 cues (`assemble.py reviewparts`), each with its own
  reviewer, who compares every Turkish line with its source: missing
  meaning, text on the wrong cue, case endings and verb forms, sen/siz,
  names and terms, and lines only the Turkish makes too fast. In a polish
  run they rewrite human lines that leave out part of what is said.
  `assemble.py reviews` joins the parts' notes into `review.md`. The
  single side-by-side file and its command are gone.
- The part reviewers run at medium reasoning effort (`effort: medium` in
  `agents/reviewer.md`), whatever effort the session uses. That is the
  effort the split review was tested at: about 50,000 tokens per part.
- The reading speed warning says when only the Turkish is fast, so the
  reviewers know which lines a shorter wording can fix.
- The sen/siz check guesses the listener when a speaker uses different
  forms to different people and the line names nobody: the one other
  character speaking right before or after, in the same scene. On a test
  film this found a judged slip the check missed before.

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
