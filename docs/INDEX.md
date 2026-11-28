# Subtitle It docs

> A Claude Code plugin that reads a film's subtitles in any language and writes natural Turkish ones.

Pick the one file you need here; do not read the folder. Every doc says what it owns under its title.
State is one of `skeleton`, `draft`, `unreviewed`, `reviewed YYYY-MM-DD`, `none YYYY-MM-DD`, `stale YYYY-MM-DD`.

![The docs programme, one row for each shelf. Getting started has Setup. Guides has After a run. Reference has how a run works, the acts, on-screen text, checks, preferences, files and privacy, and numbers. Explanation has the ideas behind it. History has the changelog](assets/index-programme.svg)

## Getting started

- [Setup](getting-started/SETUP.md): what you need, how to install the plugin, the first run, the three optional extras, and what to do when a step fails - unreviewed

## Guides

- [After a run](guides/AFTER_A_RUN.md): what to do once a subtitle is delivered: read the report, fix lines, and teach the plugin your fixes - unreviewed

## Reference

- [How a run works](reference/ARCHITECTURE.md): the map of a run: who does what, the four acts, the steps in one line each, and what each script and agent is for - unreviewed
- [Act 1: Find](reference/run/ACT_1_FIND.md): the exact rules of steps 0 to 2: finding the film, choosing source subtitles, settling the timings and building the work folder - unreviewed
- [Act 2: Understand](reference/run/ACT_2_UNDERSTAND.md): the exact rules of steps 3 to 5: the voices from the audio, the film bible, and the blind check of the bible - unreviewed
- [Act 3: Translate](reference/run/ACT_3_TRANSLATE.md): the exact rules of steps 6 to 9: which songs are translated, how the translators run, how a polish run differs, the fix rounds and how every cue is laid out - unreviewed
- [Act 4: Finish](reference/run/ACT_4_FINISH.md): the exact rules of steps 10 to 12: the review against the source, the listen pass, the delivered file and the report - unreviewed
- [On-screen text](reference/ON_SCREEN_TEXT.md): how a run finds title cards, captions and signs that the timing file leaves to the picture, and the rules that decide which of them become subtitles - unreviewed
- [Checks](reference/CHECKS.md): every check `assemble.py check` runs on the translated cues: the hard fails, the warnings, and the exceptions each one allows - unreviewed
- [Preferences](reference/CONFIGURATION.md): every setting in `preferences.md`: what it does, the values it takes and its default - unreviewed
- [Files and privacy](reference/PRIVACY.md): where a run writes files, and exactly what leaves your machine, to whom, and when - unreviewed
- [Numbers](reference/NUMBERS.md): every measured figure, with what was measured and when: run time, tokens, cost and downloads - unreviewed

## Explanation

- [The ideas behind it](explanation/OVERVIEW.md): why the plugin is built the way it is: the nine ideas a run rests on, what was tried and turned down, and what it deliberately does not do - unreviewed

## History

- [Changelog](../CHANGELOG.md): what changed for a user in each version - unreviewed
