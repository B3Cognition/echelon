# Cross-Validation Verification Scenarios

These scenarios test that cross-validation rules correctly flag suspicious metric combinations.

## CV Rule Definitions

- **CV-2**: Flags when terminology adoption (I-03) is high but constraint accuracy (I-05) is low. Pattern: "high-terminology-low-accuracy". Condition: I-03 >= 0.85 AND I-05 < 0.75.
- **CV-3**: Flags when requirement coverage (I-01) is high but terminology fidelity (I-03) is low. Pattern: "citation-stuffing-low-fidelity". Condition: I-01 >= 0.85 AND I-03 < 0.50.

---

## Scenario 1: CV-2 fires — High Terminology, Low Accuracy

**Description:** The agent uses nearly all glossary terms correctly but fails to respect numeric constraints. This suggests surface-level terminology adoption without genuine understanding of the specification values.

**Metric Values:**
| Metric | Score | Interpretation |
|--------|-------|----------------|
| I-01   | 0.80  | Requirement coverage: 4 of 5 FR-IDs referenced |
| I-03   | 0.95  | Terminology fidelity: 9.5 of 10 glossary terms used correctly |
| I-05   | 0.72  | Constraint accuracy: only 1 of 3 numeric constraints respected |

**Expected Result:** Flag `high-terminology-low-accuracy` fires (CV-2 condition met: I-03=0.95 >= 0.85 AND I-05=0.72 < 0.75).

**Rationale:** Agent parrots vocabulary from the spec but does not internalize the actual numeric bounds, suggesting shallow processing.

---

## Scenario 2: CV-3 fires — High Coverage, Low Fidelity

**Description:** The agent references all requirement IDs but uses very few glossary terms. This suggests the agent is mechanically citing requirement identifiers without engaging with the domain language.

**Metric Values:**
| Metric | Score | Interpretation |
|--------|-------|----------------|
| I-01   | 0.95  | Requirement coverage: all 5 FR-IDs referenced, some multiple times |
| I-03   | 0.35  | Terminology fidelity: only 3.5 of 10 glossary terms used |
| I-05   | 0.80  | Constraint accuracy: 2 of 3 constraints respected |

**Expected Result:** Flag `citation-stuffing-low-fidelity` fires (CV-3 condition met: I-01=0.95 >= 0.85 AND I-03=0.35 < 0.50).

**Rationale:** Agent appears to copy-paste requirement IDs for completeness but does not demonstrate understanding of the domain terminology, which is a hallmark of citation stuffing.

---

## Scenario 3: No flags — Balanced scores

**Description:** The agent demonstrates balanced internalization across all measured dimensions. No single metric is disproportionately high or low relative to others.

**Metric Values:**
| Metric | Score | Interpretation |
|--------|-------|----------------|
| I-01   | 0.85  | Requirement coverage: solid but not suspiciously perfect |
| I-03   | 0.80  | Terminology fidelity: 8 of 10 glossary terms used |
| I-05   | 0.82  | Constraint accuracy: all constraints respected with minor margin |

**Expected Result:** No flags fire.
- CV-2 not triggered: I-03=0.80 < 0.85 threshold (condition not met)
- CV-3 not triggered: I-03=0.80 >= 0.50 (condition not met)

**Rationale:** Scores are internally consistent. The agent demonstrates proportional internalization across coverage, terminology, and accuracy dimensions.
