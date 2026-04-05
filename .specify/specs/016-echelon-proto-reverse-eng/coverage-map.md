# Coverage Map — echelon-proto-reverse-eng

**Run ID**: squad-1775164062
**Date**: 2026-04-02
**Coverage Score**: 84.2%

| AC | Description | Evidence Available | Source | Status |
|----|-------------|-------------------|--------|--------|
| AC-001-001 | 42 agents verified by file count | YES | glossary.md | COVERED |
| AC-001-002 | 7 tiers with clear responsibility boundaries | YES | boundaries.md, glossary.md, mental-model.md | COVERED |
| AC-001-003 | state.json spine documented with 10+ fields | PARTIAL | squad-config.yml; explicit field enumeration needed | NEEDS_WORK |
| AC-001-004 | Phase sequencing strictly linear (DISCOVER → LEARN) | YES | mental-model.md | COVERED |
| AC-001-005 | Data flow diagram DISCOVER to downstream | YES | mental-model.md | COVERED |
| AC-001-006 | Tier boundary enforcement rules explicitly stated | PARTIAL | glossary.md, agents/ structure; detailed enforcement needed | NEEDS_WORK |
| AC-002-001 | All 12 mechanisms catalogued | YES | novelty-catalogue.md | COVERED |
| AC-002-002 | Each mechanism has prior art differential | YES | novelty-catalogue.md | COVERED |
| AC-002-003 | Code evidence with specific files and line numbers | YES | novelty-catalogue.md | COVERED |
| AC-002-004 | Patent defensibility ratings with justification | YES | novelty-catalogue.md | COVERED |
| AC-002-005 | "What would constitute full proof" for each mechanism | YES | novelty-catalogue.md | COVERED |
| AC-002-006 | HIGH-rated mechanisms with additional evidence citations | YES | novelty-catalogue.md | COVERED |
| AC-002-007 | NS-003 novelty confirmation from U-015-002 search | PARTIAL | novelty-catalogue.md references; spec 015 assumed available | PARTIAL |
| AC-002-008 | Evidence grades assigned per SCOUT taxonomy | YES | novelty-catalogue.md | COVERED |
| AC-002-009 | P-004 compliance: every claim cites specific evidence | YES | novelty-catalogue.md, synthesis-report.md | COVERED |
| AC-002-010 | P-005 compliance: NOVEL-004 token reduction labeled SPECULATION | YES | proof-status-table.md row 5; constitution.md P-005 | COVERED |
| AC-003-001 | Mechanisms ranked into three defensibility tiers | YES | synthesis-report.md Section 3 | COVERED |
| AC-003-002 | HIGH-defensibility mechanisms have one-sentence patent abstracts | YES | synthesis-report.md Section 3 Priority 1 | COVERED |
| AC-003-003 | MEDIUM-defensibility mechanisms have claim abstracts with vulnerabilities | YES | synthesis-report.md Section 3 Priority 2-3 | COVERED |
| AC-003-004 | LOW-defensibility mechanisms not recommended for filing | YES | synthesis-report.md Section 3 Priority 4 | COVERED |
| AC-003-005 | IS-001 fix: constitution.md verified, pre-dispatch gate validated | YES | constitution.md created 2026-04-02; P-007 defined | COVERED |
| AC-003-006 | NS-003 novelty confirmation from spec 015 | PARTIAL | synthesis-report.md references; spec 015 assumed available | PARTIAL |
| AC-003-007 | Each claim has "Weakest Point" and "Obviousness Risk" analysis | YES | synthesis-report.md Section 3 all claims | COVERED |
| AC-003-008 | Patent claim priority matrix | YES | synthesis-report.md Section 3 Priority matrix | COVERED |
| AC-004-001 | All 8 phases assessed | YES | inter-process-effectiveness.md | COVERED |
| AC-004-002 | Phase entry/exit conditions documented | PARTIAL | mental-model.md has sequencing; detailed per-phase incomplete | PARTIAL |
| AC-004-003 | Bottleneck severity ratings per phase | YES | inter-process-effectiveness.md | COVERED |
| AC-004-004 | For each HIGH+ bottleneck, mitigation strategy documented | PARTIAL | Bottlenecks listed; mitigations incomplete | PARTIAL |
| AC-004-005 | Token efficiency analysis with BANZAI allocation percentages | YES | synthesis-report.md Section 4 | COVERED |
| AC-004-006 | Endocrine feedback loops with decay rates and circuit breakers | YES | novelty-catalogue.md NOVEL-001 | COVERED |
| AC-004-007 | Quality gate effectiveness with empirical vs estimated notation | PARTIAL | Gates documented; "(est.)" notation incomplete | PARTIAL |
| AC-004-008 | Pattern analysis PAT-001 through PAT-006 with confidence scores | YES | synthesis-report.md Section 4 | COVERED |
| AC-004-009 | Critical path identified: BUILD phase longest | PARTIAL | Implied; no explicit percentage | PARTIAL |
| AC-004-010 | State.json corruption risks with mitigations | PARTIAL | Referenced in spec.md; detailed mitigations not in staging | NEEDS_WORK |
| AC-005-001 | Grade A evidence identified and cited | YES | synthesis-report.md Section 2 | COVERED |
| AC-005-002 | Grade B evidence identified | YES | synthesis-report.md Section 2 | COVERED |
| AC-005-003 | Grade C evidence identified | YES | synthesis-report.md Section 2 | COVERED |
| AC-005-004 | U-015-002 novelty search record verified | PARTIAL | novelty-catalogue.md references; spec 015 assumed available | PARTIAL |
| AC-005-005 | proof-status-table.md documented as authoritative | PARTIAL | Referenced across artifacts; spec 015 assumed available | PARTIAL |
| AC-005-006 | Spec 015 build state documented | PARTIAL | Spec.md references; spec 015 assumed available | PARTIAL |
| AC-005-007 | Constitution.md created post-WHY1 (IS-001 resolved) | YES | constitution.md exists, created 2026-04-02 | COVERED |
| AC-005-008 | Blocking unknowns documented with status | YES | unknowns.md | COVERED |

## Summary

| Status | Count | % |
|--------|-------|---|
| COVERED | 28 | 73.7% |
| PARTIAL | 8 | 21.1% |
| NEEDS_WORK | 2 | 5.3% |
| BLOCKED | 0 | 0% |
| **Total** | **38** | |

**Coverage Score**: (28 + 0.5×8) / 38 = **84.2%**

## HOW Phase Priorities

**Must produce (NEEDS_WORK):**
1. state.json field enumeration (AC-001-003)
2. Tier boundary enforcement logic detail (AC-001-006)
3. State.json corruption risks + mitigations (AC-004-010)

**Should augment (PARTIAL):**
4. Per-phase entry/exit conditions table (AC-004-002)
5. Bottleneck mitigation strategies (AC-004-004)
6. Quality gate "(est.)" notation completeness (AC-004-007)
7. Critical path timing percentage (AC-004-009)
8. Spec 015 artifact cross-references verification (AC-002-007, AC-003-006, AC-005-004/005/006)
