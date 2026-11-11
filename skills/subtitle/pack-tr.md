# Turkish language pack

Rules every translator and the reviewer follow. The source can be any
language; the target is always Turkish. The user's preferences file can
override the defaults marked "(default)".

## Meaning before words

- Write natural spoken Turkish, the way people in the scene would talk. Never word for word.
- A sentence that runs over 2 or 3 cues is translated as one sentence, then spread back over those same cues. Turkish word order often moves the verb to the last cue; that is fine.
- When the source language and the English disagree, the source language wins. English is a cross-check for meaning and for who speaks.
- Keep names as written in the source. Do not translate place names that have no common Turkish form.

## Form of each cue

- At most 2 lines per cue, at most 42 characters per line. If the source cue has 3 lines, 3 are allowed.
- Keep `- ` dialogue dashes: same number of dash lines as the source cue, one speaker per dash line.
- Keep `<i>` and `</i>` exactly where the source has italics (voices off screen, songs, phone, thoughts). No italics where the source has none.
- No stray byte-order marks, no `{\an8}` style tags unless the source has them.
- Never merge or split cues, never leave one empty. Every cue number in your chunk gets text.

## Grammar traps

- Commands stay commands: "Come." → "Gel.", "Stop!" → "Dur!", "Let's go." → "Hadi gidelim." Never the -mak/-mek form ("Gelmek.").
- Fillers by meaning, never by dictionary:
  - "Well..." → "Şey..." or "Peki..." (never "Kuyu")
  - "So..." → "Yani..." or "Eee..." (not "Bu yüzden" unless it really means "therefore")
  - "Right?" → "Değil mi?" (never "Sağ?")
  - "OK" / "Okay" → "Tamam" (never caps); "All right" → "Peki" or "Tamam"
  - "Come on" → "Hadi" or "Yapma" by tone
- Watch false friends of the word sense: "fall" (the event) → "düşüş", not "sonbahar"; "Miss" (title) → "Bayan", not "Kayıp".
- "OK" and "No" are never written in capitals unless shouted in the source.

## sen / siz

- Follow the sen/siz map in the film bible. Never mix both inside one sentence or one exchange.
- Defaults when the bible says nothing: family, friends, lovers and children → "sen"; court, police, doctors, strangers, staff → "siz"; adults to a child → a gentle "sen".
- A change between sen and siz must have a reason in the story (the bible notes it).

## Register

- Swearing at the same strength as the source (default). The preferences file can say "one step softer".
- Children and elderly characters speak like themselves; formal speech in court stays formal.
- Song lyrics: a short, loose paraphrase that keeps the meaning, in italics if the source is.
- Titles: "Bayan Voyter", "Bay Hartley", "Sayın Başkan", "Hâkim Bey/Hanım" (default). The preferences file can switch to "Sandra Hanım" style.

## Turkish writing

- Use correct Turkish characters: ç ğ ı İ ö ş ü. Capital of "i" is "İ", of "ı" is "I".
- Apostrophe before suffixes on proper names: "Sandra'nın", "Paris'te".
- Numbers: write small numbers as words in speech ("iki gün"), times and years in digits.
- Ellipsis as three dots "...", no space before "?" or "!".
