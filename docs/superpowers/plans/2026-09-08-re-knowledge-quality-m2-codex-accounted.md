# RE M2 — Configured provider accounting and Codex safeguards

**Direction corrected September 8:** RE uses the effective LLM provider in
Echelon configuration through the existing `AICodingCliProvider` facade.
Backend-specific transport, screening and usage handling stay behind that
boundary. The retained Codex work is an optional constrained-execution capability,
not a Codex-exclusive RE integration. Task 2 below now reflects this correction.

> **For agentic workers:** Use superpowers:subagent-driven-development and test-driven development. Keep changes uncommitted for the user's review.

**Goal:** Connect discovery and review to the existing configured provider facade under the user-approved reserve-before-call, charge-after-call model, without promising a hard native token cutoff.

**Architecture:** Reuse `AICodingCliProvider`, its existing backend selection, `KnowledgeDispatchAccount`, and both discovery controllers. Add one RE-specific callable adapter and an optional constrained backend capability, not another provider framework, scheduler, ledger, or retry loop. Native invocation uses a fresh empty directory, explicit model, isolated configuration and disabled tool capabilities. Installed routing remains unchanged; tests replace only the external model process.

**Tech Stack:** Python, existing Codex CLI adapter, pytest, local synthetic subprocesses.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, with the user's September 8 approval of reservation accounting instead of a strict per-call token guarantee.

## Global Constraints

- Work in the current checkout and branch. Do not modify `runs/`, source repositories, stashes, installations or existing run authority. Do not commit, push, migrate, or make paid provider calls.
- Retain the existing provider abstraction, neutral Prosaic roles, immutable snapshots, controller-owned state, bounded retries, budgets, and publication transaction.
- User-approved accounting: reserve before each invocation, charge reported usage afterward, conservatively charge missing/untrusted usage, and block further calls after an observed reservation breach. A native invocation can overshoot; never describe these values as enforced native token caps. Do not raise run ceilings.
- Ordinary Codex execution and historical/offline contract identities remain unchanged. New accounted execution must have a distinct frozen contract identity.
- Raw source/output/error content must not enter argv, ordinary logs, or durable controller errors. Use the existing RE scanner and restricted quarantine. No credential copying or authentication changes.
- No new recursive repair loop, second account or new user-facing protocol selector. One backend call owns one fresh native invocation; do not resume producer conversations for review.
- Tests use synthetic sources and local processes only. Native security configuration is defense in depth, not proof from scripted responses that every native version enforces it. Do not claim release readiness or independently certified semantic quality.

### Task 1: Constrained request mode in the existing Codex adapter

**Files:** Modify `src/harness/ai_cli_backends/codex.py`, `codex_capture.py`; use `src/harness/ai_cli_backends/codex_constrained.py` for focused request construction (renamed from the unused uncommitted `codex_knowledge.py`); add `tests/unit/test_codex_knowledge_request.py`. Preserve ordinary request construction.

**Interface:** Add:

```python
CodexCliBackend.run_constrained_prompt(
    request: CliRunRequest, *, model: str,
    screen_output: Callable[[bytes], bytes],
    max_input_bytes: int, max_capture_bytes: int,
) -> CliRunResult
```

This is explicitly opt-in, not a new generic backend protocol method. `request.cwd` must be an empty non-symlink directory; forbid caller-supplied source/tool scopes or unsafe host permission bypass. Bind the explicit nonempty safe model argument, not a tier default. Reject invalid finite limits, malformed input and unsafe input before spawning. Build the actual Echelon prompt including the existing tool-policy preamble; bound and screen that full prompt. This is a byte bound on the rendered prompt, not on Codex's hidden framing or full wire tokens.

- [x] Add failing tests using real local OS pipes for prompt absent from argv, exact screened prompt reaching stdin, wrapper-inclusive input rejection before spawn, fresh empty cwd requirement, pinned model, configuration inheritance refusal/override, tool restrictions, and ordinary execution unchanged.
- [x] Implement request mode by reusing command construction/capture. Deliver the prompt through stdin (`-`) and extend the existing selector collector to write stdin concurrently with draining stdout/stderr under the same deadline. Close stdin on completion and handle early exit, never-reading child, and large input without deadlock or unbounded feeder threads. Keep the existing collector interface backwards compatible with optional input bytes.
- [x] Request native `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--strict-config`, read-only sandbox, and approval mode `never`. Explicitly disable shell/unified-exec, patch, web search, image/browser/computer tools, apps/connectors/MCP/plugin discovery, multi-agent, memory, hooks and automatic skills/project instructions using supported 0.147.0 controls. Use a small explicit documented configuration helper rather than duplicating the generic command builder. Unknown/unsupported native settings must fail closed (no fallback). Keep authentication routing unchanged; remove logging/telemetry overrides from inherited environment and disable content logging/telemetry for this mode. Do not claim this equals an independently tested native isolation boundary.
- [x] Screened successful result must expose coherent aggregate observed usage, not silently take only the final turn's count. Preserve safely parsed numeric usage on a completed but rejected/error invocation where possible; missing/uncertain observations must be marked untrusted or unavailable, never exact zero. Do not persist raw errors or add usage facts not reported by the provider. Pipe timeout/overflow may have unknown usage and must keep full conservative reservation downstream. Existing ordinary streaming parser remains unchanged.
- [x] Run `pytest -q tests/unit/test_codex_knowledge_request.py tests/unit/test_codex_screened_capture.py tests/unit/test_re_v2_knowledge_codex_capture.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_tool_policy.py`. Report RED/GREEN evidence and limitations. Leave changes uncommitted.

### Task 2: Connect discovery/review through the configured provider facade

**Files:** Create `src/harness/re_v2/knowledge_llm.py` and `tests/unit/test_re_v2_knowledge_llm.py`; modify `src/harness/llm_provider.py`, `ai_cli_backend.py`, `knowledge_accounting.py`, `knowledge_dispatch.py` and `knowledge_review_dispatch.py` only where necessary; add focused facade tests if needed. Parent maintains spec/runtime documentation.

**Interfaces:**

```python
class KnowledgeLLMBackend:
    def __init__(self, config: HarnessConfig, *, model: str,
                 screen_output: Callable[[bytes], bytes],
                 max_capture_bytes: int): ...
    @property
    def contract(self) -> KnowledgeProviderContract: ...
    @property
    def contract_id(self) -> str: ...
    def __call__(self, agent: bytes, context: bytes,
                 reservation: DispatchReservationV1) -> ProviderReply: ...
```

Use the existing `AICodingCliProvider`, which selects the effective configured backend including `ECHELON_LLM`; never import or construct a concrete backend from RE. Expose an optional constrained-prompt operation through that facade and a small shared capability contract. The Codex implementation from Task 1 supplies that operation; adapters without it report `constrained-execution-unsupported` before native invocation. Never fall back to ordinary unscreened execution or another provider. Existing non-RE operations for all providers stay unchanged. This increment implements the Codex capability, not unverified native controls for every other backend.

Freeze effective configuration and the backend's constrained-contract identity, explicit provider-appropriate model, capture ceiling, bridge format and accounted resource semantics into the RE contract digest; caller configuration/environment changes must not silently switch an existing backend. Preserve the facade's normal authentication/environment construction. Expose only the minimal public facade facts needed for identity and capability checks; do not reach into facade private fields from RE. Construct a fresh temporary empty invocation cwd for each call; reuse the selected provider instance and RE screening function, not the producer's conversation.

- [x] Add failing production-path tests: real source snapshot/acquisition/account, producer proposal followed by separately invoked reviewer, one shared account, reservations present before native spawn, correct pinned model/agent/context, no producer reasoning in review input. Use existing fixture helpers and replace only the external Codex process with a synthetic subprocess.
- [x] Add a new `configured-provider-accounted` execution mode to `KnowledgeProviderContract` with explicit rendered-prompt input accounting; retain old defaults and old content identities byte-for-byte. Freeze the actual resolved provider, not a hard-coded Codex ID. Reject invalid accounting combinations. Existing immutable reopening rejects switching old offline accounts to this mode.
- [x] Test configuration and environment provider selection: configured Codex reaches its real constrained path; a configured non-Codex adapter is never replaced by Codex; unsupported capability is actionable before process launch; an environment override has the same precedence as normal facade calls. Test mutation after construction cannot switch the frozen contract or provider. A focused test backend may exercise the generic optional contract, but do not claim that certifies another native adapter. Ordinary provider calls remain covered by existing tests.
- [x] Implement the adapter with deterministic UTF-8 prompt framing (`agent` instructions followed by labelled untrusted frozen context), strict byte/limit checks, shared normalized usage, and no local retries. Failure results carry sanitized typed reasons and any reliable observed usage to `_capture_dispatch`; use a defaulted optional field on `ProviderReply` if necessary so old two-argument scripted callers are unchanged. The controller remains the sole durable writer. Full or conservative charge must survive output rejection, provider failure, restart and lost acknowledgement.
  Existing normalization requires complete disjoint usage classes for exact charging. If native Codex omits a breakdown (such as reasoning tokens), retain its observed total as untrusted and conservatively charge the greater of reservation and observed total; never invent the missing class as zero. Preserve the historical normalizer and accounting schema.
- [x] Honor the existing neutral roles' response format: one authorial JSON object followed by the minimal `echelon_result` envelope (`verdict: DONE`, empty `state_updates`). Screen the entire final response before parsing. Reuse the existing strict result parser/validator; use the standard JSON decoder to locate the authorial object, not regex brace extraction. Reject missing/invalid envelopes, nonempty state updates, multiple payloads and trailing unrelated text. Return only the authorial JSON to admission. Tests must emit the actual role envelope, not bypass it with JSON-only synthetic answers.
- [x] Test observed usage above reservation is retained as the larger charge and blocks every subsequent source/review call; missing usage charges full reservation; insufficient shared budget prevents spawning; failure never becomes empty valid output or free retry. Include a multi-turn native transcript so aggregate usage cannot be undercounted. Repeat recovery without another subprocess and verify no ceiling resets.
- [x] Run focused new tests and all `tests/unit/test_re_v2_knowledge*.py` plus Task 1's covering tests. Report RED/GREEN, changed files and remaining native/live validation limits. Leave changes uncommitted.

## Parent documentation and verification

Update the spec with the explicit approved accounting distinction: native in-flight overshoot is possible; prompt bytes are not complete-wire tokens; unknown usage is conservatively charged. Update both runtime discovery contracts to name the configured facade integration, its opt-in status and independent-review execution versus semantic certification boundary. State honestly that other configured backends lacking the constrained capability are refused, not silently replaced. Remove stale claims that live accounting is impossible until a strict native cap exists. Do not mark M2 or release complete.

Review the full increment, resolve load-bearing findings, run the focused covering suite, and report changed behavior plus remaining work. No installation or live calls are part of this increment.
