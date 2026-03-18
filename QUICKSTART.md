# Cognitive Squad — Quick Start for Engineers

## What Is This?

A spec-kit extension that makes Claude Code work like a **real engineering team** instead of a single prompt-and-pray chatbot.

Instead of:
```
You: "Build me a user auth system"
Claude: *writes code, hopes it's right*
```

You get:
```
You: "Build me a user auth system"
Squad: DISCOVER maps the domain → WHY challenges every assumption
     → WHAT writes testable requirements (validated by 31 IEEE/ISO metrics)
     → ASSESS kills it if unfeasible → HOW designs architecture with ADRs
     → Each agent PROVES it understood the plan before coding
     → IMPLEMENTER writes code → SPEC GUARD verifies it matches the spec
     → CODE REVIEWER checks quality → TEST GUARDIAN validates tests
     → VERIFICATION traces EVERY requirement to code (100% or rework)
     → System scores itself and gets better next time
```

**34 specialized agents. 3 phases. Every decision evidence-graded. Self-improving.**

## Why Should I Use This?

Because Claude Code alone:
- Is equally confident when right and when wrong
- Doesn't check if what it built matches what you asked for
- Doesn't track its own accuracy
- Makes the same mistakes across projects
- Skips its own quality process when rushing

Cognitive Squad fixes all of this with separation of concerns — different agents produce, critique, verify, and learn. No single agent can approve its own work.

## 5-Minute Setup

```bash
# 1. Clone
git clone https://github.com/Testimonial/cognitive-squad.git

# 2. Install into your spec-kit project
cd your-project
specify extension add --dev /path/to/cognitive-squad

# 3. Run the understanding phase
/speckit.squad.run "Build a user authentication system with OAuth2, MFA, and session management"

# 4. Review what it produced (in .specify/specs/001-*/):
#    - spec.md (requirements, validated by Understanding CLI)
#    - plan.md (architecture with ADRs)
#    - tasks.md (ordered tasks with critical path)
#    - feasibility.md, estimates.md, risk-matrix.md

# 5. Build with quality gates
/speckit.squad.build 001-user-auth

# 6. Verify 100% spec coverage
/speckit.squad.verify
```

## The Three Phases

### Phase 1: Understanding — "What are we building?"

| Agent | What It Does | Why It Matters |
|-------|-------------|----------------|
| DISCOVER | Maps the domain (brownfield: reads code; greenfield: researches the ecosystem) | You don't build on assumptions |
| WHY | Rejects weak specs using 31 deterministic metrics (IEEE/ISO) | Quality in = quality out |
| WHAT | Writes testable requirements with acceptance criteria | Every requirement is verifiable |
| ASSESS | Kills unfeasible ideas BEFORE anyone writes code | Saves weeks of wasted effort |
| HOW | Designs architecture with evidence-graded ADRs | Decisions have rationale, not just opinions |
| SCIENTIST | Runs experiments when nobody knows the answer | Evidence > guessing |
| PLAN | Breaks work into tasks with critical path and risk | You know what to build first |

### Phase 2: Internalization — "Does everyone understand?"

Every build agent must **prove it understood** the plan before coding. Six checks: role, constraints, architecture, domain, tasks, doubts. Zero doubts required to proceed.

### Phase 3: Application — "Build it and prove it works"

| Agent | What It Does | Why It Matters |
|-------|-------------|----------------|
| IMPLEMENTER | Writes code following TDD per task | Code exists |
| SPEC GUARD | Checks code matches the spec requirements | Built what was specified |
| CODE REVIEWER | Reviews quality, security, ADR compliance | Built it well |
| TEST GUARDIAN | Validates test quality and coverage | Tests actually test something |
| VERIFICATION | Traces EVERY spec requirement to code (backward) | Nothing was missed |
| VISUAL VALIDATOR | Screenshots the running product | Tests pass ≠ product works |
| ENGINEERING MANAGER | Manages the build loop, triggers rework | Done means done |

## 10 Commands

| Command | One-liner |
|---------|-----------|
| `/speckit.squad.run` | Understand and plan a project |
| `/speckit.squad.build` | Build it with quality gates |
| `/speckit.squad.verify` | Prove 100% spec coverage |
| `/speckit.squad.status` | Where are we? |
| `/speckit.squad.change` | Handle a spec change mid-build |
| `/speckit.squad.innovate` | Get fresh alternatives |
| `/speckit.squad.investigate` | Research a specific question |
| `/speckit.squad.ground` | Reality-check the plan |
| `/speckit.squad.feedback` | Feed back real outcomes (after deployment) |
| `/speckit.squad.resume` | Answer the squad's question |

## What Makes It Different From Other AI Tools

| Feature | Raw Claude Code | Cognitive Squad |
|---------|----------------|-----------------|
| Spec quality | Whatever the LLM produces | 31 IEEE/ISO metrics with pass/fail gates |
| Architecture decisions | "I recommend X" | ADR with rationale + alternatives + evidence grade |
| Estimation | "About 2 weeks" | Function Point Analysis + Kahneman reference class correction |
| Code verification | "Tests pass" | Backpropagation: every requirement traced to code and test |
| Self-awareness | Equally confident right or wrong | CALIBRATE tracks accuracy per domain, applies correction factors |
| Learning | Starts fresh every time | Knowledge base: patterns, pitfalls, calibration persist across projects |
| Process discipline | Skips steps when rushing | METACOGNITION MONITOR flags process violations |
| User intent | Optimizes for what it thinks is best | INTENT TRACKER compares every decision to what you actually said |

## Real Results

Tested against a large production codebase (hundreds of components, 10+ years of tech debt):

- WHY rejected the spec **4 times** before it was good enough
- SCIENTIST resolved 3 critical assumptions with one empirical test
- ASSESS estimates were 1.4x optimistic — GROUND caught it using industry data
- The squad caught its own scope mistake and self-corrected
- After the run: 5 reusable patterns and 5 pitfalls logged for next time

## Prerequisites

- **spec-kit** >= 0.3.0 (required)
- **understanding** >= 3.4.0 (optional — enables 31-metric quality gates)
- **spec-kit-reverse-eng** >= 1.0.0 (optional — enables brownfield analysis)

## Learn More

- [Full README](README.md) — architecture, agent roster, standards alignment
- [Design Doc](docs/design.md) — complete specification of all 34 agents
- [Repo](https://github.com/Testimonial/cognitive-squad)
