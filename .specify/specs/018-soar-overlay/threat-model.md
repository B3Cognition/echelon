# Threat Model — Spec 018: SOAR Cognitive Architecture Overlay

**Produced by:** GUARDIAN (SECURITY)  
**Date:** 2026-04-03  
**Mode:** Minimum Security Checklist (non-security-sensitive domain, always_on)  
**Domain classification:** Internal cognitive architecture extension — no auth, no payments, no PII, no external network exposure  
**Sources reviewed:** `spec.md`, `boundaries.md`, `investigation/iss002-context-pack-keys.md`, root `.gitignore`

---

## Executive Summary

The SOAR overlay is an internal, stdlib-only Python module with no external network exposure and no user-facing surfaces. The primary attack surface is the local filesystem: production rules and impasse logs are stored in run-scoped JSON files keyed by `run_id`. The five questions raised in the dispatch task identify four real vulnerabilities — one HIGH (path traversal via unsanitized `run_id`), two MEDIUM (soar_state data leakage through context_pack forwarding, and missing integrity protection on the ProceduralMemoryStore), and one LOW (bounded DoS risk from malformed production rules). No compliance frameworks apply. All findings are ACCEPT_WITH_MITIGATIONS per the Risk Acceptance Protocol.

---

## Minimum Security Checklist

| # | Check | Status | Finding |
|---|-------|--------|---------|
| 1 | Secrets in Config | PASS | No secrets, API keys, or credentials appear in spec.md, boundaries.md, or investigation files. The overlay uses only local filesystem paths and stdlib. No secrets management strategy required — none applicable. |
| 2 | Input Validation at Boundaries | FAIL | `run_id` is accepted as a raw string from COMMANDER and used directly in filesystem paths (`soar-procedural-{run_id}.json`, `soar-impasse-{run_id}.json`). No sanitization is specified anywhere in spec.md, boundaries.md, or the boundary trust model. Path traversal characters (`../`, `/`, `%2F`, null bytes) in `run_id` are not addressed. |
| 3 | Auth/AuthZ | N/A | Purely internal module-to-module call (COMMANDER imports the overlay directly). No user-facing surfaces. No authentication or authorization applies. |
| 4 | Dependency Security | PASS | NFR-SOAR-001 mandates stdlib-only. No third-party packages. No supply chain risk. Zero non-stdlib imports is a verifiable constraint enforced by static analysis. |
| 5 | Data Handling Compliance | PASS (with note) | The overlay processes no PII, financial data, or health data. The `soar_state` injected into context_pack reflects WME state derived from agent operational context (goal text, buffer contents, workspace items). These are cognitive architecture internals, not personal data. The note: `wme_snapshot` is written to impasse logs — if upstream overlays ever inject PII into context_pack keys (currently none do), the impasse log would capture it. This is a hypothetical risk in the current domain but should be documented as a logging hygiene rule for future overlay authors. |

**Overall:** 3/5 PASS, 1 FAIL, 1 N/A  
**Recommendation:** PROCEED_WITH_WARNINGS — the path traversal finding (Check 2) must be addressed before BUILD phase. Mitigation is low-cost (a single sanitization function).

---

## Five-Question Security Analysis

### Q1: JSON Injection Risks in Production Rule Files

**Finding: LOW risk — no JSON injection vector exists in the current design.**

Production rules are stored in `.specify/squad/soar-procedural-{run_id}.json`. The threat scenario is: could an attacker inject malicious JSON into this file?

**Analysis:**
- The file is written by `update_soar_memory` using Python's `json.dumps` serialization. All ChunkRecord fields (`rule_id`, `conditions`, `actions`, `confidence`, `learned`, `episode_id`) are Python objects serialized by the stdlib `json` module. The `json` module correctly escapes all special characters; it is not possible to inject raw JSON syntax through stdlib serialization.
- Seed rules are hand-coded by the developer. They are developer-trusted artifacts.
- The file lives on the local filesystem, gitignored, with no external write path.
- The only realistic JSON injection scenario would be if `actions` (the enrichment payload) were constructed by string concatenation rather than dict assignment before serialization. The spec does not specify the construction method; the HOW spec must ensure `actions` is always a Python dict passed to `json.dumps`, not a pre-formatted string.

**Residual risk:** LOW. Stdlib JSON serialization eliminates injection at the serialization layer. The only remaining risk is an implementation error in ChunkRecord `actions` construction.

**Mitigation:** HOW spec must require that ChunkRecord `actions` is constructed as a Python dict (not a string) before serialization. Static analysis (type hints + mypy) would catch violations.

---

### Q2: File Path Safety — `run_id` Path Traversal

**Finding: HIGH risk — `run_id` is used unsanitized in filesystem paths.**

The spec defines two file paths that embed `run_id` directly:
- `.specify/squad/soar-procedural-{run_id}.json`
- `.specify/squad/soar-impasse-{run_id}.json`

**Attack scenario:** If COMMANDER passes a `run_id` value containing path traversal characters, the overlay would open files outside `.specify/squad/`. Examples:
- `run_id = "../state"` → path becomes `.specify/squad/../state.json` → reads/writes COMMANDER's `state.json`
- `run_id = "../../scripts/ca/soar_overlay"` → path resolves to a Python module file
- `run_id = "/etc/passwd"` → on POSIX, absolute path override (Python's `open` with an absolute path ignores the prefix)
- `run_id = "proc\x00evil"` → null byte injection (Python 3 raises `ValueError` for embedded nulls, so this is mitigated automatically)

**Boundary trust model assessment:** `boundaries.md` classifies the trust level of `context_pack` contents as "Full trust — comes from COMMANDER, not external input." However, `run_id` is not part of `context_pack` — it is a separate parameter passed by COMMANDER. The boundaries document does not classify the trust level of `run_id` explicitly. This is a gap.

**In the current system:** COMMANDER is the sole caller and is a trusted internal agent. In practice, `run_id` values are system-generated timestamps or sequential IDs (e.g., `test-run-001`, as seen in the squad directory: `goal-stack-test-run-001.json`, `episodic-index-test-run-001.json`). The risk is theoretical for the current deployment.

**However:** The absence of sanitization means any future COMMANDER modification, test harness, or external orchestration layer that passes an unvalidated `run_id` creates an immediate path traversal vulnerability. The spec does not specify `run_id` format or validation at any layer.

**Existing evidence from squad directory:** Files like `goal-stack-test-run-001.json` confirm the existing convention is alphanumeric with hyphens. This convention should be enforced, not assumed.

**Risk Acceptance Record:**

### RAR-001: Path Traversal via Unsanitized `run_id`

**Risk:** A caller passing a crafted `run_id` (e.g., `"../state"`) causes `soar_overlay.py` to read or write files outside `.specify/squad/`, potentially overwriting COMMANDER's `state.json` or other overlay state files.  
**Probability:** 0.1 (current callers are trusted; risk is from future modification or test harness misuse)  
**Impact:** HIGH (could corrupt COMMANDER state, overwrite episodic index, or read arbitrary files)  
**Confidence in mitigation:** 0.95 (a simple regex sanitization is fully effective)  
**Evidence grade:** B (direct analysis of spec + file naming conventions observed in squad directory)  
**Affected compliance:** NONE

**Mitigation path:**
1. Define `run_id` format as a constrained alphanumeric-plus-hyphens string (regex: `^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$`)
2. Add a `_validate_run_id(run_id: str) -> None` function at the top of `soar_overlay.py` that raises `ValueError` if `run_id` does not match the pattern
3. Call `_validate_run_id` as the first statement in both `enrich_context` and `update_soar_memory`
4. COMMANDER exception-handling wrapper (already required by NFR-SOAR-004) will catch the `ValueError` and fall back to unenriched context_pack — no dispatch is blocked
5. Add the format constraint to the spec as a new NFR or as an amendment to FR-SOAR-002

**Residual risk after mitigation:** LOW  
**Autonomous decision:** ACCEPT_WITH_MITIGATIONS  
**Reasoning:** The risk is real but the mitigation is trivial (5 lines of code), the compliance domain is NONE, and the current deployment environment has trusted callers. The absence of an external attack surface limits actual exploitability to internal actors. The mitigation must be implemented before BUILD phase to prevent the vulnerability from being encoded into the implementation.

---

### Q3: Data Leakage — `soar_state` in Context Pack

**Finding: MEDIUM risk — `soar_state` exposes WME state from prior dispatch cycles to downstream agents.**

**Analysis:** The `soar_state` key injected by the overlay contains:
- `operator_applied` (name of the winning production rule)
- `impasse` (boolean — whether no rule matched)
- `cycle` (the dispatch cycle count)
- `wme_count` (number of WMEs extracted)

These fields are injected into `context_pack`, which is then passed to the dispatched agent. The agent receives the full context_pack, meaning it can read `soar_state`.

**What could leak:**
- `operator_applied` encodes which production rule fired. If rule names are descriptive (e.g., `"seed-scout-analysis-with-episodic-prior"`), this reveals architectural state about what context the system concluded was active. In a cognitive architecture with security-sensitive goal states, rule names could reveal classified information about the system's current task.
- `impasse: true` reveals that the system's procedural memory had no applicable rule — which reveals something about the system's knowledge state.
- `wme_count` reveals how many context_pack keys were present, which is indirect information about which prior overlays succeeded.

**In the current domain:** context_pack contains cognitive architecture internals, not personal data or secrets. The dispatched agents are internal Echelon agents (SCOUT, GUARDIAN, BUILD, WHAT). The "leakage" is intentional context enrichment — agents are expected to read `soar_state`. Open Question OQ-006 in `spec.md` explicitly asks whether `soar_state["impasse"]` should be visible to agents or kept internal — this question is unresolved.

**Residual risk:** The risk is that if agents act on SOAR metadata (especially `impasse`) in ways that degrade their reasoning — for example, an agent that receives `impasse: true` and becomes overly conservative — the leakage affects system behavior even though no confidential data is exposed.

**A second leakage vector:** The `wme_snapshot` field in `ImpasseEvent` (written to `soar-impasse-{run_id}.json`) is not length-constrained in the spec. It contains a snapshot of the full WME state at impasse time. If WME values contain sensitive content from an upstream overlay, the impasse log records it verbatim. The 200-character truncation on individual WME values (FR-SOAR-003) provides partial protection, but a WME snapshot with 50 keys × 200 characters = up to 10,000 characters of context is written to a file.

**Risk Acceptance Record:**

### RAR-002: Context-Pack-Level Information Disclosure via soar_state

**Risk:** `soar_state` (including `operator_applied`, `impasse`, `cycle`, `wme_count`) is forwarded to dispatched agents, revealing SOAR procedural memory state that was not explicitly intended for agent consumption. WME snapshots in impasse logs record up to 10KB of context state per impasse.  
**Probability:** 0.3 (agents likely read the full context_pack; impasse log accumulates unbounded WME data)  
**Impact:** MEDIUM (cognitive architecture state disclosure; no PII or credentials; no external leakage)  
**Confidence in mitigation:** 0.80  
**Evidence grade:** B  
**Affected compliance:** NONE

**Mitigation path:**
1. Resolve OQ-006 explicitly: document in spec whether `soar_state["impasse"]` is intentionally agent-visible or should be stripped before dispatch
2. Add a `wme_snapshot` size cap to the ImpasseEvent schema: serialize the snapshot then truncate to a maximum byte length (e.g., 2KB) before writing to the impasse log
3. If certain WME values are classified as internal-only in future overlay versions, document a WME-level sensitivity classification in the overlay contract

**Residual risk after mitigation:** LOW  
**Autonomous decision:** ACCEPT_WITH_MITIGATIONS  
**Reasoning:** No PII or secrets are present in the current domain. The disclosure is of cognitive architecture metadata, not sensitive user data. The compliance domain is NONE. The mitigations are documentation-level and a single size cap — both low cost.

---

### Q4: Integrity — Production Rule Tampering Between Dispatches

**Finding: MEDIUM risk — no integrity protection on ProceduralMemoryStore.**

**Analysis:** `soar-procedural-{run_id}.json` is:
- Written by `update_soar_memory` after each successful dispatch
- Read fresh by `enrich_context` at each subsequent dispatch (per AC-3.5: "the newly written ChunkRecord is available for matching")
- A plain JSON file on the local filesystem with no checksum, signature, or schema validation specified

**Tampering scenarios:**
1. **Local filesystem tampering:** A process running concurrently on the same machine (a test script, a bug in another overlay, or an operator mistake) could overwrite or corrupt `soar-procedural-{run_id}.json` between dispatches. The spec acknowledges single-writer safety (A-005 validated) but only for COMMANDER's sequential dispatch pattern — it does not address external writers.
2. **Malformed JSON injection:** If the file is externally modified to contain invalid JSON, `json.loads` would raise a `JSONDecodeError`. The spec does not specify how `enrich_context` handles a corrupt ProceduralMemoryStore. If the exception propagates, COMMANDER's exception handler catches it and dispatches with unenriched context_pack (per NFR-SOAR-004). But seed rules are lost.
3. **Schema-valid but semantically malicious ChunkRecord:** A tampered ChunkRecord could have `confidence: 1.0` (max score) with conditions that always match and an `actions` payload that injects misleading enrichment. Since the file has no signature, the overlay cannot distinguish a legitimate ChunkRecord from a tampered one. In the current trusted deployment, this requires local filesystem access — which implies a compromised machine, not a realistic attack.
4. **Seed rule replacement:** If the file already exists from a prior write (legitimate or tampered), AC-4.3 specifies the overlay loads it without re-seeding. A tampered file that retains valid JSON structure but replaced all seed rules with adversarial rules would be loaded without detection.

**Risk Acceptance Record:**

### RAR-003: ProceduralMemoryStore Integrity — No Signing or Validation

**Risk:** `soar-procedural-{run_id}.json` has no integrity protection. External modification (corrupt JSON, adversarial ChunkRecords, seed rule replacement) would be silently accepted by `enrich_context`.  
**Probability:** 0.05 (requires local filesystem access; deployment is a local developer workstation; no external attack surface)  
**Impact:** MEDIUM (incorrect SOAR operator selection degrades enrichment quality; no data loss or security boundary crossing in current domain)  
**Confidence in mitigation:** 0.85  
**Evidence grade:** B  
**Affected compliance:** NONE

**Mitigation path:**
1. Add JSON schema validation for loaded ProceduralMemoryStore files: validate that each rule has required fields (`rule_id`, `conditions`, `actions`, `confidence`, `learned`) and correct types before loading into the match engine
2. Add a `confidence` range check: reject rules with `confidence` outside [0.0, 1.0] to prevent max-confidence injection attacks
3. For v1 scope, a structural schema check (not a cryptographic signature) is sufficient given the local, trusted deployment. Document that cross-run persistence (post-MVP) requires a signing strategy.
4. Log a warning (not a crash) when a rule fails schema validation; skip that rule rather than rejecting the whole file

**Residual risk after mitigation:** LOW  
**Autonomous decision:** ACCEPT_WITH_MITIGATIONS  
**Reasoning:** The deployment is a local developer environment with trusted principals. There is no external attack surface. Schema validation provides meaningful defense-in-depth against accidental corruption and implementation bugs — even if tamper resistance is not strictly required. The mitigation cost is low (stdlib `json` + field validation, ~30 lines).

---

### Q5: Denial of Service — Malformed Production Rules and Match Loop Risk

**Finding: LOW risk — bounded by spec constraints; one gap in chunking path.**

**Analysis of the Match-Select-Apply cycle:**

**Memory risk:** The spec mandates ≤ 50 rules (NFR-SOAR-003: `max_wmes` cap; NFR-SOAR-003 performance target is "≤ 50 rules"). A linear scan of 50 rules against ≤ 50 WMEs is O(rules × WMEs) = O(2500) comparisons per dispatch call. This is bounded and cannot cause excessive memory use under spec constraints. However:
- The spec does not define a `max_rules` cap on the ProceduralMemoryStore. `squad-config.yml` mentions `max_wmes` (int, default 50) but not `max_rules`. If `chunking_enabled: true`, ChunkRecords accumulate without bound. A long run with chunking enabled and a high success rate could accumulate hundreds of rules.
- At 500 rules × 50 WMEs = 25,000 comparisons per dispatch, the 100ms performance budget (NFR-SOAR-003) would likely be exceeded, but this is a performance degradation, not an infinite loop.

**Infinite loop risk:** The match engine performs a single-pass linear scan (no iteration-until-quiescence, explicitly excluded from scope). There is no cycle in the algorithm structure. An infinite loop is not possible from a single malformed rule in the match phase.

**Chunking path gap:** `update_soar_memory` reads `episodic-index-{run_id}.json` (if present) to derive ChunkRecord conditions. The spec does not specify what happens if this file is malformed or extremely large. A multi-megabyte episodic index file would be loaded into memory entirely before any size check. This is a bounded risk (the Episodic Memory overlay writes the file, and is also an internal trusted component), but the spec does not impose a size limit on the episodic index read.

**Condition evaluation risk:** If production rule `conditions` contain complex regex patterns (if regex matching is used — OQ-001 is unresolved), a ReDoS (Regular Expression Denial of Service) attack via a crafted WME value is theoretically possible. However, OQ-001 explicitly lists value regex as one possible condition schema type. If regex is chosen, ReDoS mitigation (timeout, non-backtracking engine, or allowlist-only patterns) must be specified.

**Risk Acceptance Record:**

### RAR-004: Unbounded Rule Accumulation and Potential ReDoS

**Risk:** (a) No `max_rules` cap on ProceduralMemoryStore means chunking can accumulate rules without bound, degrading match performance past the 100ms budget. (b) If OQ-001 resolves to regex-based condition matching, crafted WME values could trigger ReDoS.  
**Probability:** 0.15 for rule accumulation (chunking is disabled by default, limiting exposure); 0.05 for ReDoS (depends on OQ-001 resolution, trusted caller)  
**Impact:** LOW (performance degradation for accumulation; temporary hang for ReDoS — both internal, no data loss)  
**Confidence in mitigation:** 0.90  
**Evidence grade:** B  
**Affected compliance:** NONE

**Mitigation path:**
1. Add `max_rules` to `squad-config.yml` (e.g., default 100) and implement a pruning policy in `update_soar_memory`: when `max_rules` is reached, prune the lowest-confidence ChunkRecords first (seed rules are never pruned)
2. When OQ-001 is resolved: if regex-based conditions are selected, impose a per-pattern timeout using `re` module with a signal-based alarm, or restrict condition patterns to a safe subset (e.g., equality and presence-check only, no arbitrary regex)
3. Add a `max_episodic_index_bytes` config key and enforce a size check before loading the episodic index in `update_soar_memory`

**Residual risk after mitigation:** LOW  
**Autonomous decision:** ACCEPT_WITH_MITIGATIONS  
**Reasoning:** Both risk vectors are low-probability in the current deployment (chunking disabled by default; trusted callers; internal filesystem). The mitigations are configuration additions and a pruning policy — low implementation cost. OQ-001 resolution is a prerequisite for the ReDoS mitigation; ARCHITECT must flag this dependency.

---

## Risk Matrix

| RAR | Threat | Likelihood | Impact | Residual Risk | Decision |
|-----|--------|------------|--------|---------------|----------|
| RAR-001 | Path traversal via unsanitized `run_id` | LOW (trusted callers, internal deployment) | HIGH (could overwrite state.json) | LOW after mitigation | ACCEPT_WITH_MITIGATIONS |
| RAR-002 | soar_state / wme_snapshot data leakage | MEDIUM (agents receive full context_pack) | MEDIUM (architecture state disclosure) | LOW after mitigation | ACCEPT_WITH_MITIGATIONS |
| RAR-003 | ProceduralMemoryStore integrity — no schema validation | VERY LOW (local filesystem, no external access) | MEDIUM (incorrect enrichment) | LOW after mitigation | ACCEPT_WITH_MITIGATIONS |
| RAR-004 | Unbounded rule accumulation / ReDoS | LOW (chunking off by default; trusted input) | LOW (performance degradation) | LOW after mitigation | ACCEPT_WITH_MITIGATIONS |

---

## Prioritized Mitigation Recommendations for ARCHITECT

Listed in priority order (highest security impact first):

### MUST-DO before BUILD phase

1. **[RAR-001 / CRITICAL for implementation]** Add `_validate_run_id(run_id)` to `soar_overlay.py`. Enforce `^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$`. Call it at the entry point of both `enrich_context` and `update_soar_memory`. Add the format constraint to FR-SOAR-002 or as a new NFR. This is a 5-line fix with zero architectural impact.

2. **[RAR-003]** Add schema validation for loaded ProceduralMemoryStore. Validate required fields and `confidence` range [0.0, 1.0] for every rule. Reject individual malformed rules with a logged warning (do not crash on a single bad rule). This prevents implementation bugs in ChunkRecord construction from silently corrupting the match engine state.

### SHOULD-DO before MVP launch

3. **[RAR-002]** Resolve OQ-006 explicitly. Document in spec.md whether `soar_state["impasse"]` and `soar_state["operator_applied"]` are intentionally agent-visible. Add a `wme_snapshot` size cap (≤ 2KB) to ImpasseEvent before writing to the impasse log.

4. **[RAR-004]** Add `max_rules` to `squad-config.yml` with a default of 100. Implement lowest-confidence ChunkRecord pruning in `update_soar_memory` when the cap is reached.

### SHOULD-DO when OQ-001 is resolved

5. **[RAR-004 / ReDoS]** If regex-based condition matching is selected, restrict patterns to an allowlist of safe pattern types or impose a per-pattern match timeout.

---

## Security Impact on Other Agents

| Agent | Impact |
|-------|--------|
| ARCHITECT | Must add `run_id` format constraint to spec (FR-SOAR-002 amendment); must add `max_rules` config key; must resolve OQ-006 explicitly |
| BUILD | Must implement `_validate_run_id` as specified; must implement ProceduralMemoryStore schema validation; must not use string concatenation for ChunkRecord `actions` field |
| SCIENTIST | Should flag if OQ-001 resolves to regex-based conditions — triggers ReDoS mitigation requirement |
| COMMANDER | No changes required; existing exception-handling wrapper already handles `ValueError` from `_validate_run_id` |

---

## Observations for Future Overlay Authors

The impasse log (`soar-impasse-{run_id}.json`) is append-only with no rotation or size limit. Over a long run with frequent impasses, this file could grow to hundreds of kilobytes. A `max_impasse_log_entries` cap or log rotation policy should be added in a post-MVP iteration.

The 200-character WME value truncation (FR-SOAR-003) is a size control, not a security boundary. If future overlays inject structured sensitive data into context_pack keys, the truncation does not prevent that data from reaching the WME layer and potentially the impasse log. A sensitivity-aware WME extraction layer (where certain keys are excluded from `wme_snapshot` writes) would be the appropriate mitigation if the domain evolves toward sensitive data.
