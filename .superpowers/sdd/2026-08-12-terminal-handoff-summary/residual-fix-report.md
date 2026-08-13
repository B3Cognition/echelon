# Terminal Handoff Summary — Residual Fix Report

Date: 2026-08-13
Branch: `feat/worked-on-summary-agent`
Starting commit: `0c6e9fb1`

## Outcome

The three user-authorized residual findings are closed. Provider observations
now expire at every unrelated transition, terminal transcript extraction rejects
multiline terminal-payload forgery before line inspection, and exact verifier
failures survive child aggregation and persisted fallback within all existing
handoff bounds.

## Root-Cause Trace and Resolution

### 1. Stale provider state

- Root cause: `StateStore.transition()` merged the previous state wholesale and
  had no atomic removal operation. Coordinator non-provider blocks and
  finalization/convergence therefore retained historical provider fields, while
  the Squad already-done path rewrote an old state unchanged. A later review
  found the same reclassification defect in CLI `harness_error` and
  `docker_unavailable` publication.
- Resolution: transitions accept explicit atomic removals; every non-blocked
  transition clears the three provider-owned keys by invariant, with removals
  applied after updates so conflicting updates cannot resurrect them.
  Coordinator blocks preserve observations only when phase and reason provenance
  still identify the current provider stop. Squad already-done success and both
  V2 and legacy CLI reclassification paths clear the full field set.
- Retention controls cover a true current provider-limit block and the existing
  controller-contract/provider dual-cause path.

### 2. Multiline OSC/DCS transcript forgery

- Root cause: the shared terminal cleaner could consume multiline string
  payloads, but Squad, Ralph, and fulfillment split or searched raw transcript
  text first. Cleaning selected lines was too late. Squad also sanitized stdout
  and stderr separately, permitting a payload opened in one stream and closed in
  the next to expose forged text.
- Resolution: one shared `clean_provider_transcript()` removes complete OSC,
  DCS/SOS/PM/APC, CSI, non-CSI ESC, C0, DEL, and C1 sequences while preserving
  line boundaries. All three extractor families fail closed on ambiguous
  framing, then sanitize and search each independent stream before any split or
  reset-hint extraction. Final messages continue through the existing
  240-character bound.

### 3. Lost verification failures

- Root cause: deferred evidence already deserialized `verification_failures`, but
  multi-target orchestration never aggregated them and delivery's persisted
  fallback read only the verification status, not
  `last_verify_result.failures[*].error`. Packet compaction could also discard
  the final failed-verification detail.
- Resolution: multi-target aggregation preserves stable first-seen failures;
  persisted delivery fallback extracts exact error facts across sorted strategy
  states; all entry and round-trip boundaries clean, deduplicate, and cap the
  collection at 16 entries of at most 240 characters. Failed evidence retains
  at least one failure through 12 KiB compaction so the first failure remains a
  required narrative candidate. Existing 4–8 line, 280-character line, and
  900-character section bounds remain enforced.

## TDD Evidence

- F1 initial RED: coordinator unrelated block, convergence, and Squad
  already-done tests — **3 failed**. New-dispatch invariant — **1 failed**.
  Initial GREEN/control run — **5 passed**.
- F2 RED: shared cleaner/extractor adversarial selection — **7 failed, 3
  passed controls**. GREEN — **10 passed**.
- F3 RED: multi-target aggregation and persisted fallback — **2 failed, 1
  passed round-trip control**. GREEN — **3 passed**; maximal bound tests — **2
  passed**.
- Review-edge RED: CLI V2/legacy reclassification, cross-stream Squad payload,
  failed-evidence packet compaction, coordinator test-double compatibility, and
  authoritative removal precedence — **6 failed** across their first RED runs.
  GREEN rerun — **6 passed**.

## Final Verification

- Post-review affected suite across state, coordinator/re-entry, CLI run/resume,
  provider extractors, Ralph, fulfillment, summary, orchestrator, and full Squad
  integration — **890 passed** in 3m04s.
- Earlier focused closure suite — **1,034 passed** in 3m01s.
- Final broad clean-signal sweep (`tests/unit` plus full Squad integration,
  excluding only the separately reproduced baseline capability-policy file) —
  **6,593 passed** in 9m52s.
- Broad repository sweep (`tests/unit` plus full Squad integration) before the
  final edge fixes — **6,588 passed, 3 failed** in 10m13s. One branch-owned
  coordinator test-double failure was fixed and is included in the 890-pass
  post-review suite. The other two failures are the unchanged baseline described
  below.
- `./scripts/bash/dry-run.sh` — **9/9 checks passed** after the final fixes.
- Python `compileall` — passed.
- `git diff --check` — passed.
- Independent post-fix re-review — no Critical, Important, or Minor findings.

## Residual Fix Round 1/5 — Cross-stream Ordering

The follow-up review showed that concatenating stdout before stderr fixed only
one possible ordering. An unterminated OSC/DCS opener in stderr and forged limit
text plus its terminator in stdout placed the fake text before the opener and
made it searchable. The same flaw affected Squad, Ralph, and fulfillment.

The shared provider boundary now scans every raw stream independently. If any
stream ends inside OSC, DCS, SOS, PM, or APC framing, provider-limit extraction
fails closed for the whole invocation. Otherwise each stream is cleaned and
searched independently, so no fixed concatenation can manufacture framing.

Exact TDD evidence:

- RED:
  `.venv/bin/pytest -q tests/unit/test_provider_limits.py
  tests/unit/test_squad_provider.py tests/unit/test_ralph_outer.py
  tests/unit/test_fulfillment_runner.py -k
  'provider_stream_cleaner_rejects_cross_stream_string_payload or
  rejects_cross_stream_terminal_payload_in_either_order or
  extracts_limit_from_either_clean_stream'` — **10 failed, 12 passed, 247
  deselected**. The failures were the absent shared boundary and the reversed
  OSC/BEL and DCS/ST order in all three extractor families.
- Secondary RED:
  `.venv/bin/pytest -q
  tests/unit/test_provider_limits.py::test_provider_stream_cleaner_preserves_safe_trailing_non_string_escape`
  — **1 failed**. This caught a scanner edge where Python's empty-string
  membership semantics misclassified a lone trailing ESC as a string opener.
- GREEN:
  `.venv/bin/pytest -q tests/unit/test_provider_limits.py
  tests/unit/test_squad_provider.py tests/unit/test_ralph_outer.py
  tests/unit/test_fulfillment_runner.py -k 'cross_stream or
  safe_trailing_non_string_escape or preserves_safe_ordinary_reset_message or
  extracts_limit_from_clean_stderr'` — **23 passed, 247 deselected**.

Round verification:

- Complete provider-limit extractor files — **271 passed** in 27.84s.
- Exact prior residual regression suite — **26 passed** in 1.25s.
- `./scripts/bash/dry-run.sh` — **9/9 checks passed**.
- Python `compileall` and `git diff --check` — passed.
- Independent read-only review found no code issue; its two documentation
  mismatches were corrected before commit.

## Remaining Concerns

- Two tests in `tests/unit/test_extension_capability_policy.py` fail unchanged on
  starting commit `0c6e9fb1`: the generated Prosaic model tiers differ from the
  older capability-policy assertions. A fresh isolated run remains **2 failed,
  1 passed**. No files in that capability-policy surface were changed here.
- No unresolved concern remains in the three authorized residual scopes.
