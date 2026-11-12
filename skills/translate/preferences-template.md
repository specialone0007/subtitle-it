# Subtitle It preferences

The skill reads this file at the start of every run. Edit it freely.
Learned rules are added at the bottom only after you say yes.

## Media folders

Folders searched when you give a film name instead of a path, one per line.

-

## Translator model

`session` uses the same model as your conversation. Or one of: sonnet, opus, haiku, fable.

session

## Audio hints

Find who speaks each line from the film's audio (needs a free Hugging Face
token; see the README). One of: yes, no, auto. `auto` runs them when an
NVIDIA GPU is found; without one they take about as long as the film.

auto

## Hearing-impaired tags

Sound descriptions (`[door slams]`) and speaker labels (`SANDRA:`,
`[Sandra]`) from a hearing-impaired source file. `remove` takes them out
of the text and of the Turkish, and leaves out cues that are only sounds.
Square brackets go from every file; parentheses and labels in capitals
only from a file that is hearing-impaired.
`keep` leaves the text as the source has it. One of: remove, keep.

remove

## Swearing

match the source

## Titles

How people are addressed by title. Default: Bay/Bayan + surname ("Bayan Kaya").
Or write first name + Bey/Hanım ("Ayşe Hanım").

Bay/Bayan + surname

## Learned rules

