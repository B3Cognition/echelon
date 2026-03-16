# Evidence Quality Grades

Used by SCIENTIST to grade all research sources.

| Grade | Description | Examples | Weight |
|-------|-------------|----------|--------|
| **A** | Peer-reviewed research, ISO/IEEE standard | IEEE 830, published papers with peer review | 1.0 |
| **B** | Official documentation, proven benchmark | Framework docs, reproducible benchmarks | 0.8 |
| **C** | Well-regarded blog, conference talk, case study | ThoughtWorks Radar, StrangeLoop talks | 0.6 |
| **D** | Stack Overflow, forum post, anecdotal | Accepted SO answers, Reddit threads | 0.3 |
| **E** | AI training data (unverified, possibly stale) | LLM-generated without citation | 0.1 |

## Grading Rules

1. Every recommendation from SCIENTIST must cite at least one source with its grade
2. Recommendations based solely on grade E evidence must be flagged as LOW_CONFIDENCE
3. Conflicting evidence: higher grade wins. Same grade: more recent wins.
4. SCIENTIST must attempt to find grade A-B evidence before falling back to C-E
5. Grade upgrades: if SCIENTIST experiment validates a grade C-E finding, it becomes grade B
