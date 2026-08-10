# Scorekeeper Scoring Reference

## Performance Points

| Action | Points | Agent | Description |
|--------|--------|-------|-------------|
| First-pass approval | +3 | echelon-implementer (IMPLEMENTER) | Task passes echelon-spec-guard (SPEC GUARD) + echelon-code-reviewer (CODE REVIEWER) on first try |
| Rework required | -1 | echelon-implementer (IMPLEMENTER) | Task needs fixes after review |
| Third rework | -3 | echelon-implementer (IMPLEMENTER) | Same task fails review 3 times |
| Critical bug caught | +5 | WHY, echelon-spec-guard (SPEC GUARD) | Found a CRITICAL issue that would have reached production |
| High bug caught | +3 | WHY, echelon-spec-guard (SPEC GUARD) | Found a HIGH issue |
| False positive | -1 | WHY, echelon-spec-guard (SPEC GUARD) | Flagged an issue that wasn't actually a problem |
| Accurate estimate | +3 | ASSESS | Estimate within 20% of actual |
| Inaccurate estimate | -2 | ASSESS | Estimate off by > 50% |
| Assumption validated | +2 | SCIENTIST | Empirical evidence confirmed an assumption |
| Assumption invalidated | +4 | SCIENTIST | Found that an assumption was WRONG (more valuable — prevented bad decisions) |
| Architecture held | +3 | HOW | ADR decision survived implementation without changes |
| Architecture changed | -1 | HOW | ADR had to be revised during build |
| Gap found by echelon-verification (VERIFICATION) | -2 | echelon-spec-guard (SPEC GUARD) | echelon-verification (VERIFICATION) found a requirement echelon-spec-guard (SPEC GUARD) missed |
| 100% coverage on verification | +5 | echelon-spec-guard (SPEC GUARD) | Zero gaps found by echelon-verification (VERIFICATION) |
| Internalization: 6/6 | +2 | Any build agent | Perfect internalization score |
| Internalization: <4/6 | -2 | Any build agent | Failed internalization |
| Doubt raised that revealed gap | +3 | Any agent | During internalization, raised a question that exposed a missing artifact |
| Knowledge transfer: READY | +3 | REFLECT | Project fully documented for handoff |
| Knowledge transfer: NOT_READY | -2 | REFLECT | Critical knowledge gaps remain |

## Peer Appreciation Points

| Appreciation | Points | When |
|-------------|--------|------|
| "Clear and actionable" | +2 | Agent received artifacts that required zero clarification |
| "Unblocked my work" | +3 | Agent's output directly enabled another agent to succeed |
| "Caught my mistake" | +2 | Agent found an error in the appreciating agent's work (acknowledge, don't resent) |
| "Exceptional quality" | +4 | Agent's output was significantly above baseline |
| "Needed rework" | -1 | Agent received artifacts that required significant rework to use |

Peer appreciation is recorded with:

```yaml
- from: "echelon-implementer (IMPLEMENTER)"
  to: "HOW"
  type: "clear_and_actionable"
  points: +2
  reason: "ADR-005 component encapsulation decision had exact code examples — zero ambiguity"
  task: "T033"
```

## Performance Badges

| Badge | Criteria | Emoji |
|-------|----------|-------|
| **First Blood** | First task completed in the run | ★ |
| **Perfect Sprint** | 5 consecutive first-pass approvals | ★★ |
| **Bug Hunter** | Caught 5+ CRITICAL/HIGH issues in one run | ★★★ |
| **Oracle** | 3 consecutive accurate estimates (within 20%) | ★★ |
| **Scientist of the Run** | SCIENTIST investigation that changed an architecture decision | ★★★ |
| **Guardian Angel** | echelon-verification (VERIFICATION) found zero gaps (echelon-spec-guard (SPEC GUARD) caught everything) | ★★★ |
| **Internalization Master** | 6/6 internalization score on first attempt, 3 runs in a row | ★★ |
| **Peer Favorite** | Most peer appreciation points in a run | ★★ |
| **Comeback** | Failed internalization, then achieved first-pass approval on all tasks | ★★ |

## Negative Badges

| Badge | Criteria | Signal |
|-------|----------|--------|
| **Rework Magnet** | 3+ tasks required rework in one run | Prompt needs refinement |
| **False Alarm** | 3+ false positives in one run (WHY/echelon-spec-guard (SPEC GUARD)) | Over-aggressive validation |
| **Blind Spot** | echelon-verification (VERIFICATION) found 3+ gaps echelon-spec-guard (SPEC GUARD) missed | Per-task checking insufficient |
| **Optimist** | 3+ estimates off by > 50% | Calibration needed |

## Prompt Refinement Triggers

| Signal | Action |
|--------|--------|
| echelon-implementer (IMPLEMENTER) score < -5 over 3 runs | Flag: echelon-implementer (IMPLEMENTER) prompt needs more examples or stricter constraints |
| WHY false positive rate > 30% | Flag: WHY prompt is over-aggressive — add "verify before flagging" instruction |
| echelon-spec-guard (SPEC GUARD) "Blind Spot" badge | Flag: echelon-spec-guard (SPEC GUARD) needs aggregate checking, not just per-task |
| ASSESS "Optimist" badge | Increase correction factor in calibration-profile.yaml automatically |
| Any agent internalization < 4/6 twice | Flag: context pack for that agent is insufficient — add more artifacts |

## Token Efficiency Points

| Action | Points | Agent | Description |
|--------|--------|-------|-------------|
| Token-efficient task | +2 | Any | Task completed with token cost < 80% of average per-task budget |
| Token-heavy task | -1 | Any | Task consumed > 150% of average per-task budget |
| Token hog | -3 | Any | Single agent consumed > 40% of total run tokens |
| Budget saver | +3 | Any | Agent completed all assigned work using < 60% of allocated tier budget |

Efficiency rating thresholds:
- **efficient**: avg tokens/dispatch < 80% of squad-wide average
- **normal**: 80-150% of squad-wide average
- **heavy**: 150-200% of squad-wide average
- **hog**: > 200% of squad-wide average

## Token Efficiency Badges

| Badge | Criteria | Emoji |
|-------|----------|-------|
| **Lean Machine** | Token efficiency rating "efficient" for 3+ consecutive runs | ★★ |
| **Token Hog** | Token efficiency rating "hog" in a run | (negative) |

## Marketplace Badge

| Badge | Criteria | Emoji |
|-------|----------|-------|
| **Community Contributor** | A pattern the agent helped create has been reused 5+ times across projects | ★★★ |

## Internalization Trend Points

| Action | Points | Description |
|--------|--------|-------------|
| Internalization improving for 3+ runs | +2 | Sustained learning improvement |
| Internalization declining for 3+ runs | -2 | Sustained degradation — flag for prompt review |
| Composite score >= 0.90 | +1 | Excellent spec comprehension |
| Composite score < 0.50 | -1 | Poor spec comprehension — needs intervention |

## Internalization Badges

| Badge | Criteria | Emoji |
|-------|----------|-------|
| **Deep Learner** | Composite score >= 0.85 for 5 consecutive runs | ★★★ |
| **Absorption Gap** | Absorption category < 0.50 for 2 consecutive runs | (negative) |
