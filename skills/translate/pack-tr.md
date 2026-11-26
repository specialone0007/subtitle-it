# Turkish language pack

Rules every translator and reviewer follows. The source can be any
language; the target is always Turkish. The user's preferences file can
override the defaults marked "(default)".

## Readable in one glance

The viewer reads each cue in about two seconds while watching. A line
that is right but slow to read is a bad subtitle.

- Say the same thing in fewer, plainer words. Reshape the sentence for clarity (Netflix Turkish style guide, I.22): split a nested clause, use an active verb instead of a passive or a noun made from a verb, put the point first.
- Keep everything that is said: facts, names, jokes, threats and swearing strength. Cut only what carries nothing: hesitations, false starts, "you know", "I mean", a word said twice. Never summarise a line into something blander.
- Meaning comes before reading speed. Aim for 17 characters a second or less (I.17); the check warns about every cue above that. Shorten only by rephrasing or by dropping filler. Never drop a clause, a question, a name, a second sentence or a stance word (want, can, must, try, maybe, still, never: `istiyor musun` is not `-ecek misin`) to reach the speed. A fast line that keeps the whole meaning stays as it is, and its warning stays: a lost clause is a mistranslation, a fast line is not.
- A word or phrase the same speaker repeats in a row is written once (I.18): "Come on. Come on." → "Hadi." Keep the repeat when it carries the scene (a chant, a count, someone pointing at things one by one).
- Sounds alone ("Oh.", "Hmm?", "Uh...") are already left out of your chunk. Inside a line, drop them too: "Oh, I didn't know." → "Bilmiyordum." Keep a sound that means something the audience may not catch: "Ouch!" → "Ah!", "Yuck." → "Iyy."
- A yes or no said as a sound ("Uh-huh.", "Mm-hmm.", "Nuh-uh.") that answers something is written as the word: "Evet.", "Hı hı.", "Hayır." (II.9).

Before → after:

- "Bütün kürek çekmeyi ben yapmıyorum." → "Hep ben kürek çekecek değilim."
- "Ağların onarılmış olarak geri getirilmesini rica ederim." → "Ağları onarıp getirirseniz sevinirim."
- "Durun, bekleyin. Elinizi verin." → "Dur. Ver elini."
- "Güvertede sizden kimse kaldığını sanmıyordum." → "Güvertede kimse kalmadı sanıyordum."

## Meaning before words

- Write natural spoken Turkish, the way people in the scene would talk. Never word for word: an English sentence shape in Turkish words is a calque, rewrite it. "How Turkish people say it" below gives the test.
- A sentence that runs over 2, 3 or more cues is translated as one sentence first, then spread back over those same cues so each part appears exactly once: no part written twice, no cue left with nothing of its own, and a name in the cue where it is said. Turkish word order often moves the verb to the last cue; that is fine. The check warns about such a group as `split sentence`.
- Slang and idioms are translated by their meaning, never word for word: the bible's "Slang and idioms" section gives what each one means in this film ("lemon" = a car that keeps breaking down, "a rain check" = another time).
- When the source language and the English disagree, the source language wins. English is a cross-check for meaning and for who speaks.
- Keep names as written in the source. Do not translate place names that have no common Turkish form.

## How Turkish people say it

A line can be right word by word and still sound like a translation. The
test for every line: say it out loud as this character, in this scene, to
these people. If a Turkish viewer would notice that someone translated it,
rewrite it, keeping everything said. Three principles:

1. **Say what the scene means, from where the speaker stands**: who is where, who moves towards whom, what is happening. "Shoot! I forgot the keys." → "Hay aksi! Anahtarları unuttum.", not "Ateş et!".
2. **Keep what the speaker does with the line**: the stance, the attitude, who it is aimed at. "Nice of you to show up." (to someone late) → "Nihayet gelebildin.", not "Gelmen çok hoş."
3. **Say a known thing the known way**: fixed word pairs, sayings, everyday names, how people answer a call. "Better late than never." → "Geç olsun, güç olmasın."

- The word people use, not the first dictionary word: an offering to a god is an "adak", not a "sunu". A word most viewers would stop to think about is wrong, even when it is in the dictionary.
- English grammar words do not carry over. "a/an" is "bir" only when it means one, some, any or a new one, never a possessive: "I've already lost a father" → "Babamı zaten kaybettim". Drop "my", "your", "I" and "you" where the ending already says them, unless stressed.
- Hear the word as daily speech hears it: "O benim partnerim" is heard as a lover (for work: "O benim ortağım"). Small words carry a shade: "ancak" says barely enough.
- Words fit the film's world (the bible's "World and register"): no word whose tone belongs to another religion, period or culture.
- A line the film says again (a chant, a saying, a line thrown back) is said the same way each time (`repeat drift`). A stock phrase anyone says ("Come on!", "Thank you.") is not one: word it for its scene. A line the bible says is said word for word is always one (`bible repeat`).

English habits that give a translation away, one per line:

- "And" opening a line is not "Ve": drop it, or say "Hadi", "Bir de", "-da/-de" (the check warns: `ve opening`).
- "I'm sorry" is "Üzgünüm" only for grief; an apology is "Kusura bakma", "Özür dilerim".
- A passive or a noun made from a verb: say who does it ("Geride bıraktıklarımız için", not "Geride bırakılanlar için").
- "so that", "he says that", "the one who": use a plain verb, "diye" or "-mış".
- An idiom put word for word: find the Turkish one ("That ship has sailed" → "İş işten geçti").
- "Yes" and "no" answer the meaning: "I don't know." "Yes, you do." → "Biliyorsun."
- "as a" is often "gibi": "Live as a king" → "Kral gibi yaşa".
- "they" or a plural for things: "They wake me up" (the ship horns) → "Beni uyandırıyor".
- A tense copied from English: a proposal is "Ya gitsek?", not "Ya gitseydik?".
- "Evet, efendim" for every "Yes, sir": take the title the bible gives the pair.

## Form of each cue

- At most 2 lines per cue, at most 42 characters per line, whatever the source has.
- Keep `- ` dialogue dashes: same number of dash lines as the source cue, one speaker per dash line. A `- ` that opens a cue right after a cue ending with ` -`, and goes on in lower case, is not a dash: Danish, Norwegian and Swedish files mark a sentence that runs on into the next cue that way. Leave it out, or start the cue with `...`. In a cue with two speakers, each speaker's turn is one line. A turn too long for one line is still written; the delivery step then splits the cue into one cue per speaker when the time allows, and otherwise the cue comes back to be shortened.
- No speaker labels (`NAME:`, `[Name]`) and no sound descriptions (`[kapı çarpar]`, `(iç çeker)`), even when the source has them. The automatic check fails square brackets in any cue, and a label or a description in parentheses in a cue whose source had tags. Parentheses the source uses as speech (`(Orada mısın?)`) and headings such as `BÖLÜM 1:` stay. Song lines keep their `♪` (see Songs below).
- Keep `<i>` and `</i>` exactly where the source has italics (voices off screen, songs, phone, thoughts). No italics where the source has none, except on a song (see Songs below). Italics on a single word of an otherwise plain line (`<i>To</i> all the harbour crews`) are mostly a slip in the source file: leave them out unless that word is really stressed, and never put them on another Turkish word.
- No stray byte-order marks and no `{\an8}` style tags, even where the source has them: every line stays at the bottom of the screen, and the delivery removes such tags.
- Break a two-line cue where the sentence breaks, so each line reads as one piece (I.12):
  - after a full stop, a question mark or a comma first; otherwise before a conjunction ("ve", "ama", "çünkü", "yoksa"), never after it;
  - never between a noun and its adjective, its possessor or "bir" ("kırmızı / araba", "Ali'nin / evi", "bir / şey");
  - never start the second line with a word that leans on the word before it: a postposition ("gibi", "diye", "kadar", "için", "ile", "göre", "değil") or a particle ("de", "da", "ki", "mi", "mısın", "mıydı");
  - never leave one word alone on a line, unless it is a whole sentence ("Hayır.").

  "Senin / gibi biri gelmedi." → "Senin gibi biri / gelmedi." · "Söyledim ama / dinlemedin." → "Söyledim / ama dinlemedin." The delivery step rewraps a cue whose break reads badly when a better break fits.
- Never merge or split cues yourself, never leave one empty. Every cue number in your chunk gets text. Only the delivery step splits a two-speaker cue, as above.

## Grammar traps

- Commands stay commands: "Come." → "Gel.", "Stop!" → "Dur!", "Let's go." → "Hadi gidelim." Never the -mak/-mek form ("Gelmek.").
- Fillers by meaning, never by dictionary:
  - "Well..." → "Şey..." or "Peki..." (never "Kuyu")
  - "So..." → "Yani..." or "Eee..." (not "Bu yüzden" unless it really means "therefore")
  - "Right?" → "Değil mi?" (never "Sağ?")
  - "OK" / "Okay" → "Tamam" (never caps); "All right" → "Peki" or "Tamam"
  - "Come on" → "Hadi" or "Yapma" by tone
- Watch false friends of the word sense: "spring" (the coil) → "yay", not "ilkbahar"; "Miss" (title) → "Bayan", not "Kayıp".
- "OK" and "No" are never written in capitals unless shouted in the source.

## sen / siz

- Follow the sen/siz map in the film bible: each pair's usual form, and the scenes where it shifts. Never mix both inside one sentence or one exchange.
- Defaults when the bible says nothing: family, friends, lovers, children, and adults of about the same age who talk at ease (working side by side, joking, sharing a quiet moment) → "sen"; court, police, doctors, staff, officials, a first contact that is formal or wary, and clear respect shown to someone much older → "siz"; adults to a child → a gentle "sen".
- siz in a teasing or tender moment between people already at ease sounds wrong in Turkish. Use it there only when the bible gives a reason (respect for an elder kept even in jokes, a cold distance the scene means).
- A pair can speak unequally (a young man says siz to an old man who says sen to him). Keep that only where the bible says so.
- A change between sen and siz must have a reason in the story (the bible notes it).

## Register

- Swearing at the same strength as the source (default). The preferences file can say "one step softer".
- Children and elderly characters speak like themselves; formal speech in court stays formal.
- Song lyrics: see Songs below.
- Titles: "Bayan Vale", "Bay Hartley", "Sayın Başkan", "Hâkim Bey/Hanım" (default). The preferences file can switch to "Mara Hanım" style.

## Songs

Only songs that carry the story reach your chunk; the rest are left out
before translation (Netflix Turkish style guide, I.20). For a song you do
get:

- A short, loose paraphrase that keeps the meaning; a rhyme is welcome, never at the cost of the meaning.
- In italics, with `♪` and a space at the start and at the end of each cue: `<i>♪ Fener yanıyor kıyıda ♪</i>`. In a musical (the bible says so) no `♪` at all: the italics alone; the delivery removes any left.
- Each lyric line starts with a capital letter. No comma or full stop at the end of a line; only `?` and `!` may end one.
- A song title goes in quotation marks.
- When the song goes on under the next dialogue, end the last lyric line you write with `...`.
- Dialogue always wins over a song in the same cue.

## Family words

Turkish names the side of the family that English leaves open (I.22). "Uncle" is "amca" (father's brother) or "dayı" (mother's brother); "aunt" is "hala" (father's sister) or "teyze" (mother's sister); "brother" is "abi" (older) or "kardeş" (younger, or when the age is not known); "sister" is "abla" or "kardeş"; "grandma" is "anneanne" (mother's mother) or "babaanne" (father's mother).

- Use the word the film bible gives for each relation, older or younger included: when the bible says a brother is the older one ("abi"), he is "abi" in every cue, never "ağabey" in one and "kardeş" in another. When the bible says nothing and the film does not show the side, take the more common word ("amca", "teyze", "kardeş") and keep it for the whole film.
- "Abi" and "abla" are also what a younger speaker calls an older one, family or not; "amca" and "teyze" are what a child calls any older adult. Use them where the scene sounds like that, not as a translation of a name.

## Turkish writing

- Use correct Turkish characters: ç ğ ı İ ö ş ü. Capital of "i" is "İ", of "ı" is "I".
- Write the circumflex wherever it changes the meaning or the sound (I.22): "hâlâ" (still) vs "hala" (aunt), "âşık" (in love) vs "aşık", "kâr" (profit) vs "kar" (snow), "hâl" (state) vs "hal" (market hall), "resmî", "millî", "dinî" (the adjective forms). The check warns about a plain "hala" or "aşık" it finds; a "hala" that really means aunt stays.
- Apostrophe before suffixes on proper names: "Mara'nın", "Paris'te". The suffix follows how the name sounds, not how it is spelled: "Casey" ends in an "i" sound, so "Casey'nin", "Casey'yi", "Casey'ye", never "Casey'in"; "Ray" ends in a consonant sound, so "Ray'in". The check warns about a suffix that does not fit (`name suffix`).
- One spelling per word for the whole film, as the TDK writes it: "sağ ol", "her şey", "bir şey", "bir arada", "şu an", "ya da", "yine de", "birçok", "hiçbir", "herhangi", "yalnız", "yanlış", "pekâlâ". Pick one of two accepted forms ("abi" or "ağabey") and keep it. The check warns about the common slips (`spelling`) and about a second form of a word (`term drift`).
- One Turkish rendering for each term the bible decides, in every cue that says it, every word of it, with any ending (`term rendering` when a cue lacks a word of it). A title or rank the bible names ("Deputy" → "Şerif Yardımcısı") counts on the cues the bible cites for it, and a rendering the bible gives only in its text ('"blockade" → "abluka"') counts as well.
- Numbers: write small numbers as words in speech ("iki gün"), times and years in digits.
- Ellipsis as three dots "...", no space before "?" or "!".
