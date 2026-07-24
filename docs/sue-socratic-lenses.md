# SUE Socratic Lenses — Reference

Deep reference for `sue_dialectic.py` (Level 4 in `docs/sue-walkthrough.md`).
The walkthrough gives the plain-English version; this file is the full account —
the method, the eight moves with their **exact** question templates, the nine
Platonic lenses, and how to read a transcript. Descriptions of the dialogues are
faithful but compressed: each lens *imitates the characteristic move* of its
dialogue, it does not reproduce the whole argument.

## The method: an elenchus as a state machine

A `sue_dialectic` run is one **elenchus** — Socratic cross-examination — turned
into a deterministic machine:

- **SUE asks; the specification answers.** SUE never asserts anything about the
  requirement. It poses one templated question per turn. The answering voice is a
  model constrained to reply **using only the specification text**, citing line
  numbers, exactly as Socrates forces an interlocutor to commit to their own words.
- **The answer's verdict picks the next question.** Every answer is graded
  `SUPPORTED` / `PARTIAL` / `SILENT` / `CONTRADICTED`. That verdict, fed through
  the chosen lens's transition table, selects the next move. Questions are
  deterministic; only the answers are model-sampled.
- **A `REVISE` budget of 1.** An understanding may be repaired once; a second
  needed repair is treated as unrepairable and ends in aporia.
- **Aporia is the finding, not a failure.** As in Plato, most genuine dialogues
  end at an impasse that proves the claim was never actually grounded. For a spec
  that is the result you want *before* building.

## The eight moves (verbatim question templates)

Every lens is assembled from these eight operators. `X` = the focus term/claim,
`Y` = the current understanding, `Z` = the recorded failure — SUE fills them in.

| Move | Question template |
|---|---|
| **DEFINE** | *What exactly does the specification define "X" to be? State the definition the text commits to, citing its lines. If the text gives only examples or usages, say so.* |
| **DISTINGUISH** | *What distinction does the text itself draw between a definition of "X" and mere examples or related notions — and where?* |
| **CAUSE_OR_CRITERION** | *By what criterion in the text would one recognize or verify "X"? Cite the lines that establish the criterion.* |
| **COUNTEREXAMPLE** | *Construct, from the specification text alone, a case that satisfies the text's own words yet violates the current understanding: Y. If the text supports no such case, say so.* |
| **FOLLOW_CONSEQUENCE** | *Assume the current understanding holds: Y. What consequences does the specification text then commit to? Cite lines; note any consequence the text elsewhere denies.* |
| **TEST_OPPOSITE** | *Assume the opposite of the current understanding: NOT (Y). Which lines of the text would then be violated, if any? If the text tolerates the opposite reading, say so.* |
| **DIVIDE** | *Split "X" into the distinct cases the text itself treats differently. Enumerate the cases with their lines.* |
| **REVISE** | *The current understanding failed: Z. Can the text itself supply a corrected understanding of "X"? State the revision with cited lines, or say the text cannot.* |

One refinement runs across every lens: a `DEFINE` answered only with **examples**
(not an essence) is routed to `DISTINGUISH` even when the examples are supported —
the core Euthyphro lesson that examples are not a definition.

## The nine lenses

Each lens = a **starting move** + a reaction table named after the dialogue whose
style it imitates. Pick by the *kind* of defect you are chasing.

### euthyphro — definition / essence · starts at DEFINE
*The dialogue:* Socrates asks Euthyphro to define holiness; Euthyphro answers with
examples ("what I am doing now — prosecuting a wrongdoer") and a circle ("holy = what
the gods love"), never an essence, and the dialogue ends without a definition.
*Drills:* undefined or circular terms. *When:* a key noun is used but never pinned down.
*Seed example:* `"what the specification defines a player's 'highest score' to be"`.

### meno — criterion of recognition · starts at CAUSE_OR_CRITERION
*The dialogue:* "Can virtue be taught?" founders because Meno can't say what virtue *is*,
raising Meno's paradox — how do you recognize the answer if you don't already know it?
*Drills:* unverifiable requirements. *When:* QA could not tell pass from fail.
*Seed example:* `"the criterion by which the system recognizes that a player is banned"`.

### parmenides — consequence and its negation · starts at FOLLOW_CONSEQUENCE
*The dialogue:* the elder Parmenides trains young Socrates by working out the
consequences of a hypothesis *and* of its negation ("if the one is… if the one is not…").
*Drills:* contradictions and tolerated opposites. *When:* two rules may quietly clash.
*Seed example:* `"whether the top-5 rule and the ban rule can both hold when a top-5 player is banned"`.

### cratylus — naming / stability · starts at DISTINGUISH
*The dialogue:* are names natural or merely conventional? — a debate about whether words
carry stable meaning. *Drills:* vocabulary drift. *When:* one idea wears two names, or one
name covers two ideas. *Seed example:* `"whether 'active player' and 'player' name the same set"`.

### theaetetus — knowledge as justified account · starts at CAUSE_OR_CRITERION
*The dialogue:* "What is knowledge?" tests "true belief + an account (logos)" and shows a
claim with no account isn't knowledge. *Drills:* claims the text never justifies. *When:*
a rule asserts something the spec cannot ground. *This lens drilled the Opta placement-accuracy
metric to APORIA_UNDEFINED.* *Seed example:* `"the property that makes an event 'unambiguous' for the accuracy measurement"`.

### sophist — division / look-alikes · starts at DIVIDE
*The dialogue:* the sophist is hunted by *diairesis* — repeatedly dividing a category to
separate the counterfeit from the real, and confronting "non-being." *Drills:* missing
boundaries and exceptions. *When:* an edge case or excluded case is unstated.
*Seed example:* `"the cases the text treats differently when a score is exactly zero"`.

### gorgias — rhetoric vs substance · starts at FOLLOW_CONSEQUENCE
*The dialogue:* Gorgias can persuade about anything without knowing it; Socrates calls
rhetoric flattery, not an art. *Drills:* persuasive-but-thin text — a confident claim that
commits the spec to nothing checkable is rhetoric, never `RESOLVED`. *When:* the text sounds
authoritative but yields no implementable obligation. *Seed example:* `"what observable behaviour the phrase 'seamless experience' commits the system to"`.

### republic — role separation · starts at DISTINGUISH
*The dialogue:* justice is "each doing their own proper work" — the right part in the right
role. *Drills:* permission and actor defects. *When:* who-may-do-what is fuzzy.
*Seed example:* `"which actors are permitted to reset another player's score"`.

### philebus — measure over the unlimited · starts at DEFINE
*The dialogue:* the good life is a mixture in which *limit* (peras) is imposed on *the
unlimited* (apeiron) — the good needs measure. *Drills:* unquantified constraints. *When:* a
requirement says "fast" / "large" / "soon" with no number. *Seed example:* `"the numeric bound the text places on 'loads quickly'"`.

## How a dialogue ends (terminal states)

| Terminal | Meaning |
|---|---|
| `RESOLVED` | The understanding survived counterexample and consequence tests — sharpened, not refuted. Rare, as in Plato. |
| `APORIA_UNDEFINED` | No stable definition or criterion can be built from the text. (Euthyphro's real ending.) |
| `APORIA_CONTRADICTED` | The text supports incompatible answers and cannot repair them. |
| `APORIA_UNDERDETERMINED` | More than one equally valid reading remains. |
| `BOUNDED_STOP` | The turn limit (`--max-turns`, default 7) was reached — a safety cap, **not** a verdict. |

A `⚠ RETENTION` flag on a turn marks a repair that abandoned the evidence lines it
had previously relied on — a revision that "moved the goalposts," surfaced rather
than silently accepted.

## Choosing a lens

| If the suspected defect is… | Reach for |
|---|---|
| a term used but never defined, or defined circularly | `euthyphro` |
| a requirement with no way to test pass/fail | `meno` |
| two rules that might contradict | `parmenides` |
| the same thing named inconsistently | `cratylus` |
| a claim the spec asserts but never grounds | `theaetetus` |
| a missing edge case, exception, or boundary | `sophist` |
| confident wording that commits to nothing checkable | `gorgias` |
| a fuzzy permission / who-does-what rule | `republic` |
| a constraint with no number ("fast", "large") | `philebus` |

Take the **seed** from a v2 stable finding or a v3 stable-low unit — do not invent
one. `sue_auto` picks the lens automatically from the finding's verdict and wording.

## Reading a transcript

`socratic-dialogue.md` records, per turn: the operator, the templated question,
the text-only answer, the cited evidence lines, and the running "claim now."
The header states the lens, seed, target, turn count, retention-flag count, and
terminal state with its meaning. The `.json` sidecar mirrors it for tooling.

```bash
python3 scripts/sue_dialectic.py <spec.md> --lens <lens> \
  --seed "<claim or term, from a v2/v3 finding>" [--target <ID>] \
  [--max-turns 7] [--model-cmd "claude --model claude-sonnet-5"]
```
