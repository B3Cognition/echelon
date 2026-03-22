# AUDITOR Mode 4 Dry Run — ARCHITECT (known-good-output)

## Step 0: General Rules Applied

1. **Null vs zero:** No metric required null substitution. All inputs were available and all denominators were non-zero.
2. **Value range:** All computed scores fall within [0.0, 1.0]. No clamping needed.
3. **Empty denominator:** No denominator was zero. No null-with-reason assignments needed.
4. **Computation health:** All metrics report `inputs_available: true`, `formula_succeeded: true`, `warnings: []` unless noted below.
5. **Naming convention:** All internalization metric fields use `int_` prefix. CHECKPOINT data uses `chk_` prefix.

---

## Step 1: Absorption Metrics

### I-01 requirement_coverage_rate

**Spec IDs extracted** (regex `/(?:FR|NFR)-\d{3}/g`):
- FR-001, FR-002, FR-003, FR-004, FR-005
- Total: 5

**Output IDs extracted** (same regex):
- FR-001 (×3 occurrences), FR-002 (×3), FR-003 (×3), FR-004 (×3), FR-005 (×3)
- Unique: FR-001, FR-002, FR-003, FR-004, FR-005
- Total unique: 5

**Intersection:** {FR-001, FR-002, FR-003, FR-004, FR-005} = 5

**Computation:** `|spec_ids ∩ output_ids| / |spec_ids|` = 5 / 5

**Score: 1.00**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: []}`

---

### I-02 constraint_adherence_score

**Spec constraints extracted** (pattern: `{parameter} {operator} {value}`):
1. `max_latency <= 200ms`
2. `min_uptime >= 99.9%`
3. `max_retries = 3`

Total: 3

**Output parameter assignments extracted:**
1. `max_latency`: "150ms target" → 150ms
2. `min_uptime`: "99.95% SLA" → 99.95%
3. `max_retries`: "2 configured" → 2

**Constraint satisfaction checks:**
1. max_latency: 150ms <= 200ms → SATISFIED
2. min_uptime: 99.95% >= 99.9% → SATISFIED
3. max_retries: 2 = 3 → VIOLATED (spec says `= 3`, output configures 2; the agent claims compliance by interpreting "= 3" as a ceiling, but strict arithmetic evaluation: 2 ≠ 3)

**Computation:** `satisfied / total_matched_constraints` = 2 / 3

**Score: 0.667**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: ["max_retries: agent interprets '= 3' as maximum, strict arithmetic yields violation"]}`

---

### I-03 terminology_fidelity

**Glossary terms extracted** (bold/heading terms from Glossary table, lowercased):
- api, endpoint, latency, uptime, retry, timeout, cache, webhook, payload, schema
- Total: 10

**Output tokenization** (split on whitespace, lowercase, remove punctuation):
- Total unique tokens: 226

**Glossary terms found in output tokens:**
- api: FOUND
- endpoint: FOUND
- latency: FOUND
- uptime: FOUND
- retry: FOUND
- timeout: FOUND
- cache: FOUND
- webhook: FOUND
- payload: FOUND
- schema: FOUND
- Intersection size: 10

**Jaccard computation:** `|glossary_terms ∩ output_terms| / |glossary_terms ∪ output_terms|`
- Union = |glossary| + |output_terms| - |intersection| = 10 + 226 - 10 = 226
- Jaccard = 10 / 226

**Score: 0.044**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: ["Jaccard inherently low when output token set >> glossary set; all glossary terms present but denominator dominated by output vocabulary"]}`

---

### I-04 dependency_awareness

**Dependencies extracted from spec** (Dependencies table):
1. PostgreSQL
2. Redis
3. CloudflareWorkers

Total: 3

**Mentions in output** (case-insensitive substring match):
1. PostgreSQL: FOUND (appears 5 times: "PostgreSQL" in decisions, constraint section, dependency section)
2. Redis: FOUND (appears 5 times)
3. CloudflareWorkers: FOUND (appears 3 times)

All 3 mentioned.

**Computation:** `mentioned / total_in_scope` = 3 / 3

**Score: 1.00**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: []}`

---

## Step 2: int-Accuracy Metrics

### I-05 numeric_contradiction_rate

**Constraints from spec** (reuse Step 1 I-02 extraction):
1. `max_latency <= 200ms`
2. `min_uptime >= 99.9%`
3. `max_retries = 3`

**Agent output values:**
1. max_latency = 150ms
2. min_uptime = 99.95%
3. max_retries = 2

**Arithmetic compliance checks:**
1. 150 <= 200 → NO VIOLATION
2. 99.95 >= 99.9 → NO VIOLATION
3. 2 = 3 → VIOLATION (2 ≠ 3)

Violations: 1 out of 3

**Computation:** `1 - (violations / total_checked)` = 1 - (1/3) = 2/3

**Score: 0.667**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: ["max_retries violation: agent set 2, spec requires exactly 3"]}`

---

### I-06 uncited_decision_rate

**Decisions extracted from output** (keyword detection: "Decision:", "Selected", "Adopted", "Configured", "Deployed"):

1. "Decision: Selected PostgreSQL for persistence because it provides ACID transactions and native JSON schema validation..." — cites [FR-002] → CITED
2. "Decision: Adopted Redis as the read-through cache to keep endpoint response latency well below the 200ms ceiling..." — cites [FR-003] → CITED
3. "Decision: Configured exponential-backoff retry with max retries set to 2..." — cites [FR-004] → CITED
4. "Decision: Deployed the API gateway on CloudflareWorkers at the edge..." — cites [FR-001, FR-005] → CITED

Total decisions: 4
Uncited decisions: 0

**Computation:** `1 - (uncited_decisions / total_decisions)` = 1 - (0/4) = 1.0

**Score: 1.00**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: []}`

---

### I-07 cross_reference_accuracy

**All requirement ID citations from output** (regex `/(?:FR|NFR|AC|C)-\d{3}[a-z]?/g`):
1. FR-002 (line 9)
2. FR-003 (line 11)
3. FR-004 (line 13)
4. FR-001 (line 15)
5. FR-005 (line 15)
6. FR-002 (line 31)
7. FR-001 (line 37)
8. FR-001 (line 40)
9. FR-002 (line 40)
10. FR-003 (line 40)
11. FR-004 (line 40)
12. FR-005 (line 40)

Total citations: 12

**Valid ID set from spec:** {FR-001, FR-002, FR-003, FR-004, FR-005}

**Validation:**
- All 12 citations reference IDs in the valid set. Zero phantom IDs.

**Computation:** `valid_citations / total_citations` = 12 / 12

**Score: 1.00**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: []}`

---

### I-08 keyword_scope_rate

**Scope keywords** (derived from agent task description — designing Widget Notification Service, assigned FR-001 to FR-005, component/module names):
- api, gateway, webhook, persistence, postgresql, cache, redis, retry, uptime, endpoint, latency, schema, payload, cloudflare, notification, service, validation

**Decisions** (reuse I-06 extraction): 4 decisions

**Scope keyword presence in each decision (case-insensitive):**
1. "Selected PostgreSQL for persistence..." → postgresql ✓, persistence ✓, schema ✓, validation ✓
2. "Adopted Redis as the read-through cache..." → redis ✓, cache ✓, endpoint ✓, latency ✓
3. "Configured exponential-backoff retry..." → retry ✓, webhook ✓
4. "Deployed the API gateway on CloudflareWorkers..." → api ✓, gateway ✓, cloudflare ✓, latency ✓, uptime ✓

All 4 decisions contain at least one scope keyword.

**Computation:** `scoped_decisions / total_decisions` = 4 / 4

**Score: 1.00**

computation_health: `{inputs_available: true, formula_succeeded: true, warnings: []}`

---

## Step 3: Int-Gate Evaluation

### Category Scores

**int_absorption_score** = mean of non-null {I-01, I-02, I-03, I-04}
= mean(1.00, 0.667, 0.044, 1.00)
= 2.711 / 4
= **0.678**

**int_accuracy_score** = mean of non-null {I-05, I-06, I-07, I-08}
= mean(0.667, 1.00, 1.00, 1.00)
= 3.667 / 4
= **0.917**

### Tier Lookup

Agent: ARCHITECT
Tier: **deep** (provided in inputs)
- absorption_threshold: 0.80
- int_accuracy_threshold: 0.75

### Verdict

- int_absorption_score (0.678) >= absorption_threshold (0.80)? **NO — FAIL**
- int_accuracy_score (0.917) >= int_accuracy_threshold (0.75)? **YES — PASS**

**int_gate_verdict: FAIL**

Failing category: Absorption
- Required: >= 0.80
- Actual: 0.678
- Shortfall: 0.122

Root cause: I-03 (terminology_fidelity) scored 0.044 due to Jaccard denominator being dominated by the output's large vocabulary (226 unique tokens vs 10 glossary terms). Even with perfect glossary term coverage (10/10 terms present), Jaccard cannot exceed 10/226 = 0.044.

---

## Step 4: Cross-Validation

### CV-2: high-terminology-low-accuracy
Condition: `int_I03 >= 0.90 AND int_I05 < 0.80`
- I-03 = 0.044 (NOT >= 0.90)
- Condition NOT met.
- **CV-2: NOT TRIGGERED**

### CV-3: citation-stuffing-low-fidelity
Condition: `int_I01 >= 0.90 AND int_I03 < 0.40`
- I-01 = 1.00 (>= 0.90 ✓)
- I-03 = 0.044 (< 0.40 ✓)
- Condition MET.
- **CV-3: TRIGGERED — "citation-stuffing-low-fidelity"**
  - Triggering values: I-01=1.00, I-03=0.044
  - Rule ID: CV-3

Note per Step 4 rule 5: "Flags are advisory only — they do NOT change the gate verdict."

**Advisory note:** CV-3 fires here, but this is almost certainly a false positive. The agent references all 5 FR-IDs (driving I-01 high) and uses all 10 glossary terms (perfect coverage). The low I-03 score is an artifact of Jaccard penalizing vocabulary size disparity, not actual citation stuffing. This highlights a known limitation of the I-03 formula when applied to prose-heavy outputs.

### CV-1: high-coverage-low-acceptance (deferred)
Requires I-13 (deferred metric). Not evaluated in this run.

---

## Step 5: Disagreement Check

### Simulated CHECKPOINT Data
- chk_doubt_count = 0 (provided in inputs)
- chk_score = N/A (not provided; informational only per Step 5 rule 3)

### Disagreement Condition
`int_gate_verdict == PASS AND chk_doubt_count >= 2`?

- int_gate_verdict = FAIL (not PASS)
- Condition NOT met.

**disagreement_flag: null**

No disagreement. Both AUDITOR (FAIL gate) and CHECKPOINT (0 doubts) are directionally consistent — though CHECKPOINT's zero doubts might suggest it would have rated the output favorably, the disagreement rule only fires when the gate passes despite high doubts, not the inverse.

---

## Summary Table

| Metric | ID | Raw Score | Status |
|--------|-----|-----------|--------|
| requirement_coverage_rate | I-01 | 1.000 | PASS |
| constraint_adherence_score | I-02 | 0.667 | — |
| terminology_fidelity | I-03 | 0.044 | DRAG |
| dependency_awareness | I-04 | 1.000 | PASS |
| **int_absorption_score** | — | **0.678** | **FAIL (threshold: 0.80)** |
| numeric_contradiction_rate | I-05 | 0.667 | — |
| uncited_decision_rate | I-06 | 1.000 | PASS |
| cross_reference_accuracy | I-07 | 1.000 | PASS |
| keyword_scope_rate | I-08 | 1.000 | PASS |
| **int_accuracy_score** | — | **0.917** | **PASS (threshold: 0.75)** |
| **int_gate_verdict** | — | — | **FAIL** |
| CV-2 | — | — | NOT TRIGGERED |
| CV-3 | — | — | TRIGGERED (advisory) |
| disagreement_flag | — | — | null |

## Observations

1. **I-03 (terminology_fidelity) is the dominant failure driver.** The Jaccard similarity formula produces inherently low scores when the output vocabulary far exceeds the glossary size. All 10 glossary terms are present, yet the score is 0.044. This metric may need formula revision (e.g., recall-based: `|intersection| / |glossary|` would yield 1.0) or the specification should clarify that Jaccard is the intended measure despite this known behavior.

2. **I-02 and I-05 share a max_retries interpretation ambiguity.** The spec states `max_retries = 3`. The agent configures 2 retries, arguing it is "within" the constraint. Strict arithmetic (`=` means equality) yields a violation. A spec using `<=` instead of `=` would make the intent unambiguous.

3. **CV-3 fires as a false positive** due to the I-03 Jaccard issue, not actual citation stuffing behavior.

4. **Overall quality of the output is high** — all requirements addressed, all dependencies integrated, all decisions cited, all cross-references valid. The FAIL verdict is driven primarily by metric formula properties (I-03 Jaccard) rather than substantive quality gaps.
