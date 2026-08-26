## Change Request: CR-001

**Status:** ACCEPTED — propagation applied 2026-07-20 (spec.md edits 1–6 below; overlap wording refined per the Risk Items recommendation to "requirement or acceptance criterion explicitly named in that issue"). Re-entry: NONE. Journal entries 94–95.
**Date:** 2026-07-20
**Source:** Operator, informed by three SUE self-examination artifacts (socratic-dialogue.md, semantic-reproducibility.md, socratic-consensus.md) and the closure plan committed at 0f596a95.
**Type:** MODIFICATION
**Priority:** NORMAL (all build tasks DONE, no in-progress work affected; Phase A only)

### Changed Requirements

| Req ID | Change Type | Description |
|--------|-------------|-------------|
| AC-023 | MODIFIED | Add operational definition of "overlap": a finding whose cited evidence lines include at least one line of the named requirement's definition or of its referenced acceptance criteria. Currently undefined (theaetetus APORIA_UNDEFINED on this criterion). |
| SC-001 | MODIFIED | Mirror the AC-023 overlap definition into the SC-001 success criterion for consistency. |
| AC-001 | MODIFIED | Split the Then clause (3 bundled obligations: 2 model calls, report written, exit code 0) into one obligation per sub-bullet. No obligation content changes. |
| AC-002 | MODIFIED | Split the Then clause (enumerated fact list) into one obligation per sub-bullet. No obligation content changes. Note: the pre-existing "exactly 4 facts" vs FR-036 "exactly 5 base facts" discrepancy (ISS-303) is NOT part of this change and is NOT corrected here. |
| AC-017 | MODIFIED | Split the Then clause (3 bundled obligations: parse-failure classification, 1 retry, second failure exit 3) into one obligation per sub-bullet. No obligation content changes. |
| AC-021 | MODIFIED | Split the Then clause (2 bundled obligations: end-to-end completion, 0 live model calls) into one obligation per sub-bullet. No obligation content changes. |

### Guardrail Verification

| Guardrail | Status | Evidence |
|-----------|--------|----------|
| Consensus findings 4, 5, 7-13 stay ACCEPTED backlog | PASS | None of the 6 changed requirement IDs appear in the accepted backlog findings. The definitional tail remains untouched. |
| Limitations frontier stays | PASS | No Limitations section text is touched. |
| No estimate inflation | PASS | Total delta is approximately 0.5h of spec-text editing. No DONE-task rework. |
| No behavioural changes | PASS | All clause splits preserve obligation content verbatim. Overlap definition adds precision to an undefined criterion without changing the delivered script. |
| Constitution compliance | PASS | No principle violated. This is spec-text precision, not a behavioural or architectural change. |

### Impact Assessment

#### 1. Direct Impact: spec.md (6 requirement units)

All 6 changes are within spec.md. No structural changes to any other specification artifact.

**AC-023 (line 86) and SC-001 (line 268) -- overlap definition:**
The word "overlap" appears in both AC-023 and SC-001 without an operational definition. The theaetetus dialogue (socratic-dialogue.md) reached APORIA_UNDEFINED on this criterion. The SUE script's own finding #13 in the acceptance report (`specs/029-builder-spec-workbench/socratic-challenge.md`) independently identified this gap. The proposed definition makes the criterion operational.

**Consistency of proposed overlap definition with the delivered report format:**
- FR-037 requires each finding to state a target requirement identifier plus evidence rendered per FR-039.
- FR-039 requires quoting exactly 1 line of text per cited evidence line number from the challenged spec.
- The acceptance report (T-S01, 2026-07-19) confirms findings cite evidence line numbers from spec 029. Finding #13 cites lines 13, 15, 16, 218, 219, 220 -- all within REQ-002's definition (lines 12-17) or AC-002's definition (lines 218-220) in spec 029.
- Under the proposed definition, finding #13 overlaps known issue 3 ("the undefined active-run pointer of REQ-002") because its evidence lines include lines 13, 15, 16 of REQ-002's definition. This is consistent with the T-S01 acceptance evidence.
- Finding #10 cites line 202 (REQ-028's output line in spec 029), overlapping known issue 2 ("REQ-017/REQ-019/REQ-028 quality-score recording loop") because REQ-028 is explicitly named.
- Finding #1 cites lines 258-260 (AC-010 in spec 029), overlapping known issue 1 ("REQ-009 'time order' vs AC-010 'most recent first' ordering conflict") because AC-010 is explicitly referenced.

**Recommendation on overlap definition wording:** The phrase "of its referenced acceptance criteria" could be ambiguous -- "its" could mean (a) the named requirement's own acceptance criteria, or (b) the acceptance criteria explicitly referenced in the known issue description. For issue 1, AC-010 is REQ-010's acceptance criterion, not REQ-009's, but is explicitly named in the issue description. I recommend the definition read: "a finding whose cited evidence lines include at least one line within the definition block of any requirement identifier or acceptance criterion identifier explicitly named in the known issue description." This eliminates the possessive ambiguity while preserving the same operational test.

**AC-001, AC-002, AC-017, AC-021 -- clause splits:**
These are structural decompositions of dense multi-obligation sentences. The semantic-reproducibility report identifies all four as fracture lines with high edge counts (AC-001: 9x, AC-002: 10x, AC-017: 10x, AC-021: 7x). Splitting to one obligation per sub-bullet reduces edge density without changing content.

#### 2. ID Strategy Recommendation: Sub-bullets Within Existing IDs

**Recommended shape:** Keep the parent AC-NNN identifier. Restructure the Then clause as a bulleted list introduced by "then:" with sub-items (a), (b), (c). Example for AC-001:

```
- **AC-001**: Given a readable specification with an available model command, when the operator runs the challenge script, then:
  - (a) exactly 2 model calls occur (FR-008),
  - (b) the challenge report is written into the specification's directory (FR-034), and
  - (c) exit code 0.
```

**Rationale -- sub-bullets vs new sub-IDs:**

| Criterion | Sub-bullets (recommended) | New sub-IDs (AC-001a/AC-001b) |
|-----------|---------------------------|-------------------------------|
| Downstream reference breakage | 0 -- AC-001 ID preserved | Would require updating coverage-map.md (4 rows), tasks.md (req= tags on 3 tasks), traceability.md/traceability.json, test-strategy.md, plan.md |
| New IDs to track | 0 | 10+ new sub-IDs across 4 ACs |
| Semantic fidelity | High -- the obligations are still jointly asserted | Risks splitting a conjunction into independent assertions that could be tested in isolation when they should be joint |
| Consistency with spec style | Consistent -- other ACs already use enumerated lists (e.g., FR-015 lists 5 categories) | New convention not used elsewhere in this spec |

**Verdict:** Sub-bullets within existing IDs. Zero downstream reference breakage. Zero new IDs.

#### 3. Task Impact

| Task ID | Current Status | Impact | Delta Effort | Action |
|---------|---------------|--------|-------------|--------|
| T-001 | DONE | None | 0h | NO ACTION |
| T-002 | DONE | None | 0h | NO ACTION |
| T-003 | DONE | None | 0h | NO ACTION |
| T-004 | DONE | None | 0h | NO ACTION |
| T-005 | DONE | None | 0h | NO ACTION |
| T-006 | DONE | None | 0h | NO ACTION |
| T-007 | DONE | None | 0h | NO ACTION |
| T-008 | DONE | None | 0h | NO ACTION |
| T-009 | DONE | None | 0h | NO ACTION |
| T-010 | DONE | None | 0h | NO ACTION |
| T-011 | DONE | None | 0h | NO ACTION |
| T-012 | DONE | None | 0h | NO ACTION |
| T-013 | DONE | None | 0h | NO ACTION |
| T-014 | DONE | None | 0h | NO ACTION |
| T-S01 | DONE | None | 0h | NO ACTION |

**Verification that zero DONE tasks are affected:**

Every DONE task description was checked for verbatim quotes of the sentences being split. All task references use summaries, not verbatim text:

- T-012 references AC-001 as: "AC-001: exactly 2 model calls, report written beside the spec, exit 0" -- a summary paraphrase. The sub-bullet split does not change the three obligations this summary captures.
- T-011 references AC-002 as: "AC-002: header states exactly the 4 facts (FR-036)" -- a summary. The split decomposes the fact enumeration without changing the count assertion.
- T-009 references AC-017 as: "sleep->sleep exits 3 with TIMEOUT-prefixed dump lines (AC-017)" -- a summary of the behavioural outcome, not the clause structure.
- T-012/T-014 reference AC-021 as: "AC-001/AC-021 end-to-end stub run green" -- an ID-level reference. Stable.
- T-S01 references AC-023 as: "AC-023: finding overlap >= 1 of 3 named issues within <= 3 attempts (SC-001)" -- a summary. The overlap definition ADDS precision to this summary without contradicting it.

No task Test: contract or acceptance-criteria checkbox quotes the sentences being split verbatim. Zero rework.

**Test code impact:** Tests verify behavioural properties (exit codes, call counts, file contents), not spec sentence structure. The clause splits change no behaviour. The overlap definition adds precision to a criterion judged by the operator at T-S01, not by automated tests. Zero test updates needed.

#### 4. Architecture Impact

- ADR-001 through ADR-008 (in plan.md/research.md): NONE affected. All ADRs concern implementation decisions (single-file script, subprocess isolation, extraction strategy, test architecture). No ADR references overlap or AC clause structure.
- Constitution v1.0.0: NONE violated. No principle is implicated by spec-text edits that change no behaviour.

#### 5. Cross-Artifact Reference Impact

| Artifact | References to Changed IDs | Impact | Action |
|----------|--------------------------|--------|--------|
| tasks.md | AC-001 (T-012), AC-002 (T-011), AC-017 (T-009), AC-021 (T-012/T-014), AC-023 (T-S01), SC-001 (T-S01) | All are ID-level or summary references | NO UPDATE -- IDs preserved, summaries still accurate |
| coverage-map.md | AC-001, AC-002, AC-017, AC-021, AC-023, SC-001 rows | Evidence column text uses summaries ("exactly 2 recorded calls; report in spec dir; exit 0") | NO UPDATE -- evidence descriptions remain accurate |
| contracts/report-format.md | AC-002 on line 70: "Header states exactly 4 base facts" | Pre-existing ISS-303 discrepancy with FR-036's "5 base facts" | NO UPDATE -- this is a pre-existing issue, NOT part of CR-001 |
| contracts/cli-contract.md | No direct reference to any changed AC | None | NO UPDATE |
| contracts/model-command-contract.md | No direct reference to any changed AC | None | NO UPDATE |
| plan.md | AC-001, AC-002, AC-017, AC-021, AC-023, SC-001 -- all ID-level or summary | None | NO UPDATE |
| glossary.md | "Acceptance run" entry mentions "the REQ-009/AC-010 ordering contradiction, the score-recording loop, and the undefined active-run pointer" | This informal overlap description is compatible with the new formal definition | NO UPDATE |
| test-strategy.md | AC-021, AC-023, SC-001 -- ID-level references | None | NO UPDATE |
| test-architecture.md | AC-021, AC-023, SC-001 -- ID-level references | None | NO UPDATE |
| semantic-reproducibility.md | Quotes spec lines verbatim as fracture evidence | Historical analysis record -- reflects the spec text AT THE TIME OF ANALYSIS. Not updated retroactively. | NO UPDATE (historical record) |
| socratic-consensus.md | Quotes spec lines as evidence | Same: historical analysis record | NO UPDATE (historical record) |
| socratic-dialogue.md | Targets AC-023 overlap criterion | Historical: the finding that motivated this change | NO UPDATE (historical record) |
| issues.md | ISS-303 references AC-002 "exactly 4 facts" | ISS-303 is a separate pre-existing issue | NO UPDATE |
| checklists/requirements.md | "AC-001 ... AC-023" range reference | Range still valid | NO UPDATE |
| inputs/traceability.md | AC-001, AC-002, AC-021, AC-023 in spec= arrays | ID-level; IDs preserved | NO UPDATE |
| ARTIFACTS.md | No direct AC references | None | NO UPDATE |

#### 6. Dependency Chain Trace

Cross-references between changed requirements and other requirements:

| From | References | Direction | Stable? |
|------|-----------|-----------|---------|
| AC-002 | AC-001 | AC-002's Then clause says "(FR-036, AC-001)" | Yes -- AC-001 ID preserved |
| AC-003 | AC-002 | AC-003 says "(FR-034, AC-002)" | Yes -- AC-002 ID preserved |
| AC-005 | AC-001 | AC-005 says "(FR-040, AC-001)" | Yes -- AC-001 ID preserved |
| ERR-005 | AC-017 | ERR-005 says "(FR-011, AC-017)" | Yes -- AC-017 ID preserved |
| FR-043 | AC-021 | FR-043 says "(AC-021, FR-003)" | Yes -- AC-021 ID preserved |
| SC-001 | AC-023 | SC-001 says "(AC-023, FR-034)" | Yes -- AC-023 ID preserved |
| AC-023 | SC-001 | AC-023 says "(SC-001, FR-034)" | Yes -- SC-001 ID preserved |

All dependency chains are stable. Zero breakage.

### Total Change Cost

- **Rework effort:** 0h (zero DONE tasks affected)
- **Redirection effort:** 0h (zero IN_PROGRESS tasks)
- **New effort:** ~0.5h (6 requirement units edited in spec.md: AC-001, AC-002, AC-017, AC-021 clause splits + AC-023, SC-001 overlap definition)
- **Total delta:** ~0.5h
- **Schedule impact:** 0 days added to critical path (all build tasks DONE; Phase A only; no delivery convergence chasing per operator constraint)

### Risk Items

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Overlap definition possessive ambiguity ("its referenced acceptance criteria") | Medium | Low -- finding #13 unambiguously overlaps issue 3 regardless of interpretation | Recommend refined wording: "any requirement identifier or acceptance criterion identifier explicitly named in the known issue description" |
| ISS-303 (AC-002 "4 facts" vs FR-036 "5 base facts") not fixed alongside AC-002 split | Known pre-existing | Low -- T-011 tests pass against the delivered script which renders 5 facts | Track as separate future fix; explicitly out of scope for CR-001 per "WITHOUT changing any obligation's content" |
| Analysis artifacts (semantic-reproducibility, consensus, dialogue) now quote stale spec text | Expected | None -- these are historical records, not normative. Their value is precisely that they capture what the text said at analysis time | No action needed; the artifacts motivate the change, not mirror the result |

### Propagation Plan

1. **HALT:** None (no IN_PROGRESS tasks)
2. **REWORK:** None (no DONE tasks affected)
3. **UPDATE:** None (no TODO tasks to re-specify)
4. **REMOVE:** None (no tasks cancelled)
5. **NEW:** None (no new build tasks; the spec edits are Phase A work, not build tasks)

**Ordered file-edit list (Phase A spec-text work only):**

| Order | File | Edit | Scope |
|-------|------|------|-------|
| 1 | spec.md | AC-023 (line 86): Append overlap definition after "within at most 3 total attempts" | Add operational criterion |
| 2 | spec.md | SC-001 (line 268): Mirror the overlap definition for consistency | Add operational criterion |
| 3 | spec.md | AC-001 (line 25): Split Then clause into sub-bullets (a), (b), (c) | Structural decomposition only |
| 4 | spec.md | AC-002 (line 26): Split fact enumeration into sub-bullets | Structural decomposition only |
| 5 | spec.md | AC-017 (line 67): Split Then clause into sub-bullets (a), (b), (c) | Structural decomposition only |
| 6 | spec.md | AC-021 (line 84): Split Then clause into sub-bullets (a), (b) | Structural decomposition only |

No other files require editing. All cross-references are ID-level and remain stable.

### Re-validation Results

| Req ID | Gate | Result | Notes |
|--------|------|--------|-------|
| AC-023 | Testability | PASS | The overlap definition adds an operationally testable criterion where none existed. Evidence-line intersection with named requirement/AC lines is mechanically checkable. |
| AC-023 | Consistency | PASS | Consistent with FR-037 (findings state target + evidence), FR-039 (evidence cites line numbers), and the delivered report format. Compatible with the T-S01 acceptance evidence. |
| AC-023 | Unambiguity | CONDITIONAL | The possessive "its referenced acceptance criteria" has a minor ambiguity (see Risk Items). Recommend the refined wording. |
| SC-001 | Testability | PASS | Mirrors AC-023. |
| SC-001 | Consistency | PASS | SC-001 already references AC-023; adding the same definition maintains consistency. |
| AC-001 | Testability | PASS | Sub-bullets preserve all three obligations; each is independently testable (already tested by T-SEAM-01). |
| AC-001 | Consistency | PASS | No content change; no new contradiction introduced. |
| AC-002 | Testability | PASS | Sub-bullets preserve the fact enumeration; each fact is independently testable (already tested by T-RPT-01). |
| AC-002 | Consistency | PASS | The pre-existing ISS-303 discrepancy (4 vs 5 facts) is NOT worsened and NOT fixed. |
| AC-017 | Testability | PASS | Sub-bullets preserve all three obligations; each tested by T-EXC-06. |
| AC-017 | Consistency | PASS | No content change. |
| AC-021 | Testability | PASS | Sub-bullets preserve both obligations; each tested by T-SEAM-01. |
| AC-021 | Consistency | PASS | No content change. |

### Finding-to-Rework Traceability (Step 5b)

| Finding | Source | Impacted Req IDs | Rework Task ID | Notes |
|---------|--------|------------------|----------------|-------|
| Theaetetus APORIA_UNDEFINED on AC-023 overlap criterion | socratic-dialogue.md | AC-023, SC-001 | N/A -- no rework task needed | Resolved by spec-text edit (overlap definition addition). No DONE task is affected; no build work required. |
| Fracture lines AC-001, AC-002, AC-017, AC-021 | semantic-reproducibility.md | AC-001, AC-002, AC-017, AC-021 | N/A -- no rework task needed | Resolved by spec-text edit (clause splits). No DONE task is affected; no build work required. |

No findings require mapped rework tasks because no DONE task is invalidated. The changes are Phase A spec-text precision edits that do not alter any obligation's content or any delivered behaviour.

### Re-entry Target

**NONE** -- no BUILD_RESTART, no QA_RESTART.

Justification: All 15 tasks (14 build + T-S01 acceptance gate) are DONE. The change modifies zero behavioural requirements. The clause splits are structural decompositions that preserve obligation content. The overlap definition adds precision to an existing criterion that was already satisfied (T-S01 acceptance evidence confirms overlap with finding #13 / known issue 3). No test assertion, acceptance criterion, or delivered artifact becomes stale. The operator constraint "do NOT chase delivery convergence" is honoured: this is Phase A spec-text work only.

---

## Change Request: CR-002

**Status:** PENDING APPROVAL
**Date:** 2026-07-21
**Source:** Operator, informed by three drill-confirmed defects in sue-dossier.md (parmenides drill on FR-036, theaetetus drills on FR-008 and FR-013) plus triage of finding 4 (A-001 non-interactivity assumption).
**Type:** MODIFICATION
**Priority:** NORMAL (all build tasks DONE; no in-progress work; Phase A only)

### Changed Requirements

| Req ID | Change Type | Description |
|--------|-------------|-------------|
| AC-002 | MODIFIED | Align header fact count from "exactly 4 facts" to "exactly 5 base facts" and add the resolved model provider sub-bullet (c), matching FR-036 and the delivered script. Closes ISS-303. |
| FR-036 | MODIFIED | Add an operational definition of "resolved model provider": the reverse lookup from the runtime protocol to the 3-key PROVIDERS registry; unknown basenames (including test stubs) default to `claude`. |
| FR-013 | MODIFIED | Define "empty stdout" as 0 characters (length zero) in FR-005's definitional style; explicitly state that whitespace-only stdout is not empty and proceeds to FR-026/FR-027 extraction, where the absence of a JSON object routes it to the FR-028 corrective retry as a parse failure. |
| A-001 | MODIFIED | Update status from "unvalidated (OQ-001 spike before HOW)" to "validated at HOW (claude CLI 2.1.214; research.md OQ-001 spike)" per ISS-307 recommendation. One-line governance fix. |

### Guardrail Verification

| Guardrail | Status | Evidence |
|-----------|--------|----------|
| Stable-low units untouched | PASS | None of the 45 stable-low units listed in sue-dossier.md are touched. CR-001 tested the restructuring hypothesis; it did not improve SR. |
| Accepted backlog findings 4,5,7-13 untouched | PASS | None of the accepted backlog finding IDs overlap with AC-002, FR-036, FR-013, or A-001. |
| Limitations frontier untouched | PASS | No Limitations section text is touched. |
| No behavioural changes to scripts/sue_challenge.py | PASS | Zero code changes. The spec moves to match the delivered code, never the reverse. |
| Constitution compliance | PASS | No principle violated. Spec-text precision only. |

### Impact Assessment

#### Finding 1 -- ISS-303: AC-002 header fact count (4 vs 5)

**Ground truth verification:** `render_report()` (sue_challenge.py:1081-1089) emits 5 header bullets before the conditional truncation note: `**Specification:**`, `**Run date:**`, `**Provider:**`, `**Questions:**`, `**Findings:**`. Test code (test_sue_challenge.py:1325-1326) already asserts: `# Exactly the 5 base facts` with `assert len([l for l in head.splitlines() if l.startswith("- **")]) == 5`. The delivered script implements 5. FR-036 (spec.md:218) correctly says 5. AC-002 (spec.md:29) is stale at 4.

**Direct impact -- 3 locations:**

| Artifact | Location | Current Text | Required Change |
|----------|----------|-------------|-----------------|
| spec.md | AC-002, line 29 | "exactly 4 facts (FR-036, AC-001):" with sub-bullets (a)-(d) missing provider | "exactly 5 base facts (FR-036, AC-001):" with sub-bullets (a)-(e) adding provider at (c) |
| contracts/report-format.md | Template, lines 32-35 | 4 header bullets (Specification, Run date, Questions, Findings) | Add `- **Provider:** <provider name>` after Run date |
| contracts/report-format.md | Normative rules table, line 70 | "Header states exactly 4 base facts ... spec path, run date, question count, finding count" | "Header states exactly 5 base facts ... spec path, run date, resolved model provider, question count, finding count" |

**Task impact:**

| Task ID | Current Status | Stale Text | Action |
|---------|---------------|------------|--------|
| T-011 | DONE | Description (line 301): "exactly 4 base facts (spec path, run date, question count, finding count)". Test line (line 303): "the 4 header facts". Acceptance criteria (line 306): "AC-002: header states exactly the 4 facts (FR-036)". | NO REWORK. Tests already verify 5 facts (test line 1326: `== 5`). Task description is a historical record written before the provider fact was added to FR-036. The "4 facts" text in T-011 is stale against the code it produced, not against the tests that verify it. |

**Re-validation risk -- does changing AC-002 from 4 to 5 invalidate existing tests or assertions?**
- Test code: Already asserts 5 facts. No test change needed.
- contracts/report-format.md: Being updated in the same change batch. No residual inconsistency.
- Other AC references to AC-002: AC-003 (line 34) says "(FR-034, AC-002)" -- ID-level, stable.
- No existing test will break. No existing assertion becomes stale.

**ISS-303 closure path:** After AC-002 says "5 base facts" and report-format.md says "5 base facts", the two-year-old WHY2/WHY3 escalation chain ISS-203 -> ISS-303 is fully resolved. Mark ISS-303 RESOLVED in issues.md.

**Recommended verbatim edit for AC-002 (spec.md line 29-33):**

Replace:
```
- **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 4 facts (FR-036, AC-001):
  - (a) the specification path,
  - (b) the run date,
  - (c) the question count,
  - (d) the finding count.
```
With:
```
- **AC-002**: Given a completed challenge run, when the operator opens the challenge report, then the report header states exactly 5 base facts (FR-036, AC-001):
  - (a) the specification path,
  - (b) the run date,
  - (c) the resolved model provider,
  - (d) the question count,
  - (e) the finding count.
```

**Recommended verbatim edit for report-format.md template (line 32-35):**

Replace:
```
- **Specification:** <spec path as invoked>
- **Run date:** <YYYY-MM-DD>
- **Questions:** <post-truncation count>
- **Findings:** <finding count>
```
With:
```
- **Specification:** <spec path as invoked>
- **Run date:** <YYYY-MM-DD>
- **Provider:** <provider name>
- **Questions:** <post-truncation count>
- **Findings:** <finding count>
```

**Recommended verbatim edit for report-format.md normative rules (line 70):**

Replace:
```
| Header states exactly 4 base facts | FR-036, AC-002 | spec path, run date, question count, finding count; truncation note is the only conditional addition |
```
With:
```
| Header states exactly 5 base facts | FR-036, AC-002 | spec path, run date, resolved model provider, question count, finding count; truncation note is the only conditional addition |
```

---

#### Finding 2 -- FR-036 provider fact definition

**Ground truth verification:** `PROVIDERS` (sue_challenge.py:87-91) is a fixed 3-key registry: `claude`, `codex`, `copilot`. The header value is `provider_of_protocol(config.model_protocol)` (sue_challenge.py:150-154, 1221) -- the reverse lookup from the runtime-resolved protocol to its provider name. For a bare command whose basename is not in PROVIDERS (a test stub), sue_challenge.py:131 assigns `provider = "claude"` -- unknown basenames keep the Claude-compatible stdin protocol for backward compatibility. The rendered provider value is therefore always exactly one of the three literals `claude`, `codex`, `copilot`.

**Direct impact -- 1 location:**

| Artifact | Location | Current Text | Required Change |
|----------|----------|-------------|-----------------|
| spec.md | FR-036, line 218 | "The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison." | Insert a definition sentence before this sentence, grounded in the delivered PROVIDERS behavior. |

**Task impact:** None. No task description or test references the provider definition.

**Architecture impact:** None. No ADR is invalidated. The PROVIDERS registry was a development-time design decision not covered by an ADR.

**Recommended verbatim edit for FR-036 (spec.md line 218):**

Replace:
```
- **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.
```
With:
```
- **FR-036**: The report header MUST state exactly 5 base facts — specification path, run date, resolved model provider, question count, finding count — plus the FR-019 truncation note when truncation occurred (AC-002). The run date is the ISO calendar date `YYYY-MM-DD` in the operator's local timezone, rendered as the single `**Run date:**` header bullet; NFR-004's byte-identical comparison excludes exactly that line. The resolved model provider is the reverse lookup from the runtime-resolved protocol to the `PROVIDERS` registry; the rendered value is always exactly one of three literals — `claude`, `codex`, or `copilot`. When the model command's executable basename is not a registered provider (including test stubs), the value defaults to `claude`. The provider fact keeps environment-resolved runs auditable (runtime provider selection, 2026-07-19); it is stable across reruns and participates in NFR-004's comparison.
```

---

#### Finding 3 -- FR-013 "empty stdout" definition

**Ground truth verification:** sue_challenge.py:631: `kind = "ok" if process.returncode == 0 and stdout else "failed"` -- plain Python string truthiness. A zero-length string is falsy (empty); a whitespace-only string is truthy (non-empty). Therefore:
- Empty stdout = 0 characters (length zero) -> classified `"failed"` -> parse-failure path, output never consumed.
- Whitespace-only stdout = non-empty, truthy -> classified `"ok"` -> proceeds to `extract_json_object` (FR-026) -> no JSON object extractable -> parse failure (FR-027) -> corrective retry (FR-028).

These are two distinct paths with different semantics. The current FR-013 text says "empty stdout" without defining it, which is the gap the theaetetus drill exposed.

**Direct impact -- 1 location:**

| Artifact | Location | Current Text | Required Change |
|----------|----------|-------------|-----------------|
| spec.md | FR-013, line 152 | "or produces empty stdout, is classified as a failed call" | Define "empty stdout" as 0 characters; add explicit whitespace-only routing clause. |

**Task impact:** None. T-005 and T-009 are DONE. The tests exercise the actual code behavior (string truthiness). No test change needed.

**Recommended verbatim edit for FR-013 (spec.md line 152):**

Replace:
```
- **FR-013**: When a corrective retry launches under FR-028, the challenge script MUST grant that retry exactly 1 fresh timeout budget equal to the FR-004 value (NFR-001). A model call that exits with non-zero status, or produces empty stdout, is classified as a failed call on the parse-failure path before any extraction — its output is never consumed even when it would parse (U-007).
```
With:
```
- **FR-013**: When a corrective retry launches under FR-028, the challenge script MUST grant that retry exactly 1 fresh timeout budget equal to the FR-004 value (NFR-001). A model call that exits with non-zero status, or produces empty stdout (0 characters), is classified as a failed call on the parse-failure path before any extraction — its output is never consumed even when it would parse (U-007). Stdout consisting only of whitespace characters is not empty: it proceeds to FR-026/FR-027 extraction, where the absence of a JSON object routes it to the FR-028 corrective retry as a parse failure.
```

---

#### Finding 4 -- A-001 non-interactivity assumption: FIX verdict

**Triage verdict: FIX (one-line governance sentence suffices).**

**Justification:** ISS-307 (issues.md) already recommends this exact status change. research.md records the OQ-001 spike (claude CLI 2.1.214, 2026-07-18) as Grade-A direct evidence validating A-001. The successful T-S01 acceptance run (2026-07-19) further confirms non-interactive operation works end-to-end. FR-008 and FR-026 are correct as written -- they rely on A-001, and A-001 is now validated. No restructuring of FR-008 or FR-026 is needed.

The dossier's concern -- "If the designated acceptance run's real model command turns out not to satisfy A-001, which requirement governs?" -- is moot because A-001 has been validated through both the spike and the acceptance run. Updating the status field records this closure.

**Direct impact -- 1 location:**

| Artifact | Location | Current Text | Required Change |
|----------|----------|-------------|-----------------|
| spec.md | A-001, line 338 | "unvalidated (OQ-001 spike before HOW)" | "validated at HOW (claude CLI 2.1.214; research.md OQ-001 spike)" |

**Task impact:** None.

**Recommended verbatim edit for A-001 (spec.md line 338):**

Replace:
```
| A-001 | The model command can be driven non-interactively with prompt in, extractable JSON out | unvalidated (OQ-001 spike before HOW) | FR-008, FR-026 |
```
With:
```
| A-001 | The model command can be driven non-interactively with prompt in, extractable JSON out | validated at HOW (claude CLI 2.1.214; research.md OQ-001 spike) | FR-008, FR-026 |
```

---

### Full Task Impact Assessment

| Task ID | Current Status | Impact | Delta Effort | Action |
|---------|---------------|--------|-------------|--------|
| T-001 | DONE | None | 0h | NO ACTION |
| T-002 | DONE | None | 0h | NO ACTION |
| T-003 | DONE | None | 0h | NO ACTION |
| T-004 | DONE | None | 0h | NO ACTION |
| T-005 | DONE | None | 0h | NO ACTION |
| T-006 | DONE | None | 0h | NO ACTION |
| T-007 | DONE | None | 0h | NO ACTION |
| T-008 | DONE | None | 0h | NO ACTION |
| T-009 | DONE | None | 0h | NO ACTION |
| T-010 | DONE | None | 0h | NO ACTION |
| T-011 | DONE | Stale "4 facts" text in description (historical) | 0h | NO ACTION -- tests verify 5 facts |
| T-012 | DONE | None | 0h | NO ACTION |
| T-013 | DONE | None | 0h | NO ACTION |
| T-014 | DONE | None | 0h | NO ACTION |
| T-S01 | DONE | None | 0h | NO ACTION |

**Zero DONE tasks require rework.** All changes are spec-text precision edits that align the spec to the delivered code's actual behavior. The tests already verify the correct behavior (5 header facts, string truthiness for empty-stdout classification). No test assertion becomes stale.

### Architecture Impact

- ADR-001 through ADR-008 (in research.md): NONE affected. No ADR references the header fact count, provider definition, empty-stdout semantics, or A-001 status.
- Constitution v1.0.0: NONE violated. No principle is implicated by spec-text precision edits that change zero behavior.
- No constraint violation introduced.

### Estimates Impact

No change to estimates.md. The effort range and function point breakdown are historical artifacts of the original estimation. The CR-002 delta effort (~1.0h of spec-text editing) does not alter the delivered work or its estimates.

### Total Change Cost

- **Rework effort:** 0h (zero DONE tasks affected)
- **Redirection effort:** 0h (zero IN_PROGRESS tasks)
- **New effort:** ~1.0h (4 spec.md edits + 2 report-format.md edits, Phase A spec-text work)
- **Total delta:** ~1.0h
- **Schedule impact:** 0 days added to critical path (all build tasks DONE; Phase A only; no delivery)

### Propagation Plan

1. **HALT:** None (no IN_PROGRESS tasks)
2. **REWORK:** None (no DONE tasks affected)
3. **UPDATE:** None (no TODO tasks to re-specify)
4. **REMOVE:** None (no tasks cancelled)
5. **NEW:** None (no new build tasks)

**Ordered file-edit list (Phase A spec-text work only):**

| Order | File | Edit | Finding |
|-------|------|------|---------|
| 1 | spec.md | AC-002 (line 29): "4 facts" -> "5 base facts" + add provider sub-bullet (c) | Finding 1 |
| 2 | spec.md | FR-036 (line 218): Insert provider definition sentence | Finding 2 |
| 3 | spec.md | FR-013 (line 152): Define "empty stdout" as 0 characters + whitespace-only routing clause | Finding 3 |
| 4 | spec.md | A-001 (line 338): Status "unvalidated" -> "validated at HOW" | Finding 4 |
| 5 | contracts/report-format.md | Template (line 33): Add `**Provider:**` line after `**Run date:**` | Finding 1 |
| 6 | contracts/report-format.md | Normative rules (line 70): "4 base facts" -> "5 base facts" + add provider | Finding 1 |

No other files require editing. All cross-references are ID-level and remain stable.

### Dependency Chain Trace

| From | References | Direction | Stable? |
|------|-----------|-----------|---------|
| AC-003 | AC-002 | AC-003 says "(FR-034, AC-002)" | Yes -- AC-002 ID preserved |
| AC-006 | FR-036 | AC-006 says "(FR-036)" | Yes -- FR-036 ID preserved |
| AC-016 | FR-013 | AC-016 says "(FR-028, FR-013)" | Yes -- FR-013 ID preserved |
| FR-028 | FR-013 | FR-028 says "(FR-013, FR-030)" | Yes -- FR-013 ID preserved |
| NFR-001 | FR-013 | FR-013 says "(NFR-001)" | Yes -- reference direction only |
| ISS-303 | AC-002, FR-036 | ISS-303 cites the AC-002/FR-036 conflict | Resolves -- ISS-303 becomes RESOLVED |
| ISS-307 | A-001 | ISS-307 recommends A-001 status refresh | Resolves -- ISS-307 recommendation fulfilled |

All dependency chains are stable. Zero breakage.

### Finding-to-Rework Traceability (Step 5b)

| Finding ID | Source | Impacted Req IDs | Rework Task ID | Notes |
|------------|--------|------------------|----------------|-------|
| Dossier finding 1 (ISS-303 fact count) | sue-dossier.md parmenides drill + v2-stable CONTRADICTED on FR-036 | AC-002, FR-036 (report-format.md) | N/A -- no rework task needed | Resolved by spec-text edits (AC-002 + report-format.md aligned to "5 base facts"). No DONE task invalidated; tests already verify 5 facts. |
| Dossier finding 2 (provider definition) | sue-dossier.md v2-stable UNANSWERABLE on FR-036 | FR-036 | N/A -- no rework task needed | Resolved by spec-text edit (provider definition sentence in FR-036). No DONE task references the definition. |
| Dossier finding 3 (empty stdout) | sue-dossier.md theaetetus drill APORIA_UNDEFINED on FR-013 | FR-013 | N/A -- no rework task needed | Resolved by spec-text edit (0-characters definition + whitespace-only routing). Tests exercise the actual code behavior. |
| Dossier finding 4 (A-001 status) | sue-dossier.md theaetetus drill APORIA_CONTRADICTED on FR-008 | A-001 | N/A -- no rework task needed | Resolved by one-line status update. ISS-307 already recommends this. |

No findings require mapped rework tasks because no DONE task is invalidated. All changes are Phase A spec-text precision edits that align the spec to the delivered code's actual behavior without altering any obligation's content or any delivered behavior.

### Re-validation Results

| Req ID | Gate | Result | Notes |
|--------|------|--------|-------|
| AC-002 | Testability | PASS | Sub-bullets (a)-(e) are independently testable; already tested by T-RPT-01 (test line 1326). |
| AC-002 | Consistency | PASS | Now consistent with FR-036 "exactly 5 base facts". ISS-303 resolved. |
| AC-002 | Unambiguity | PASS | "5 base facts" mirrors FR-036's wording exactly. Provider sub-bullet (c) matches delivered code. |
| FR-036 | Testability | PASS | Provider definition is operationally testable: value is always one of 3 literals; unknown basenames default to `claude`. |
| FR-036 | Consistency | PASS | Definition matches delivered PROVIDERS registry (sue_challenge.py:87-91) and reverse-lookup logic (sue_challenge.py:150-154). |
| FR-036 | Unambiguity | PASS | Three explicit literals; explicit default for unknown basenames; no wiggle room. |
| FR-013 | Testability | PASS | "0 characters" is measurable. Whitespace-only routing is deterministic and separately testable. |
| FR-013 | Consistency | PASS | Consistent with FR-005's definitional style ("0 non-whitespace characters" for empty spec; here "0 characters" for empty stdout). Whitespace-only routing consistent with FR-026/FR-027/FR-028 as written. |
| FR-013 | Unambiguity | PASS | "0 characters" eliminates the whitespace ambiguity the theaetetus drill exposed. |
| A-001 | Testability | PASS | Status is a governance field, not a testable assertion. |
| A-001 | Consistency | PASS | Status now reflects the Grade-A evidence from research.md OQ-001 spike and the successful T-S01 acceptance run. |

### Risk Items

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| T-011 stale "4 facts" text in task description could confuse a future reader | Low | Low -- task is DONE, tests verify 5 facts, description is historical | Note staleness in this report; do not rewrite historical task descriptions |
| ISS-303 marked RESOLVED but issues.md not yet updated | Low | Low -- the spec edits are the authoritative closure | Batch ISS-303 resolution into the issues.md update when the spec edits are applied |
| contracts/report-format.md template and normative rules updated but no downstream contract consumer exists beyond the test suite | None | None | The contract file is an internal specification artifact, not an external API |

### Re-entry Target

**NONE** -- no BUILD_RESTART, no QA_RESTART.

Justification: All 15 tasks (14 build + T-S01 acceptance gate) are DONE. The change modifies zero behavioral requirements. The spec moves to match the delivered code's actual behavior in every case: 5 header facts (not 4), provider derived from PROVIDERS registry, empty stdout means 0 characters, A-001 validated (not unvalidated). No test assertion, acceptance criterion, or delivered artifact becomes stale. The operator constraint "Phase A only -- do not proceed to delivery" is honored.
