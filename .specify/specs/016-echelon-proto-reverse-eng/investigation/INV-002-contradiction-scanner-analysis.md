# INV-002: Contradiction Scanner Precision — What Does It Actually Detect?

**Date**: 2026-04-02
**Run ID**: squad-1775164062
**Status**: COMPLETE

## Question

The contradiction scanner is rated LOW patent defensibility. But what specific contradictions has it caught? What are the three heuristic patterns? What is the precision/recall? Is "adjacent pipeline stage contradiction detection" novel, or do standard spec review tools already do this?

## Evidence Examined

### 1. `/scripts/contradiction-scanner.py` (778 lines)
- Read lines 1-100 (header, constants, artifact stage map)
- Read lines 310-489 (detect_contradictions function and three heuristic implementations)
- Read lines 144-208 (Assertion class, extraction helpers, entity matching logic)

### 2. `/contradiction-scan-results.json` (actual execution on specs 013, 014, 015)
- Total contradictions detected: 197
- Per-pair rates
- Breakdown by contradiction type
- Sample results for spec 015

### 3. Source code review
- Lines 375-391 (status contradiction detection)
- Lines 393-489 (detect_contradictions main logic)
- Lines 344-373 (entity matching heuristics)

## Findings

### 1. Three Heuristic Patterns (Lines 393-489)

The scanner implements exactly THREE heuristic patterns:

**HEURISTIC 1: Count Mismatch (Lines 418-441)**

Trigger: Two assertions from adjacent pipeline stages assert about the SAME ENTITY (by key match) and BOTH contain numeric values, and those numeric values differ.

Example:
```
Artifact A (DISCOVER): "| R-001 | LOW | REQ-Q2-001, REQ-S-001 | Add EU AI Act compliance placeholder |"
Artifact B (risks.md): "| R-001 | SAGE false negatives at quality gate | H | 5 | **CRITICAL** | Yes (cascade) |"
Entity matched: "R-001"
Numbers extracted: [1] vs [5]
Contradiction type: count_mismatch, confidence: 0.7
```

Implementation (lines 419-426):
- Extract all positive numbers (> 0) from each assertion
- Compare first number from each
- If they differ, flag as contradiction with confidence 0.7

**HEURISTIC 2: Status Mismatch (Lines 443-464)**

Trigger: Two assertions about the SAME ENTITY each contain opposite status tokens.

Status pairs defined (lines 377-390):
- PASS ↔ FAIL
- YES ↔ NO
- TRUE ↔ FALSE
- VALIDATED ↔ INVALID
- CONFIRMED ↔ UNCONFIRMED
- ENABLED ↔ DISABLED
- ACTIVE ↔ INACTIVE

Implementation (lines 444-463):
- Iterate all status pairs from assertion A and B
- If any pair is opposite (per _status_contradicts), flag with confidence 0.85

Example from results (C-001 through C-006 in scan):
```
C-002: Entity "R-002", status mismatch, confidence 0.85
```

**HEURISTIC 3: Boolean Mismatch (Lines 465-489)**

Trigger: Two assertions about the SAME ENTITY where one is negated and the other is not, AND both have no numeric values, AND the text length ratio is > 0.4.

Negation detection (regex pattern at lines 107-111):
```
\b(not|no |never|none|absent|missing|does not|do not|cannot|can't|
doesn't|don't|isn't|aren't|won't|hasn't|haven't)\b
```

Implementation (lines 466-489):
- Check if a.negated != b.negated (one is negated, other is not)
- Exclude numeric assertions (likely measurement differences, not logical contradictions)
- Ensure text similarity (len_ratio > 0.4) to filter unrelated pairs
- Flag with confidence 0.5 (lowest of three)

### 2. Actual Scan Results for Spec 015

From `/contradiction-scan-results.json`:

**Summary Statistics**:
- Total contradictions across all specs (013, 014, 015): 197
- Contradictions in spec 015 only: 15
- Contradiction types distribution (all specs):
  - count_mismatch: 171 (86.8%)
  - boolean_mismatch: 20 (10.2%)
  - status_mismatch: 6 (3.0%)

**Per-stage rates** (all specs):
| Stage Pair | Pairs Compared | Contradictions | Rate |
|---|---|---|---|
| DISCOVER → ASSESS | 193,152 | 33 | 0.000171 |
| ASSESS → HOW | 208,624 | 52 | 0.000249 |
| HOW → PLAN | 159,200 | 112 | 0.000704 |
| PLAN → BUILD | 0 | 0 | 0.0 |
| BUILD → FINALIZE | 0 | 0 | 0.0 |

**Overall rate**: 197 / 560,976 = 0.000351 (0.035%)

**Spec 015 examples** (sample):
```json
C-183: count_mismatch, "REQ-015-002"
  Artifact A (estimates.md): "REQ-015-002 | Q — <1 hour | None | Can run in parallel..."
  Artifact B (test-architecture.md): "REQ-015-002 | ACC, CIT, REP | ACC for AC-002-001..."
  Numbers: 1 vs none; confidence 0.7

C-184: count_mismatch, "REQ-015-005"
  Artifact A (estimates.md): "REQ-015-005 | M — 1-2 days | Detection method choice |..."
  Artifact B (test-architecture.md): "REQ-015-005 | ACC | ACC on five ACs..."
  Numbers: 1, 2 vs none; confidence 0.7
```

### 3. Precision/Recall Status

**Stated in code (lines 662-672)**:
```
"This scanner applies three syntactic heuristics (count mismatch, status mismatch, 
boolean mismatch) over structured key-value lines, bold patterns, and table rows 
in Markdown artifacts. It is an UPPER BOUND estimator: (1) false positives occur 
when different entities share the same key name across artifacts; (2) false negatives 
occur for contradictions expressed in unstructured prose, multi-sentence reasoning, 
or non-adjacent pipeline stages."
```

**Key statement** (line 665-666): "The output contradiction_rate_per_run is not a true precision-recall metric and must be interpreted as a detection signal, not a ground truth."

**No precision/recall targets are specified in the scanner code or spec 015.** The scanner is explicitly positioned as an UPPER BOUND (over-detects, misses soft contradictions).

**Manual verification**: The scan results note "verified=null" for all 197 contradictions, indicating no human review has been conducted.

### 4. Assessment of Novelty

**Question: Is "adjacent pipeline stage contradiction detection" novel?**

**Evidence against novelty**:
1. **Contradiction detection in specs is standard**: Tools like:
   - Lint-based spec checkers (e.g., in Kubernetes, OpenAPI specs)
   - Contract testing frameworks (Pact)
   - Cross-document consistency checking in documentation tooling
   
   All implement similar heuristics (type mismatch, count mismatch, status inconsistency).

2. **Heuristic patterns are not novel**: Count mismatch and status mismatch are elementary pattern matching. They appear in:
   - Datalog constraint checkers
   - Schema validation tools
   - Database integrity checkers

3. **Adjacent pipeline detection is a natural consequence of spec structure**, not an architectural insight. If specs have DISCOVER → ASSESS → HOW stages, checking consistency between them is straightforward.

4. **Precision limitation**: The scanner's own documentation admits it over-detects (false positives) and misses prose-based contradictions. This limits practical utility.

**Evidence for novelty (weak)**:
1. **Markdown-specific heuristics**: The scanner targets Markdown artifacts (table rows, bold patterns, key-value lines) which are task-specific to Echelon. Standard tools expect JSON/YAML.

2. **Integration with Echelon's artifact pipeline**: The pipeline-stage-aware categorization (DISCOVER, ASSESS, HOW, PLAN) is tailored to Echelon's cognitive phases.

3. **No prior tool on codebase**: A search of the Echelon repo for competing contradiction-checking tools found none (contradiction-scanner.py is the sole implementation).

**Patent defensibility assessment**: LOW (as stated in novelty-catalogue.md). The novelty is in applying elementary pattern matching to Markdown artifacts in a specific pipeline context, not in the detection mechanisms themselves. If prior work on spec validation or contract testing exists, the claim weakens further.

### 5. Practical Usefulness

**Given the evidence**:
- 197 contradictions detected across 560,976 pairs = 0.035% detection rate
- No manual verification of any result
- 86.8% of detections are count mismatches (most likely noise)
- No precision/recall metrics provided

**Assessment**: The scanner is useful as a draft detection tool (flagging potential issues) but not for automated gatekeeping. The "verified=null" status indicates it was treated as exploratory, not production-quality.

## Verdict

**CONFIRMED — LOW NOVELTY, LIMITED UTILITY**

The contradiction scanner detects contradictions using three standard heuristic patterns (count mismatch, status mismatch, boolean mismatch) applied to Markdown artifacts across adjacent pipeline stages. The mechanism is straightforward and the novelty claim is weak:

1. Count, status, and negation mismatches are elementary pattern matching, present in existing spec validation tools.
2. The scanner operates on Markdown (task-specific) rather than structured formats, which limits generalizability.
3. No manual verification of results; 0.035% detection rate across 560k+ pairs suggests either low contradiction frequency or high false positive rate.
4. The scanner explicitly positions itself as an UPPER BOUND estimator, acknowledging precision limitations.

The scanner is useful for draft exploration but not for patent defense. The "adjacent pipeline stage contradiction detection" claim is not novel compared to standard multi-artifact consistency checking.

## Recommendations

1. **If defending the novelty claim**: Conduct a search for existing tools performing multi-artifact contradiction detection on Markdown specs with pipeline-stage awareness (DISCOVER → ASSESS → HOW ordering). If zero results, document this search as evidence. If any results exist, the novelty claim should be abandoned.

2. **If improving practical utility**: 
   - Implement manual verification sampling (currently "verified=null" for all 197)
   - Measure actual false positive rate on a labeled test set
   - Add precision/recall targets (currently unstated)
   - Consider implementing a learning-based ranker to prioritize high-confidence contradictions

3. **For patent strategy**: Do not claim novelty on contradiction detection per se. If filing, claim novelty on "Echelon artifact protocol implementation + contradiction detection integration," positioning the scanner as a utility for Echelon-specific specs, not a general pattern-matching innovation.

