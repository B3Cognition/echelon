# Cognitive Squad — Cookbook

A step-by-step guide for common scenarios. Copy-paste the commands. Follow the order.

---

## Recipe 1: New Project From Scratch (Greenfield)

You have an idea. No code exists yet.

```
Step 1: Initialize spec-kit project
────────────────────────────────────
$ mkdir my-project && cd my-project
$ specify init my-project --ai claude

Step 2: Run the squad
────────────────────────────────────
> /speckit.squad.run "Build a task management API with user auth, teams, projects, and real-time notifications"

What happens:
  DISCOVER  → researches the domain, finds reference architectures
  WHY₁      → challenges assumptions ("what auth provider? what real-time tech?")
  WHAT      → writes spec with testable requirements
  WHY₂      → validates spec (31 metrics — may reject and loop)
  ASSESS    → estimates effort, classifies features (must-have vs nice-to-have)
  HOW       → selects tech stack, writes ADRs
  PLAN      → creates tasks with critical path

  Time: ~15-30 minutes
  Output: .specify/specs/001-task-management/

Step 3: Review what the squad produced
────────────────────────────────────
Read these files:
  spec.md           ← requirements (check: do they match your intent?)
  plan.md           ← architecture (check: tech stack OK?)
  estimates.md      ← effort (check: realistic for your team?)
  tasks.md          ← task breakdown (check: ordering makes sense?)
  feasibility.md    ← can this be built? (check: any kills/defers?)
  quality-gates.md  ← spec quality scores (all should be green)

Step 4: Build it
────────────────────────────────────
> /speckit.squad.build 001-task-management

What happens per task:
  IMPLEMENTER  → writes code (TDD)
  SPEC GUARD   → checks: does code match the spec?
  CODE REVIEWER → checks: quality, security, ADR compliance
  TEST GUARDIAN → checks: are tests sufficient?

Step 5: Verify nothing was missed
────────────────────────────────────
> /speckit.squad.verify

What happens:
  VERIFICATION scans EVERY requirement against the codebase.
  If gaps → creates rework tasks → loops until 100%.

Step 6: After deployment — close the learning loop
────────────────────────────────────
> /speckit.squad.feedback 001

Answer questions about what actually happened:
  - How long did it really take vs estimated?
  - Which architecture decisions held up?
  - What requirements were missing?
  → Updates calibration for next project
```

---

## Recipe 2: Modernize an Existing Codebase (Brownfield)

You have a legacy system. You want to rewrite/modernize it.

```
Step 1: Point the squad at your codebase
────────────────────────────────────
> /speckit.squad.run /path/to/legacy-codebase

What happens:
  DISCOVER uses reverse-eng to analyze:
    - Directory structure
    - Dependencies
    - Git history (hotspots, contributors)
    - Config files
    - Language/framework detection
  Then maps: domain glossary, boundaries, assumptions, unknowns

Step 2: SCIENTIST investigates unknowns
────────────────────────────────────
The squad auto-dispatches SCIENTIST for testable questions:
  - "Does the API support modern protocols?" → empirical test
  - "Are legacy data formats still evolving?" → git history analysis
  - "What percentage uses the old vs new pattern?" → codebase grep

Step 3: Same flow as greenfield from here
────────────────────────────────────
WHY validates → WHAT writes spec → ASSESS estimates → HOW designs → PLAN breaks down

The difference: all decisions are GROUNDED in what the codebase actually contains,
not what documentation says it contains.
```

---

## Recipe 3: Handle a Spec Change Mid-Build

Requirements changed. It happens.

```
> /speckit.squad.change "FR-AUTH-003 now requires OAuth2 instead of API keys. The client changed their security requirements."

What happens:
  CHANGE CONTROLLER:
    1. Impact analysis → which tasks affected? which code needs rework?
    2. Re-validates changed requirement through WHY
    3. Re-estimates affected tasks through ASSESS
    4. Marks completed tasks as NEEDS_REWORK
    5. Updates traceability matrix

  Output: change-impact-report.md
    - 3 tasks need rework
    - 1 ADR invalidated
    - Estimated impact: +4 days
    - Critical path affected: yes

  Then: IMPLEMENTER reworks affected tasks → SPEC GUARD re-validates
```

---

## Recipe 4: "I'm Stuck" — Get Fresh Ideas

The architecture feels wrong. You're going in circles.

```
> /speckit.squad.innovate "The current API design feels over-engineered. Are there simpler approaches?"

What happens:
  INNOVATE applies:
    - First Principles: strip assumptions, rebuild from fundamentals
    - TRIZ: what contradiction exists? what inventive principle applies?
    - Blue Ocean: what would a competitor do differently?

  Output: alternatives.md
    - Option A: (description, pros, cons, risk level)
    - Option B: (description, pros, cons, risk level)
    - Option C: (description, pros, cons, risk level)

  Then: WHY + ASSESS evaluate each alternative
```

---

## Recipe 5: Research Before Deciding

You need evidence, not opinions.

```
> /speckit.squad.investigate "Should we use GraphQL or REST for the public API? We expect 10K concurrent users."

What happens:
  SCIENTIST follows the scientific method:
    1. RESEARCH → searches docs, papers, benchmarks
    2. EVALUATE → grades each source (A=peer-reviewed, B=official docs, C=blog, D=forum, E=AI training data)
    3. HYPOTHESIZE → "GraphQL reduces over-fetching but adds server complexity"
    4. EXPERIMENT → scaffolds a minimal prototype, benchmarks both
    5. RECOMMEND → confidence-scored conclusion with evidence

  Output: investigation/graphql-vs-rest.md
    Recommendation: REST (confidence: 0.75)
    Evidence: B (official benchmarks show REST handles 10K concurrent with less memory)
    Caveat: If client needs vary widely, GraphQL at 0.60 confidence
```

---

## Recipe 6: Check Progress

```
> /speckit.squad.status

Output:
  Run: squad-001
  Phase: BUILD (Phase 3 of 5)
  Tasks: 23/67 complete
  Quality: CPI 0.92, SPI 0.88 (slightly behind schedule)
  Coverage: 34% of requirements implemented
  Alerts: none
  Last agent: IMPLEMENTER completed T-023
```

---

## Recipe 7: Reality-Check Your Plan

Before committing to a timeline, get a grounded estimate.

```
> /speckit.squad.ground

What happens:
  GROUND:
    - Compares your estimates to similar past projects
    - Checks architecture decisions against real-world production data
    - Applies Kahneman's reference class forecasting (outside view)
    - Flags disconnects between plan and reality

  Output: reality-check.md
    "Your estimate of 12 weeks is in the 30th percentile for similar projects.
     Industry median is 18 weeks. Recommend budgeting 16-20 weeks."
```

---

## Recipe 8: After Deployment — Make the Squad Smarter

This is the most important step. It closes the learning loop.

```
> /speckit.squad.feedback 001

The squad asks:
  - Actual effort vs estimated?
  - Which architecture decisions held up in production?
  - Which requirements were missing or wrong?
  - What risks materialized?
  - What tests caught real bugs? What didn't?

  → Updates:
    - calibration-profile.yaml (accuracy per domain)
    - estimates-log.yaml (predicted vs actual)
    - patterns.yaml (what worked)
    - pitfalls.yaml (what failed)

  Next run: ASSESS uses this data for better estimates.
  Next run: WHY knows which areas the squad historically gets wrong.
  Next run: The squad is measurably better.
```

---

## Common Patterns

### "I want the squad to be more thorough"
Increase iterations: edit `squad-config.yml` → `analysis.max_iterations: 7`

### "I want the squad to be faster"
Decrease specialist count: `specialists.max_active: 2`

### "I want to skip understanding and just build"
Don't. That's the whole point. But if you must:
`/speckit.squad.build 001-feature` works on any existing spec-kit artifacts.

### "The squad keeps rejecting my spec"
Good — that means WHY is doing its job. Read `issues.md` for specific fixes. The most common issues:
- Testability too low → add measurable constraints to requirements
- Semantic completeness → add actor-action-object-outcome to each requirement
- Ambiguous terms → update glossary with precise definitions

### "How do I add the squad to CI/CD?"
Run understanding + verify in CI:
```yaml
- run: /speckit.squad.run "$PR_DESCRIPTION"
- run: /speckit.squad.verify
```
If verify fails (coverage < 100%), block the merge.

---

## Anti-Patterns — Don't Do This

| Anti-Pattern | Why It Fails | Do This Instead |
|-------------|-------------|-----------------|
| Skip understanding, jump to build | No spec = no verification = no quality | Always run the full pipeline |
| Ignore WHY rejections | WHY catches real problems — 4 rejections in our test run | Fix the spec, don't bypass the gate |
| Never run feedback | Squad can't learn without ground truth | Run feedback after every deployment |
| Set max_iterations to 1 | No rework loops = first draft ships | Default 5 is there for a reason |
| Use the squad for trivial tasks | 34 agents for a config change is overkill | Use it for features, migrations, new systems |
