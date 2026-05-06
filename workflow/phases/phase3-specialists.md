# Phase: phase3-specialists
# Source: echelon.run.md §7 — Specialist Summoning
# Agent: conditional_parallel (GUARDIAN mandatory; others conditional)
# Read by: COMMANDER before dispatching specialists

## 7. Specialist Summoning

### Determine Which Specialists to Summon

After ASSESS passes, determine which specialists are needed:

1. **Read DISCOVER outputs** to classify the domain (e.g., fintech, healthcare, IoT, e-commerce, real-time, ML/AI)
2. **Read `calibration-profile.yaml`** for low-confidence domains
3. **Read `unknowns.md`** for unresolved items

### Summoning Rules

| Specialist | Summon When | Max Priority |
|-----------|-------------|--------------|
| **TEST ARCHITECT** | ALWAYS (mandatory) | Required |
| **SCIENTIST** (INVESTIGATOR) | `unknowns.md` has unresolved items OR `calibration-profile.yaml` shows confidence < 0.5 for relevant domain | High |
| **SECURITY** (GUARDIAN) | ALWAYS when `guardian.mode: always_on` (default); otherwise domain involves auth, payments, PII, regulatory compliance | Required (always_on) / High (on_demand) |
| **DOMAIN EXPERT** | Domain-specific knowledge needed (detected from DISCOVER) | Medium |
| **PERFORMANCE** | High-load, real-time, scalability requirements in spec | Medium |
| **UX / A11Y** | Frontend, user-facing features, accessibility | Medium |
| **INNOVATE** | See expanded triggers below | Medium |

**INNOVATE Expanded Triggers** — INNOVATE should run more often than other specialists. It catches design ruts early:

1. **Re-run stagnation:** EVOLVE detects no improvement between runs → INNOVATE
2. **Circular reasoning:** Same issue raised 3x without resolution → INNOVATE before escalation
3. **WHY rejects spec 2+ times:** The spec keeps failing quality gates → INNOVATE reframes the problem
4. **ASSESS borderline DEFER:** Feasibility is marginal (not clear KILL, not clear PASS) → INNOVATE proposes simpler alternatives
5. **HOW faces a hard tradeoff:** Architecture decision has no clear winner → INNOVATE applies TRIZ contradiction resolution
6. **Quality scores plateau:** WHY scores improve < 2% over 2 iterations → INNOVATE breaks the local optimum
7. **Any agent reports BLOCKED:** Before escalating to human, try INNOVATE first
8. **First run with complex scope:** If ASSESS estimates > 100 person-weeks, proactively run INNOVATE to check if a simpler approach exists

### Max Active Specialists

Maximum `max_active_specialists` (default 3) can be active simultaneously. If more are needed, prioritize by domain signal strength. Defer lower-priority specialists (their insights can be incorporated in future runs).

**Exception:** TEST ARCHITECT and GUARDIAN (when `guardian.mode: always_on`) do not count toward the cap — they are mandatory and always run.

### Dispatch Specialists

For each specialist to summon, dispatch sequentially (unless they are independent — INVESTIGATOR investigations can run in parallel with domain specialists).

#### SCIENTIST Dispatch (INVESTIGATOR codename) — if summoned

Context pack:

- Specific question(s) from `unknowns.md`
- Relevant artifacts (select based on the question — do not send everything)
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include specific unknowns from unknowns.md, relevant artifacts based on the question, reasoning-journal.json]
  </context>

  <instructions>
  You are INVESTIGATOR. Read agents/specialists/investigator.md for your complete protocol.
  Investigate the following unknowns: [list from unknowns.md]. Follow the full scientific method: QUESTION, RESEARCH, EVALUATE (grade A-E), HYPOTHESIZE, EXPERIMENT (if feasible — use git worktree via `scripts/bash/setup-worktree.sh`), MEASURE, SYNTHESIZE, RECOMMEND. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "INVESTIGATOR: investigating unknowns — {topic summary}"

#### SECURITY Dispatch (GUARDIAN codename) — always-on by default

**Dispatch mode** is controlled by `echelon-config.yml` → `guardian.mode` (default: `always_on`).

- **`always_on`**: Dispatch GUARDIAN on every run. If the domain is NOT security-sensitive, GUARDIAN runs only the **Minimum Security Checklist** (5-item lightweight check). If security-sensitive, GUARDIAN runs the full STRIDE + OWASP + compliance analysis.
- **`on_demand`**: Dispatch only when domain involves auth, payments, PII, regulatory compliance (legacy behavior).

Context pack:

- `spec.md` + `boundaries.md` + domain-relevant artifacts
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, boundaries.md, domain-relevant artifacts, reasoning-journal.json]
  </context>

  <instructions>
  You are GUARDIAN. Read agents/specialists/guardian.md for your complete protocol.
  Guardian mode is `{guardian.mode}`. If always_on and domain is non-security: run the Minimum Security Checklist only. If domain is security-relevant OR mode is on_demand with security domain: perform full STRIDE threat modeling, OWASP Top 10, compliance analysis. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "GUARDIAN: security analysis (mode: {guardian.mode})"

#### DOMAIN EXPERT Dispatch (if summoned)

Context pack:

- Domain-relevant artifacts from `specs/{feature}/`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include domain-relevant artifacts from specs/{feature}/, reasoning-journal.json]
  </context>

  <instructions>
  You are ORACLE. Read agents/specialists/oracle.md for your complete protocol.
  You are the ORACLE agent for {domain}. Provide domain patterns, regulatory requirements, common pitfalls, and terminology corrections. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "ORACLE: {domain} domain analysis"

#### PERFORMANCE Dispatch (if summoned)

Context pack:

- `spec.md` + `boundaries.md` + performance-relevant requirements
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, boundaries.md, performance-relevant requirements, reasoning-journal.json]
  </context>

  <instructions>
  You are BENCHMARK. Read agents/specialists/benchmark.md for your complete protocol.
  Perform load modeling, capacity planning, identify bottleneck risks. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "BENCHMARK: load modeling and capacity analysis"

#### UX / A11Y Dispatch (if summoned)

Context pack:

- `spec.md` + user-facing requirements
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, user-facing requirements, reasoning-journal.json]
  </context>

  <instructions>
  You are ADVOCATE. Read agents/specialists/advocate.md for your complete protocol.
  Analyze WCAG 2.1/2.2 compliance needs, apply Nielsen's heuristics, map user flows. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "ADVOCATE: accessibility and usability analysis"

#### INNOVATE Dispatch (if summoned)

Context pack:

- All current artifacts
- Prior run's `evolution-report.md`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts, prior run's evolution-report.md, reasoning-journal.json]
  </context>

  <instructions>
  You are MAVERICK. Read agents/specialists/maverick.md for your complete protocol.
  Propose 2-3 fundamentally different approaches using TRIZ, Design Thinking, or First Principles. Challenge established assumptions. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "MAVERICK: alternative approaches and assumption challenges"

### Post-Specialist

After all specialists complete, collect their outputs. Update `state.json.active_specialists` with the list of specialists that ran.

Before this transition, COMMANDER performs phase-boundary timing writes in order:

1. Close `phase2-decide` by calling `scripts/bash/phase-timing.sh end_phase phase2-decide`.
2. Open `phase3-solution` by calling `scripts/bash/phase-timing.sh start_phase phase3-solution 2400`.
3. `end_phase` writes `end_ts`, `elapsed_seconds`, `over_budget`, and `anomaly_reason`; if over budget (>120%), it also appends a `timing_anomaly` journal entry.
4. Persist state updates before routing to HOW.

**Transition:** `phases[phase3-how]` — see `workflow/definition.yaml`
