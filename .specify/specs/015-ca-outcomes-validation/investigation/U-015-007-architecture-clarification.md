# Investigation U-015-007: Echelon Architecture Clarification
**Agent**: INVESTIGATOR | **Date**: 2026-04-02 | **Spec**: 015

## Agent Count and Tier Structure

Echelon agents were enumerated by direct filesystem inspection of `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/agents/`. Each `.md` file in a tier directory is one agent definition.

| Tier | Agent Count | Agent Names | Dispatch Mode |
|------|-------------|-------------|---------------|
| control | 6 | commander, checkpoint, prospector, scorekeeper, strategist, tracker | Always dispatched as needed by COMMANDER |
| exploration | 6 | cartographer, golddigger, modeler, sage, scout, synthesizer | Selective — COMMANDER dispatches per phase requirements |
| feasibility | 2 | gatekeeper, validator | Selective — mandatory at phase gates |
| learning | 8 | adaptive, auditor, global-memory, internalizer, mirror, monitor, realist, veteran | Selective — COMMANDER dispatches based on EVOI |
| solution | 3 | architect, orchestrator, sentinel | Selective — COMMANDER dispatches per HOW/PLAN phases |
| specialists | 6 | advocate, benchmark, guardian, investigator, maverick, oracle | Selective — COMMANDER dispatches on-demand or per config (guardian_mode) |
| build | 11 | code-reviewer, debugger, engineering-manager, change-controller, implementer, integrator, progress-tracker, spec-guard, test-guardian, verification, visual-validator | Selective — dispatched only when build phase is active |

**Total agent count**: 42
**Total tiers**: 7

---

## Dispatch Protocol: Individual Agents, Not Tiers

COMMANDER's dispatch protocol (commander.md) operates at the **individual agent level**, not at the tier level as a whole. Evidence:

1. **Named dispatches**: COMMANDER issues explicit per-agent dispatches (e.g., "Dispatch GUARDIAN," "Dispatch PROSPECTOR," "Dispatch GOLDDIGGER," "Dispatch INVESTIGATOR") — not tier-level dispatches.
2. **EVOI gating**: Before dispatching another iteration, COMMANDER applies Expected Value of Information (EVOI) analysis on a per-agent basis: "What is the probability that re-running [this agent] will improve the output?"
3. **Budget allocation**: Token budget is allocated by phase group (DISCOVER+WHAT, WHY, HOW+SPECIALISTS, PLAN+ASSESS, CONSENSUS+FINALIZE), not by tier. Multiple agents from different tiers may be active within one phase group.
4. **Selective specialist dispatch**: The specialists tier is explicitly on-demand — GUARDIAN has a `guardian_mode` config (`always_on` | `on_demand`); other specialists are dispatched only when EVOI or convergence criteria indicate value. The build tier is not dispatched at all unless `/speckit.echelon.build` is explicitly invoked.
5. **Phase sequencing maps to tier membership loosely**: exploration agents run in Phase 1 (DISCOVER), feasibility agents run at gates, solution agents run in HOW/PLAN phases — but these are not tier-as-unit dispatches. COMMANDER selects specific agents within a tier based on the task.

---

## 7-Stage vs 42-Agent Relationship

The "7 stages" (or "7-stage pipeline") referenced in spec 014 and related specs maps to the **7 tiers**, not to individual agents. The tier names themselves encode the pipeline stage semantics:

| Stage (Tier) | Pipeline Function |
|---|---|
| control | Orchestration, initialization, convergence monitoring |
| exploration | Discovery, understanding, knowledge synthesis |
| feasibility | Quality gates, validation, pass/fail verdicts |
| learning | Feedback incorporation, calibration, pattern recognition |
| solution | Architecture, orchestration logic, risk sentinel |
| specialists | Domain-specific: security, novelty, investigation, adversarial |
| build | Implementation, code review, integration |

The 42 agents are dispatched *selectively within* their tier. Within a single run, not all 42 agents are invoked. COMMANDER's EVOI framework determines which agents within a tier are worth dispatching given current evidence quality and remaining budget.

**In practice**: A typical spec analysis run (non-build) involves approximately 10–18 agent dispatches drawn from the control, exploration, feasibility, learning, solution, and specialists tiers. The build tier's 11 agents are only active during a build phase.

---

## Impact on CA Overlay Designs

This finding is relevant to two design questions in spec 014's plan.md that reference the goal stack and ACT-R buffer designs. The clarification is reported here as a finding; architecture decisions about what to do with it belong to ARCHITECT.

**Finding 1: Goal stack operates at agent level, not tier level.**
COMMANDER's dispatch is per-agent with EVOI scoring. A goal stack that tracks "current work item" must therefore reference individual agent dispatch states, not tier completion states. Spec 014's goal stack design needs to specify whether the stack entries are tier-level (coarse) or agent-level (fine-grained). This is an architecture decision for ARCHITECT.

**Finding 2: ACT-R typed buffers.**
The ACT-R buffer analogy (one buffer per cognitive function) maps more naturally to tier-level than to individual agents — each tier represents a distinct cognitive function (exploration, feasibility, learning, etc.). However, within a tier, multiple agents can be active with different sub-tasks. Whether the ACT-R buffer design operates at tier granularity (7 buffers) or agent granularity (up to 42 buffer slots) is not determined by this architectural inspection. This is an architecture decision for ARCHITECT.

**Finding 3: The build tier is a conditional sub-pipeline, not a primary stage.**
The build tier's 11 agents form a self-contained sequential pipeline (IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN → INTEGRATOR). This is structurally different from the other 6 tiers, which are invoked non-sequentially by COMMANDER. Any CA overlay that assumes 7 symmetric pipeline stages needs to account for the fact that the build tier is a conditionally-invoked sequential sub-pipeline, not an always-active stage. This is an architecture decision for ARCHITECT.

---

## Verdict

**CLARIFIED**: Echelon has 42 agents across 7 tiers. The "7-stage pipeline" refers to the 7 tiers as pipeline stages. Agents within a tier are selectively dispatched by COMMANDER based on EVOI scoring, phase requirements, and budget — not dispatched as a tier-unit. The build tier (11 agents) is a conditionally-invoked sequential sub-pipeline distinct from the 6 analysis tiers. This finding means spec 014's plan.md sections covering Goal Stack and ACT-R Typed Buffer designs need to specify whether those constructs operate at tier granularity (7 entries) or agent granularity (up to 42 entries) — that is an architecture decision for ARCHITECT.

---

## Resolution Note — TASK-009
**Date**: 2026-04-02

### Goal Stack Granularity

**Confirmed granularity: agent-level (up to 42), not tier-level (7).**

Evidence from commander.md dispatch protocol:
- COMMANDER issues named per-agent dispatches throughout its protocol (e.g., "Dispatch GUARDIAN," "Dispatch PROSPECTOR," "Dispatch GOLDDIGGER," "dispatch INVESTIGATOR," "dispatch MAVERICK") — never "dispatch the exploration tier" or "dispatch the learning tier."
- The EVOI check is framed at the individual agent level: "What is the probability that re-running *the agent* will improve the output?" — not at the tier level.
- The Build Phase State Machine (commander.md § Build Phase Orchestration) sequences individual agents explicitly: IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN → PROGRESS TRACKER, then INTEGRATOR — individual agent transitions, not tier transitions.
- Token budget allocation is organized by phase group (DISCOVER+WHAT, WHY, HOW+SPECIALISTS, PLAN+ASSESS, CONSENSUS+FINALIZE), with multiple agents from different tiers potentially active within one phase group. This further confirms that the operational unit is the individual agent dispatch, not the tier.

Therefore: the Goal Stack overlay must track individual agent dispatch states. A tier-level (7-entry) Goal Stack would lose information about which specific agents within a tier have been dispatched, are active, or have completed — information that COMMANDER actively manages and that EVOI decisions depend on. The stack should reference individual agent dispatch entries (up to 42 possible entries across a full run, though a typical non-build run involves 10–18 dispatches).

### ACT-R Buffer Granularity

**Confirmed granularity: tier-level (7 buffers) for the buffer type mapping; agent-level for buffer content.**

The ACT-R typed buffer analogy maps buffer *types* to cognitive functions — and each tier represents a distinct cognitive function (exploration, feasibility, learning, etc.). This structural mapping is at the tier level: 7 tiers = 7 buffer types. However, the *content* of each buffer at runtime reflects the most recently completed agent dispatch within that tier, since COMMANDER selects specific agents within a tier based on task requirements and EVOI. A feasibility buffer holds the output of the last GATEKEEPER or VALIDATOR dispatch — not a monolithic "feasibility tier" output.

Token budget per context call applies at the **individual agent dispatch level**: commander.md explicitly tracks cumulative token usage per agent in `state.json` (`token_ledger.dispatches[]`) and enforces that no single agent consumes more than 40% of total budget. Each dispatch is a separate context call with its own token footprint. The ACT-R buffer's token budget concern is therefore per-dispatch (per agent invocation), not per tier.

### Build Tier Treatment

**The 11-agent build sub-pipeline requires separate overlay treatment.**

Evidence from commander.md § Build Phase Orchestration:
1. The build tier is **not dispatched during Phase A (Understanding)**. It is only activated when the user explicitly invokes `/speckit.echelon.build` — a separate command. COMMANDER does not auto-start the build phase.
2. The build tier operates as a **sequential state machine** (IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN → PROGRESS TRACKER → INTEGRATOR), which is structurally distinct from the non-sequential EVOI-gated dispatch pattern used for all other tiers.
3. A mandatory VALIDATOR gate runs before any build agent — a pattern that does not exist in the analysis phase.
4. Build agents have their own iteration cycle limits (max 2 fix cycles per agent pair), separate from the analysis phase's convergence thresholds.

Any CA overlay that models the 7 tiers as symmetric pipeline stages must treat the build tier as a conditional, sequentially-orchestrated sub-pipeline with its own state machine, not as a peer stage in the analysis pipeline. The Goal Stack during a build phase should track position within the build state machine (which task, which agent step within that task) — a different tracking structure than the EVOI-gated dispatch log used in Phase A.

### ISS-001 Status: RESOLVED

**Impact on TASK-004 (U-CA-004 experiment spec)**: The experiment should test CA overlays at the **agent-dispatch level** because COMMANDER's dispatch protocol operates at the individual agent level (named dispatches, per-agent EVOI checks, per-agent token tracking). A CA overlay that operates at the tier level would be coarser than the actual orchestration unit and would not capture the routing decisions that COMMANDER actually makes. The U-CA-004 gate experiment design (REQ-015-008) should specify CA overlay targeting at the agent-dispatch level, with the 7-tier structure used only for buffer-type classification (which cognitive function does this agent's output serve), not for dispatch sequencing.
