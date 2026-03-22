# Diagnostic Matrix Verification Scenarios

The diagnostic matrix combines Understanding scores (from the 31-metric framework) with Internalization gate pass rates (from the 16-metric framework) to classify agent performance into four quadrants.

## Quadrant Definitions

|                        | Int-Gate Pass Rate >= 0.70 | Int-Gate Pass Rate < 0.70 |
|------------------------|----------------------------|---------------------------|
| **Understanding >= 0.70** | Q1: Proceed with confidence | Q2: Prompt problem          |
| **Understanding < 0.70**  | Q3: Spec problem            | Q4: Systemic issue          |

---

## Scenario Q1: Proceed with confidence

**Understanding Score:** 0.85
**Internalization Gate Pass Rate:** 0.90 (e.g., 14 of 16 metrics above their thresholds)

**Diagnosis:** Proceed with confidence

**Interpretation:** The agent both understands the specification (high comprehension, reasoning, mapping scores) and has successfully internalized it (high coverage, accuracy, fidelity, traceability). The agent is ready to execute tasks grounded in the spec.

**Recommended Action:** Allow the agent to proceed to task execution. Monitor outputs for drift but no corrective intervention is needed.

---

## Scenario Q2: Prompt problem

**Understanding Score:** 0.82
**Internalization Gate Pass Rate:** 0.40 (e.g., only 6 of 16 metrics above their thresholds)

**Diagnosis:** Prompt problem

**Interpretation:** The agent understands the spec content (it can answer questions about requirements, reason about constraints) but fails to internalize it into its working context (low citation rates, poor constraint adherence, missing dependency references). The spec comprehension is present but the prompting strategy does not elicit proper internalization behavior.

**Recommended Action:** Revise the system prompt or internalization instructions. Add explicit directives to cite requirement IDs, use glossary terms, and validate against numeric constraints. Re-run internalization and re-evaluate gate pass rate.

---

## Scenario Q3: Spec problem

**Understanding Score:** 0.55
**Internalization Gate Pass Rate:** 0.85 (e.g., 13 of 16 metrics above their thresholds)

**Diagnosis:** Spec problem

**Interpretation:** The agent mechanically internalizes the spec (references IDs, uses terms, respects constraints) but does not actually understand it (low comprehension scores, poor reasoning about edge cases, weak structural mapping). The spec itself may be ambiguous, contradictory, or poorly structured, causing the agent to parrot without comprehending.

**Recommended Action:** Review and improve the specification. Clarify ambiguous requirements, resolve contradictions, add examples and rationale. The internalization machinery works, but the input material is inadequate for genuine understanding.

---

## Scenario Q4: Systemic issue

**Understanding Score:** 0.50
**Internalization Gate Pass Rate:** 0.35 (e.g., only 5 of 16 metrics above their thresholds)

**Diagnosis:** Systemic issue

**Interpretation:** The agent neither understands nor internalizes the specification. Both the comprehension pipeline and the internalization pipeline are failing. This typically indicates a fundamental mismatch: the spec may be too complex for the agent's capacity, the agent may lack domain knowledge prerequisites, or there may be infrastructure issues (context window overflow, prompt truncation, retrieval failures).

**Recommended Action:** Investigate root causes systematically. Check context window utilization, verify spec is fully loaded, test with a simpler spec to isolate agent capability vs spec complexity. Consider decomposing the spec into smaller, independently testable units. Address both understanding and internalization issues before proceeding.
