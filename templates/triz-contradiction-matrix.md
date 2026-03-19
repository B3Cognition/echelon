# TRIZ Contradiction Matrix — Software Engineering Adaptation

Source: Altshuller's contradiction matrix adapted for software systems
Standard: ISO/TR 18686:2017
Reference: https://www.triz40.com/

Used by: INNOVATE agent (Phase 2: AutoTRIZ — Step 2: Map to parameters)

## How to Use

1. Identify the **improving parameter** (what you want to make better)
2. Identify the **worsening parameter** (what degrades when you improve #1)
3. Find the intersection in the matrix → suggested inventive principles
4. Read each principle from `triz-40-principles.md` and generate a concrete solution

## Software Engineering Parameters

Adapted from Altshuller's 39 engineering parameters to software-relevant concerns:

| # | Parameter | Software Meaning |
|---|-----------|-----------------|
| 1 | **Speed/Performance** | Response time, throughput, processing speed |
| 2 | **Reliability** | Uptime, fault tolerance, error rate |
| 3 | **Scalability** | Ability to handle growing load/data/users |
| 4 | **Security** | Protection against threats, data integrity, access control |
| 5 | **Maintainability** | Ease of change, readability, debugging |
| 6 | **Complexity** | Number of components, dependencies, cognitive load |
| 7 | **Resource Usage** | CPU, memory, storage, network, cost |
| 8 | **Development Speed** | Time to implement, iteration speed |
| 9 | **Testability** | Ease of writing and running tests, coverage |
| 10 | **Flexibility** | Ability to adapt to new requirements |
| 11 | **Data Freshness** | How current/real-time the data is |
| 12 | **User Experience** | Responsiveness, clarity, accessibility |
| 13 | **Coupling** | Degree of interdependence between components |
| 14 | **Observability** | Ability to understand system state, debug issues |
| 15 | **Portability** | Ability to run in different environments |
| 16 | **Consistency** | Data consistency, UI consistency, behavioral predictability |

## Contradiction Matrix

Read as: "Improving ROW degrades COLUMN → use these principles"

| Improving ↓ \ Worsening → | Speed | Reliability | Scalability | Security | Maintainability | Complexity | Resource Usage | Dev Speed |
|---------------------------|-------|------------|------------|----------|----------------|-----------|---------------|-----------|
| **Speed** | — | 11,35,27 | 1,5,15 | 24,28 | 6,3 | 2,17 | 10,19,16 | 21,16 |
| **Reliability** | 11,35 | — | 1,24 | 33,9 | 3,25 | 7,24 | 10,27 | 16,11 |
| **Scalability** | 1,5,15 | 1,24 | — | 24,3 | 1,17 | 1,6 | 37,27 | 27,16 |
| **Security** | 24,28 | 33,9 | 24,3 | — | 6,3 | 7,39 | 35,28 | 16,11 |
| **Maintainability** | 6,3 | 3,25 | 1,17 | 6,3 | — | 1,2,3 | 12,33 | 5,6 |
| **Complexity** (reduce) | 2,17 | 7,24 | 1,6 | 7,39 | 1,2,3 | — | 12,6 | 27,5 |
| **Resource Usage** (reduce) | 10,19 | 10,27 | 37,27 | 35,28 | 12,33 | 12,6 | — | 27,16 |
| **Dev Speed** | 21,16 | 16,11 | 27,16 | 16,11 | 5,6 | 27,5 | 27,16 | — |
| **Testability** | 3,12 | 23,25 | 1,3 | 26,9 | 25,3 | 3,1 | 27,12 | 26,5 |
| **Flexibility** | 15,35 | 15,11 | 15,1 | 15,39 | 15,3 | 15,6 | 15,27 | 15,5 |
| **Data Freshness** | 10,19,20 | 11,23 | 20,5 | 24,11 | 19,3 | 19,6 | 19,10 | 16,20 |
| **User Experience** | 21,14 | 11,23 | 6,12 | 39,24 | 12,3 | 6,3 | 12,14 | 5,6 |
| **Coupling** (reduce) | 2,24 | 2,7 | 1,2 | 2,39 | 2,1,3 | 2,1 | 2,12 | 2,5 |
| **Observability** | 32,23 | 32,23 | 32,14 | 32,39 | 32,3 | 32,6 | 32,35 | 32,5 |
| **Consistency** | 16,33 | 33,23 | 33,1 | 33,39 | 33,3 | 33,6 | 33,12 | 33,5 |

## Common Software Contradictions and Solutions

### Speed vs Reliability
**Contradiction:** Faster processing (skip validation) reduces reliability (unvalidated data)
**Principles:** 11 (Beforehand Cushioning), 35 (Parameter Changes), 27 (Cheap Short-Lived)
**Solution:** Pre-validate at ingestion (Principle 10), use tiered validation — fast check inline, thorough check async (Principle 3)

### Speed vs Data Freshness
**Contradiction:** Caching improves speed but data becomes stale
**Principles:** 10 (Preliminary Action), 19 (Periodic Action), 20 (Continuity of Useful Action)
**Solution:** Cache with TTL per data type (Principle 3 Local Quality) — hot data 10s, warm data 5min, cold data 1h

### Scalability vs Complexity
**Contradiction:** Scaling out (microservices) increases system complexity
**Principles:** 1 (Segmentation), 6 (Universality)
**Solution:** Modular monolith (Principle 1 internal segmentation without distributed complexity). Extract to service only when proven necessary.

### Security vs User Experience
**Contradiction:** More security steps (MFA, captcha) worsen user experience
**Principles:** 39 (Inert Atmosphere), 24 (Intermediary)
**Solution:** Risk-based authentication (Principle 3) — frictionless for low-risk, MFA for high-risk. Use SSO as intermediary (Principle 24).

### Maintainability vs Performance
**Contradiction:** Clean code abstractions add overhead. Raw optimized code is hard to maintain.
**Principles:** 6 (Universality), 3 (Local Quality)
**Solution:** Clean abstractions everywhere, optimize only measured bottlenecks (Principle 3 Local Quality). 80% clean, 20% optimized where profiling proves necessary.

### Development Speed vs Testability
**Contradiction:** Writing tests slows development. Skipping tests speeds development but increases bugs.
**Principles:** 26 (Copying), 5 (Merging)
**Solution:** Generate tests from specs (Principle 26 — copy the spec into test form). Co-locate test with implementation (Principle 5 — merge dev and test activity).

### Flexibility vs Consistency
**Contradiction:** Supporting many use cases (flexible) makes behavior unpredictable (inconsistent)
**Principles:** 15 (Dynamics), 3 (Local Quality)
**Solution:** Configuration-driven flexibility with validated presets (Principle 15 + 11). Each preset is consistent; the system is flexible across presets.

### Coupling vs Development Speed
**Contradiction:** Decoupling (interfaces, abstractions) takes longer to build initially
**Principles:** 2 (Taking Out), 5 (Merging)
**Solution:** Start coupled, extract interfaces at natural seams when the boundary is proven (Principle 2). Don't pre-optimize boundaries — let usage reveal them.

### Observability vs Resource Usage
**Contradiction:** More logging/tracing/metrics consumes more CPU, memory, storage
**Principles:** 32 (Colour Changes), 35 (Parameter Changes)
**Solution:** Sampling (Principle 16 — partial action). Structured logging (Principle 38 — enriched context with less volume). Dynamic log levels (Principle 35 — change verbosity based on need).

## How INNOVATE Uses This

1. Read the current design's sticking point
2. Identify the contradiction: "improving X worsens Y"
3. Map X and Y to parameters in the table above
4. Find the intersection → principle numbers
5. Read each principle from `triz-40-principles.md`
6. Generate 2-3 concrete solutions that RESOLVE the contradiction (both parameters satisfied)
7. Present as alternatives in `alternatives.md` with evidence grade B (ISO/TR 18686)
