# Phase: phase3-specialists
# Source: echelon.run.md §7 — Specialist Summoning
# Agent: conditional_parallel (speckit-echelon-guardian (GUARDIAN) mandatory; others conditional)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching specialists

## 7. Specialist Summoning

### Determine Which Specialists to Summon

After ASSESS passes, determine which specialists are needed:

1. **Read DISCOVER outputs** to classify the domain (e.g., fintech, healthcare, IoT, e-commerce, real-time, ML/AI)
2. **Read `calibration-profile.yaml`** for low-confidence domains
3. **Read `unknowns.md`** for unresolved items

### Summoning Rules

| Specialist | Summon When | Max Priority |
|-----------|-------------|--------------|
| **TEST speckit-echelon-architect (ARCHITECT)** | ALWAYS (mandatory) | Required |
| **SCIENTIST** (speckit-echelon-investigator (INVESTIGATOR)) | `unknowns.md` has unresolved items OR `calibration-profile.yaml` shows confidence < 0.5 for relevant domain | High |
| **SECURITY** (speckit-echelon-guardian (GUARDIAN)) | ALWAYS when `specialists.guardian_mode: always_on` (default); otherwise domain involves auth, payments, PII, regulatory compliance | Required (always_on) / High (on_demand) |
| **DOMAIN EXPERT** | Domain-specific knowledge needed (detected from DISCOVER) | Medium |
| **PERFORMANCE** | High-load, real-time, scalability requirements in spec | Medium |
| **UX / A11Y** | Frontend, user-facing features, accessibility | Medium |
| **INNOVATE** | See expanded triggers below | Medium |

**INNOVATE dispatch conditions** are defined in `workflow/definition.yaml` phase3-specialists → `speckit-echelon-maverick.condition` (8 conditions). speckit-echelon-commander (COMMANDER) evaluates each against `state.json` before finalising the specialist list and records the decision as a `routing_decision` journal entry. If `dispatch_innovate: false`, the entry must list which conditions were checked and why none fired.

### Max Active Specialists

Maximum `max_active_specialists` (default 3) can be active simultaneously. If more are needed, prioritize by domain signal strength. Defer lower-priority specialists (their insights can be incorporated in future runs).

**Exception:** TEST speckit-echelon-architect (ARCHITECT) and speckit-echelon-guardian (GUARDIAN) (when `specialists.guardian_mode: always_on`) always run as mandatory agents and do not count toward the cap.

### Dispatch Specialists

This phase uses `type: conditional_sequential` (see `workflow/definition.yaml` phase3-specialists). Dispatch each specialist in turn — wait for completion and run the post-dispatch protocol before dispatching the next. speckit-echelon-investigator (INVESTIGATOR) is the only exception: it may run in parallel with one domain specialist.

#### SCIENTIST Dispatch (speckit-echelon-investigator (INVESTIGATOR) codename) — if summoned

Context pack:

- Specific question(s) from `unknowns.md`
- Relevant artifacts (always select based on the question — do not send everything)
- `extension/templates/investigation-report-template.md`
- `extension/templates/evidence-grades-template.md`
- `extension/templates/recommendations-template.md`
- `extension/templates/knowledge-gaps-template.md`
- `extension/templates/experiment-results-template.md`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include specific unknowns from unknowns.md, relevant artifacts based on the question, investigator output templates including experiment-results-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are INVESTIGATOR. Read agents/specialists/investigator.md for your complete protocol.
  Investigate the following unknowns: [list from unknowns.md]. Follow the full scientific method: QUESTION, RESEARCH, EVALUATE (grade A-E), HYPOTHESIZE, EXPERIMENT (if feasible — use git worktree via `scripts/bash/setup-worktree.sh`), MEASURE, SYNTHESIZE, RECOMMEND. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-investigator (INVESTIGATOR): investigating unknowns — {topic summary}"

#### SECURITY Dispatch (speckit-echelon-guardian (GUARDIAN) codename) — always-on by default

**Dispatch mode** is controlled by `echelon-config.yml` → `specialists.guardian_mode` (default: `always_on`).

- **`always_on`**: Dispatch speckit-echelon-guardian (GUARDIAN) on every run. If the domain is NOT security-sensitive, speckit-echelon-guardian (GUARDIAN) runs only the **Minimum Security Checklist** (5-item lightweight check). If security-sensitive, speckit-echelon-guardian (GUARDIAN) runs the full STRIDE + OWASP + compliance analysis.
- **`on_demand`**: Dispatch only when domain involves auth, payments, PII, regulatory compliance (legacy behavior).

Context pack:

- `spec.md` + `boundaries.md` + domain-relevant artifacts
- `extension/templates/security-checklist-template.md`
- `extension/templates/threat-model-template.md`
- `extension/templates/compliance-requirements-template.md`
- `extension/templates/risk-acceptance-log-template.md`
- `extension/templates/security-findings-template.md`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, boundaries.md, domain-relevant artifacts, guardian output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are GUARDIAN. Read agents/specialists/guardian.md for your complete protocol.
  Guardian mode is `{specialists.guardian_mode}`. If always_on and domain is non-security: run the Minimum Security Checklist only. If domain is security-relevant OR mode is on_demand with security domain: perform full STRIDE threat modeling, OWASP Top 10, compliance analysis. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-guardian (GUARDIAN): security analysis (mode: {specialists.guardian_mode})"

#### DOMAIN EXPERT Dispatch (if summoned)

Context pack:

- Domain-relevant artifacts from `{spec_dir}/`
- `extension/templates/domain-patterns-template.md`
- `extension/templates/domain-amendments-template.md`
- `extension/templates/compliance-gaps-template.md`
- `extension/templates/terminology-corrections-template.md`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include domain-relevant artifacts from {spec_dir}/, oracle output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ORACLE. Read agents/specialists/oracle.md for your complete protocol.
  You are the ORACLE agent for {domain}. Provide domain patterns, regulatory requirements, common pitfalls, and terminology corrections. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-oracle (ORACLE): {domain} domain analysis"

#### PERFORMANCE Dispatch (if summoned)

Context pack:

- `spec.md` + `boundaries.md` + performance-relevant requirements
- `extension/templates/performance-requirements-template.md`
- `extension/templates/capacity-model-template.md`
- `extension/templates/performance-amendments-template.md`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, boundaries.md, performance-relevant requirements, benchmark output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are BENCHMARK. Read agents/specialists/benchmark.md for your complete protocol.
  Perform load modeling, capacity planning, identify bottleneck risks. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-benchmark (BENCHMARK): load modeling and capacity analysis"

#### UX / A11Y Dispatch (if summoned)

Context pack:

- `spec.md` + user-facing requirements
- `extension/templates/accessibility-requirements-template.md`
- `extension/templates/user-flow-template.md`
- `extension/templates/ux-amendments-template.md`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include spec.md, user-facing requirements, advocate output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ADVOCATE. Read agents/specialists/advocate.md for your complete protocol.
  Analyze WCAG 2.1/2.2 compliance needs, apply Nielsen's heuristics, map user flows. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-advocate (ADVOCATE): accessibility and usability analysis"

#### INNOVATE Dispatch (if summoned)

Context pack:

- All current artifacts
- Prior run's `evolution-report.md`
- `extension/templates/alternatives-template.md`
- `extension/templates/risk-opportunities-template.md`
- `extension/templates/challenge-assumptions-template.md`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts, prior run's evolution-report.md, maverick output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are MAVERICK. Read agents/specialists/maverick.md for your complete protocol.
  Propose 2-3 fundamentally different approaches using TRIZ, Design Thinking, or First Principles. Challenge established assumptions. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-maverick (MAVERICK): alternative approaches and assumption challenges"

### Post-Specialist

After all specialists complete, collect their outputs. Return the list of specialists that ran in `echelon_result.state_updates`:

```yaml
active_specialists:
  - "<specialist-name>"
```

**MANDATORY — run before transitioning to phase3-how:**

```bash
# Budgets: definition.yaml phases[phase3-specialists].timing_window_transition
#   close: phase2-decide (budget_seconds=1800)
#   open:  phase3-solution (open_budget_seconds=2400)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" end_phase phase2-decide
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase3-solution 2400
```

If `end_phase` detects over-budget (>120%), it records that outcome in the
append-only telemetry event stream. Do not write timing data to `state.json`
before routing to phase3-how.

**Transition:** `phases[phase3-how]` — see `workflow/definition.yaml`
