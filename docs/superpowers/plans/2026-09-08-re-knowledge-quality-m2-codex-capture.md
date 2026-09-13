# M2 Codex screened capture implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Follow test-driven development.

**Goal:** Close the Echelon-side pre-log disclosure gap in the existing Codex adapter with an explicit bounded, screened response path, without enabling production RE dispatch.

**Architecture:** Reuse the existing Codex command construction and `CliRunRequest`/`CliRunResult`. Add an opt-in adapter method which collects bounded stdout/stderr in memory, screens before returning content, never streams diagnostics, and does not request a last-message file. Existing ordinary execution remains unchanged. This is a provider integration prerequisite, not certification of native Codex tool isolation, native storage, full wire token accounting or semantic independence.

**Tech Stack:** Python, existing Codex CLI adapter, pytest, synthetic local subprocesses (no model/network).

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, sections 5, 7, 10 and M2.

## Global Constraints

- Retain the existing provider abstraction, neutral Prosaic roles, immutable snapshots, controller-owned state, bounded retries, budgets, and publication transaction.
- Screen provider output before retaining ordinary logs or promoting artifacts; quarantine unsafe results locally with restricted access and a sanitized error. Never print matched values.
- No live workspace reads, arbitrary shell access, network fetching, or undeclared-repository traversal are introduced.
- Do not build a second scheduler, generic agent framework or new parser platform.
- Work in this existing feature checkout as requested. Do not install, invoke real providers, change defaults/provider selection, raise budgets, touch source workspaces/stashes or stage `runs/`.
- Leave the new increment uncommitted for handoff. The preceding increment is committed as `a0cdd0e5`.

### Task 1: Bounded screened Codex response path

**Files:** Modify `src/harness/ai_cli_backends/codex.py`; create a focused private helper `src/harness/ai_cli_backends/codex_capture.py` if needed for bounded pipe capture, and `tests/unit/test_codex_screened_capture.py`. Do not modify RE accounting contracts or other adapters.

**Interfaces:**
```python
CodexCliBackend.run_prompt_screened(
    request: CliRunRequest,
    *, screen_output: Callable[[bytes], bytes],
    max_capture_bytes: int,
) -> CliRunResult
```

`screen_output` is a trusted harness policy callback, not provider metadata. It returns identical bytes on success and raises on rejection; using the existing RE `screen_provider_output` with a protected quarantine provides retention. Callbacks which rewrite or return another type fail closed. The callback must not log; its exception text is never returned. This method is explicitly Codex-only and not added as a capability other backends can silently ignore.

- [x] RED: write tests calling the real adapter with a synthetic subprocess transport. Start with a literal modern `item.completed` / `agent_message` containing `{"ok":true}` and `turn.completed` usage. Assert exact final stdout, numeric usage, silent captured console, and no `--output-last-message` or Echelon last-message temporary file. Exercise ordinary adapter tests unchanged. Use missing-method RED initially, then each new behavior RED before implementing it.
```python
result = backend.run_prompt_screened(request, screen_output=screen, max_capture_bytes=4096)
assert result.stdout == '{"ok":true}'
assert result.exit_code == 0
assert capsys.readouterr().out == ""
```
- [x] GREEN: reuse current command construction/security checks; select a separate bounded capture path before the ordinary streaming loop and final-message-file creation. Do not duplicate the command/scope policy builder. Do not redirect global stdout or monkeypatch printing. Keep the existing ordinary `run_prompt`/`run_agent` behavior unchanged.
- [x] RED/GREEN: validate positive finite request timeout, a positive non-boolean integer byte cap and callable screen before spawning. Bound aggregate raw stdout plus stderr, including an unterminated giant line. Read fixed-size chunks; on overflow kill/reap the owned subprocess, discard output and return a fixed safe failure. Drain both pipes to avoid deadlock. Deadline must cover pipe reads and process termination, not merely the initial call. Test with real local Python subprocesses for simultaneous stderr/stdout, no-newline overflow and timeout; no real Codex invocation. Do not leave running children or blocked reader threads on failure.
- [x] RED/GREEN: screen complete raw streams and individual JSON event records before any content escapes; screen extracted final content too, so JSON escaping or reassembly cannot hide a canary. Whole-stream screening catches secrets split across read chunks. Unknown diagnostic event fields cannot bypass screening. Validate UTF-8 and event object structure; malformed/uninspectable capture fails closed. Screen stderr but never expose it through successful or failed results. Quarantine behavior belongs to the supplied existing policy callback, not a new store.
- [x] RED/GREEN: use recognized final assistant events (`item.completed` agent_message and supported legacy task_complete last_agent_message) with successful completion; commentary/diagnostic text is not the final answer. A missing final answer, malformed event, nonzero process exit, timeout, byte overflow, process-start/read failure, tool-execution event or scanner rejection returns empty stdout, safe fixed stderr/reason metadata, and no raw exception text. Never turn a partially captured success into success. Keep only allowlisted numeric usage/request metadata; no provider-supplied diagnostic metadata. Test modern and legacy final forms, escaped canaries in final/diagnostic/error fields, later unsafe bytes after an apparently complete response, callback rejection/rewriting, and malicious source text attempting to grant tools. Rejecting observed tool events is not proof tools could not execute: live RE stays disabled.
- [x] Run `pytest -q tests/unit/test_codex_screened_capture.py tests/unit/test_ai_cli_backend.py` and covering tool-policy tests. Self-review and report RED/GREEN evidence, actual output and any limitations. Do not commit or spawn agents.

### Task 2: Document boundary and verify integration gates

**Files:** Update the implementation status in the spec, this plan, and the discovery/review runtime contracts only where they name provider safety prerequisites. Add `tests/unit/test_re_v2_knowledge_codex_capture.py` for the existing RE scanner/quarantine integration. Parent owns these files.

- [x] Document the opt-in screened method and its scope: Echelon-side stdout/stderr/last-message handling only. Native Codex logs/storage, tools-free isolation, complete-wire token bounds and independent production invocation remain unproven gates; do not claim production safety or wire into the offline account.
- [x] RED/GREEN: exercise the actual adapter and existing `screen_provider_output` with a synthetic local subprocess, replacing only process launch command. Safe final JSON returns unchanged without quarantine; canaries in final output, escaped diagnostic fields and stderr produce an empty safe result, no console disclosure and owner-only existing quarantine objects. No raw output reaches ordinary artifacts.
- [x] Independent task review of code/tests and document accuracy; fix actionable defects with regression tests and scoped review.
- [x] Run focused adapter tests plus existing RE knowledge account/discovery/review compatibility and `git diff --check`. No paid calls, installation or external mutations.

## Preflight

Task 1 produces the explicit adapter method; task 2 documents that exact opt-in capability and its remaining gates. Shared interface only, no overlapping code ownership. Each task is independently checkable. This step intentionally leaves `KnowledgeProviderContract.execution_mode` restricted to `offline-scripted`; collecting responses safely does not prove tools-free or billable-token-limited native execution.

## Progress

Preceding shared-account review dispatch committed as `a0cdd0e5`; fresh pre-commit verification passed 28 tests. Both tasks are complete. Independent review approved the bounded increment after resolving all findings with regressions. New changes remain uncommitted; no live execution, installation, provider/default changes or source/stash operations occurred.

Final covering verification: `pytest -q tests/unit/test_codex_screened_capture.py tests/unit/test_re_v2_knowledge_codex_capture.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_tool_policy.py` — **203 passed in 3.41s**, after the last missing-item correction. `git diff --check` passed.

The broader provider/RE/workflow selection passed **759 tests in 206.02s** before that final two-line missing-item guard correction and its two added regressions; the 203-case covering rerun above verifies the final amended code. Earlier broad checkpoints: 746 passed in 206.55s and 757 passed in 209.90s. The broader selection adds existing provider-caller/CLI tool-policy/protocol-22-provider tests, knowledge dispatch/acquisition/discovery/review/handoff/evidence tests, and workflow/prompt wiring tests to the final covering selection.

Review regressions cover duplicate keys, malformed Unicode/nonfinite numbers and discriminators, legacy envelopes/tools/errors, completion ordering and EOF cleanup reserve. The blocking file-like test fallback was removed; read-error and missing-item tests exercise real subprocess pipes. All findings are resolved; approval covers only the Echelon-side capture prerequisite.

Remaining gates are unchanged: native Codex storage/tool isolation and complete-wire token enforcement; independent production invocation certification; bounded producer revisions, semantic target/source reconciliation, analysis invalidation/debt; M3 unified publication/refresh/consumer path; M4 separately authorized live evaluation. This increment does not enable live RE or declare the repair released.
