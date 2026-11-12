# Learn mode

Read this only when the arguments start with `learn`. SCRIPTS, CONFIG and
WORK mean what they mean in SKILL.md.

`learn <film>`: find WORK for the film (`sources.py slug`, or the `scan`
list). Run `learn.py diff --work WORK`. From `repeated_swaps` and the
edits, propose at most 5 general rules, each with its count and one
example, for instance: "You changed 'Peki' to 'Tamam' in 6 places. Always
use 'Tamam' for 'OK'?" Skip one-off fixes and rules already in the
preferences. Add to "Learned rules" only the ones the user says yes to.
Then run `learn.py done --work WORK` so the same edits are not proposed
again.
