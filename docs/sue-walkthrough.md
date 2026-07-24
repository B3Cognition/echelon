# SUE, explained with one example (start here)

New to SUE? Read this first, then `docs/sue-usage.md` for the full reference.
Every command below runs against the tiny sample spec in
`docs/examples/leaderboard.spec.md` — copy-paste and they work.

## The one big idea

Imagine a teacher hands out project instructions, then leaves the room. Five
students read the *same* instructions, alone, and each builds their version.
If everyone builds basically the same thing, the instructions were clear. If
everyone builds something different, the instructions were secretly unclear —
even though they *looked* fine.

**That's SUE.** It doesn't check spelling or grammar. It checks whether a
requirement can be understood only one way, by handing it to several
independent AI "readers" that can't talk to each other and watching where they
disagree or get stuck. If careful readers can't agree on what a rule means,
the rule is broken — no matter how professional it looks.

## Our sample rules

`docs/examples/leaderboard.spec.md` contains, among others, these two:

> **FR-001** ("the top-5 rule"): show the top 5 players ranked by their highest score.
>
> **FR-002** ("the ban rule"): a banned player must never appear on the leaderboard.

Looks fine, right? Two hidden problems: (a) if a top-5 player is banned, does
#6 fill the empty slot, or do you show only 4 rows? Nobody wrote that down.
(b) "highest score" — best single game, or total across all games? Undefined.
Watch SUE find both.

> **Before you run anything:** each tool sends the spec's text to a model
> provider and writes its report *beside the spec* (here, into `docs/examples/`).
> The dialogue tiers are cheap enough to run on a smaller model — add
> `--model-cmd "claude --model claude-sonnet-5"` to any command to save cost.

---

## Level 1 — the quick check · `sue_challenge`

One reader asks hard questions about the rules, then tries to answer each using
**only** the text (no guessing, no common sense). Every answer gets a verdict:
`ANSWERED` (the text says it — discarded), `UNANSWERABLE` (the text never says —
a gap), or `CONTRADICTED` (the text says two different things — a clash).

```bash
python3 scripts/sue_challenge.py docs/examples/leaderboard.spec.md
```

→ writes `docs/examples/socratic-challenge.md`. You'll typically see the
banned-player backfill question come back **UNANSWERABLE** — a real hole that
would otherwise become a "why does the board sometimes show 4 rows?!" bug.
*Caveat:* it's one reader, so findings vary run to run — treat them as leads.

## Level 2 — do three readers agree? · `sue_consensus`

Three readers that never talk to each other each find problems, and SUE keeps
**only what at least 2 of them found independently.** A problem three strangers
all trip over is real; a problem only one mentions is just noise, and gets
dropped.

```bash
python3 scripts/sue_consensus.py docs/examples/leaderboard.spec.md --readers 3
```

→ writes `docs/examples/socratic-consensus.md` with a **stable findings**
section (trust these) and a sampling-noise appendix (ignore these). This is the
gate to run *before* building: fix the stable findings first.

## Level 3 — measure it with a picture · `sue_reproducibility`

Each reader turns every requirement into a little who-does-what diagram, and
SUE checks whether they all drew the **same** diagram. Crystal-clear rules →
everyone draws the same arrows → high score. Fuzzy rules → different diagrams →
SUE flags that requirement and points at the exact line that split them.

```bash
python3 scripts/sue_reproducibility.py docs/examples/leaderboard.spec.md --passes 2
```

→ writes `docs/examples/semantic-reproducibility.md` + `.json`. Read the
**measurement vector**, not one number: the *stable-low* list (requirements
that scored low in **both** passes) is the trustworthy "these reliably confuse
readers" set. `--passes 2` is what makes the per-requirement scores
trustworthy — one pass is noisy. Keep the default model here (a smaller model
is not measurement-grade for this tier).

## Level 4 — drill one gap deep · `sue_dialectic`

When one confirmed gap really matters, SUE interrogates it like a lawyer with a
witness — one sharp follow-up at a time, each building on the last answer —
until it reaches a verdict.

```bash
python3 scripts/sue_dialectic.py docs/examples/leaderboard.spec.md \
  --lens theaetetus --target FR-002 \
  --seed "how the system detects that a player is banned, given FR-001 promises the top 5 and FR-002 removes banned players"
```

→ writes `docs/examples/socratic-dialogue.md`. Likely terminal state:
`APORIA_UNDEFINED` — "the rulebook has no answer here, and we proved it." Pick
the lens by defect type (`theaetetus` = claims with no evidence, `parmenides` =
contradictions, `philebus` = missing numeric bounds, … full table in
`docs/sue-usage.md`).

## A little Plato — the rules of the Socratic dialogue

Level 4 isn't decoration. It really is Socrates' method, turned into a machine.
Here's the idea and the rules, then the nine "lenses" you can pick from.

### Who Socrates was, and what "elenchus" means

Socrates walked around Athens asking people to define things they were sure
they understood — *what is justice? what is courage? what is holiness?* He
never lectured. He only asked questions, and his questions kept exposing that
the confident expert couldn't actually say what he meant. That method of
question-and-refutation has a name: **elenchus**. SUE runs an elenchus against
a specification.

### The three rules that make it Socratic (not just Q&A)

1. **SUE only asks. The spec only answers.** SUE never states an opinion about
   the rule; it poses one question per turn. The "answering voice" must reply
   using **only the specification's own words** — exactly like Socrates forcing
   an opponent to commit to *their own* statements, not to outside knowledge.
2. **Each question is chosen by the last answer.** The dialogue is a little
   state machine: the previous answer's verdict (did the text support it,
   partly, not at all, or contradict itself?) decides the next question. That
   decision table is the **lens** — see below.
3. **The honest ending is often "we don't know."** Most real Platonic dialogues
   don't end with an answer — they end in **aporia** (Greek for *impasse*): the
   proof that the interlocutor never actually knew what he claimed to know. For
   a spec that's not failure — it's the finding. "We proved the rulebook has no
   answer here" is exactly what you want to learn *before* building.

### The eight moves

Every lens is built from the same eight question-types (Socrates' toolkit):
**DEFINE** (state the essence), **DISTINGUISH** (separate the real definition
from mere examples), **CAUSE_OR_CRITERION** (give the test to recognize it),
**COUNTEREXAMPLE** (find a case that fits the words but breaks the meaning),
**FOLLOW_CONSEQUENCE** (assume it's true — what must follow?), **TEST_OPPOSITE**
(assume the opposite — what breaks?), **DIVIDE** (split into the distinct
cases), **REVISE** (repair a broken understanding).

### The nine lenses (each is a real Plato dialogue)

A *lens* is just which move to start with and how to react to each answer —
named after the dialogue whose style it imitates. Pick the lens by the *kind*
of defect you're chasing.

- **euthyphro** — *In the dialogue,* Socrates asks Euthyphro "what is holiness?"
  and Euthyphro keeps offering examples ("what I'm doing right now") and circles
  ("what the gods love"), never an essence. *SUE move:* demand a real definition,
  reject examples-as-definition. *Reach for it when:* a term is undefined or
  defined in a circle. (Leaderboard: is "highest score" ever actually defined?)
- **meno** — *Meno can't say what virtue is, raising the paradox: how would you
  even recognize the answer if you found it?* *SUE move:* demand the criterion by
  which you'd verify the thing. *When:* a requirement can't be tested — QA
  couldn't tell pass from fail.
- **parmenides** — *The dialogue drills a claim by working out the consequences
  of it AND of its negation ("if the one is… if the one is not…").* *SUE move:*
  follow what the claim commits the text to, then test the opposite. *When:* you
  suspect two rules quietly clash.
- **cratylus** — *A debate about names: are words stable, or does meaning drift?*
  *SUE move:* check that one name means one thing throughout. *When:* the same
  idea is called two names, or one name covers two ideas.
- **theaetetus** — *"What is knowledge?" — tested as "true belief plus an
  account." A claim without a justification isn't knowledge.* *SUE move:* ask
  whether the text can actually justify a stated claim. *When:* a rule asserts
  something the spec never grounds. (This is the lens that drilled the Opta
  accuracy metric to APORIA_UNDEFINED.)
- **sophist** — *Socrates hunts the sophist by "division" — repeatedly splitting
  a category to separate the look-alike from the real thing.* *SUE move:* divide
  into cases and test the supposedly-excluded one. *When:* a boundary or
  exception is missing.
- **gorgias** — *Gorgias the rhetorician can persuade about anything without
  knowing it; Socrates calls rhetoric flattery, not an art.* *SUE move:* if a
  confident-sounding claim commits the text to nothing checkable, it's rhetoric,
  not a requirement — never "resolved." *When:* the text sounds authoritative but
  says nothing you could implement.
- **republic** — *Justice is "each part doing its own proper work" — the right
  role in the right place.* *SUE move:* check who is permitted to do what. *When:*
  a permission or actor rule is fuzzy (the FR-001-style "who may do X").
- **philebus** — *The good life needs "limit" imposed on "the unlimited" — measure
  over the boundless.* *SUE move:* demand the numeric bound. *When:* a constraint
  says "fast" / "large" / "soon" with no number. (Leaderboard NFR-001 says "within
  2 seconds" — good; a rule that just said "fast" would fail here.)

### How a dialogue ends (the terminal states)

- **RESOLVED** — the claim survived counterexample and consequence tests,
  sharpened rather than refuted. (Rare — as in Plato.)
- **APORIA_UNDEFINED** — no stable definition or criterion can be built from the
  text. (Euthyphro's actual ending: they never do define holiness.)
- **APORIA_CONTRADICTED** — the text supports two incompatible answers.
- **APORIA_UNDERDETERMINED** — more than one equally valid reading survives.
- **BOUNDED_STOP** — hit the turn limit; a safety cap, **not** a verdict.

### Try it on the leaderboard, three ways

```bash
# "highest score" is never defined → definition lens
python3 scripts/sue_dialectic.py docs/examples/leaderboard.spec.md \
  --lens euthyphro --target FR-001 \
  --seed "what the specification defines a player's 'highest score' to be"

# top-5 rule vs ban rule may clash → consequences-and-opposite lens
python3 scripts/sue_dialectic.py docs/examples/leaderboard.spec.md \
  --lens parmenides --target FR-002 \
  --seed "whether the top-5 rule (FR-001) and the ban rule (FR-002) can both hold when a top-5 player is banned"

# is the ban rule even checkable? → criterion lens
python3 scripts/sue_dialectic.py docs/examples/leaderboard.spec.md \
  --lens meno --target FR-002 \
  --seed "the criterion by which the system recognizes that a player is banned"
```

Each writes `docs/examples/socratic-dialogue.md` — a full, auditable transcript:
every question, the text-only answer with cited lines, and the terminal verdict.

## Bonus — whole-spec conflict map · `sue_jgraph`

Each reader builds one claims-and-conflicts graph of the whole spec in a single
pass; trust the contradictions that ≥2 readers find independently.

```bash
python3 scripts/sue_jgraph.py docs/examples/leaderboard.spec.md --readers 3
```

→ writes `docs/examples/justification-graph.md`.

---

## The one unified command · `sue_auto`

Don't want to run five tools by hand and pick seeds and lenses yourself? This
does the whole thing robotically — runs the tiers, auto-selects the drill seeds
and lenses from what the earlier tiers found, and writes **one** dossier with a
severity-ranked, fix-ready summary. It only diagnoses; it never edits the spec.

```bash
# The default: v2 consensus → v3 measurement → up to 3 auto-selected drills
python3 scripts/sue_auto.py docs/examples/leaderboard.spec.md

# Fast triage (just Level 1, ~2 model calls):
python3 scripts/sue_auto.py docs/examples/leaderboard.spec.md --profile lite

# Everything, including the conflict map and up to 8 drills:
python3 scripts/sue_auto.py docs/examples/leaderboard.spec.md --profile forensic
```

→ writes `docs/examples/sue-dossier.md` (+ `.json`). The individual tool
reports are still written beside it; the dossier links them and puts the
must-fix items on top. Model policy is baked in — dialogue tiers on a smaller
model, the measurement on the default — so you don't pass model flags at all.

---

## What you walk away with

For two innocent-looking rules, SUE produces a concrete, confirmed to-do list:

1. **Confirmed gap** (readers agreed): decide what fills a banned player's slot
   — backfill with #6, or show fewer rows.
2. **Measured fracture** (the diagrams split): define "highest score" — best
   single game vs. total.
3. **Deep finding** (drilled): the top-5 rule and the ban rule can't both be
   guaranteed until "banned" is defined and detectable.

None of that is about typos. It's about *meaning* being unclear — the stuff
that turns into arguments and bugs months into building. SUE's whole trick:
hand the same rule to several careful readers who can't collude, and let their
disagreements show you exactly where the rule is secretly fuzzy.

> Example outputs above are illustrative — findings are model-sampled and will
> vary between runs. That variation is the point: the parts that show up every
> time (v2 stable findings, v3 stable-low, drill aporias) are the real ones.
