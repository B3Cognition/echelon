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
