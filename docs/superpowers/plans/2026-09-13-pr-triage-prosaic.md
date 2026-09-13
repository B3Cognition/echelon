# PR-triage Prosaic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish active PR triage's Prosaic migration for Claude and Codex without relaxing diagnostic permissions.

**Architecture:** ReviewLoopController owns grouping and role sequencing. A triage-local descriptor-pinned read channel supplies requested evidence to no-tools provider turns; the existing publisher retains canonical authority and recovery.

**Tech Stack:** Python, pytest, Prosaic, existing Claude/Codex adapters.

**Spec:** docs/superpowers/specs/2026-09-13-pr-triage-prosaic-design.md (user approved).

## Global Constraints

- ReviewArtifactPublisher remains the only canonical artifact publisher.
- Unsupported providers or unavailable required isolation fail before model launch; never fall back to general run_prompt/run_agent execution.
- Do not advertise Claude as implementing the generic constrained RE capability.
- No model shell, browser, web search, or arbitrary network tool is available.
- Provider-specific controls stay in adapters, never neutral prose.
- At most 32 read requests per role; 1 MiB input and 256 KiB captured output per turn; one existing review timeout across the attempt.
- No legacy build, fulfillment, repair-feedback, identity, developer guidance, installation, migration, live model run, push, merge, or rollout changes.
- Work only in the delivery-controller-contract worktree. Use `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest` for tests. Commit only task-owned files. No subagents from workers.

## Task 1: Pinned read channel and captured Prosaic loading

**Files:** Create `src/harness/review_triage_io.py`, `tests/unit/test_review_triage_io.py`; optionally modify `src/harness/prosaic_prompt_loader.py` to accept a subprocess timeout without changing its default behavior.

**Interfaces:**
```python
class ReviewTriageError(ValueError): pass
class ReviewReadChannel:
    def __init__(self, worktree: Path, spec_dir: Path): ...
    def __enter__(self) -> ReviewReadChannel: ...
    def __exit__(self, *args) -> None: ...
    def request(self, value: object) -> dict[str, object]: ...
def load_review_prose(worktree: Path, *, timeout_s: float) -> dict[str, ProsaicCommandArtifact]: ...
```
`request` takes exact schemas `{"op":"read_file","root":"worktree"|"spec","path":str,"start_line":int,"line_count":int}` and `{"op":"list_directory","root":...,"path":str}`. A directory root itself is represented only by `path="."`. Invalid or denied requests raise ReviewTriageError; unavailable text/oversize returns `{"status":"unavailable","reason":str}`. Successful reads return status=ok, text, start_line, total_lines; directory listing returns status=ok and entries [{name,type}]. Caller owns the per-role request budget. Expose no extra read roots or write operations.

`load_review_prose` returns keys echelon.review, echelon.review-debugger, echelon.review-sentinel, echelon.review-spec-guard. Capture corresponding command/subagent source bytes, max 128 KiB each, descriptor-relative O_NOFOLLOW. Use a private temporary `.echelon/prosaic` bundle and ProsaicPromptLoader on that captured bundle. Reject companions before normal loader expansion, then validate returned bodies nonempty and neutral model metadata. Bound all four inspections by one monotonic deadline based on timeout_s (an optional timeout on the shared loader is permitted; its existing default behavior stays unchanged). Keep the fixed names local to this module. This task does not change the active controller yet.

- [ ] Write failing tests using real files and literal expected data, starting with:
```python
def test_read_returns_requested_lines_from_supplied_root(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    with ReviewReadChannel(tmp_path, tmp_path) as channel:
        result = channel.request({"op":"read_file", "root":"worktree",
            "path":"a.py", "start_line":2, "line_count":1})
    assert result["text"] == "two\n"
```
Add traversal, unknown fields, integer booleans, symlink components/files, root replacement, hard links, FIFO, binary, per-file/output bounds, sorted bounded listing, missing/empty/unsafe prose, companion rejection and captured-input inspection tests. Mock only Prosaic's subprocess for fast parser-boundary tests; include a real local Prosaic smoke if available, with no model invocation.
- [ ] Run focused tests; record meaningful RED evidence before production changes.
- [ ] Implement descriptor chain open/close with exception cleanup; bounded nonblocking regular-file reads and metadata rechecks; sorted limited directory iteration; capture/inspect the fixed prose set. No recursive worktree scans or generic snapshot system.
- [ ] Run the new test file plus existing Prosaic loader tests, self-review diff, commit `feat: add bounded PR triage read and prose boundary`.

## Task 2: No-tools triage turns for both providers

**Files:** Modify `src/harness/ai_cli_backend.py`, `src/harness/llm_provider.py`, `src/harness/ai_cli_backends/claude.py`, `src/harness/ai_cli_backends/codex.py`; create `src/harness/ai_cli_backends/claude_triage.py`, `tests/unit/test_review_triage_provider.py`. Change existing constrained Codex helper only as required to carry neutral effort without changing existing defaults.

**Interfaces:** Add optional runtime-checkable ReviewTriageBackend with `run_review_triage_turn(request: CliRunRequest) -> CliRunResult`. Add facade `run_review_triage_turn(worktree_path: str, prompt: str, *, frontmatter: Mapping[str, object], timeout_ms: int) -> CliRunResult`. `worktree_path` here is the caller-created private empty invocation directory, not the product worktree. Adapter receives neutral metadata under prompt_metadata and fixed 1 MiB/256 KiB caps. No caller-supplied tool scope or execution-profile override. Return existing CliRunResult with normalized final text and usage/failure metadata.

- [ ] Write a facade test showing unsupported backend and absent macOS isolation return exit 125 before subprocess, even under unsafe user policy. Write adapter tests that inspect emitted execution controls and run real small scripted subprocesses as stand-ins for the external CLIs.
```python
result = provider.run_review_triage_turn(str(empty_dir), "triage input",
    frontmatter={"model_tier":"strong", "effort":"medium"}, timeout_ms=1000)
assert result.exit_code == 125  # unsupported configured provider fixture
```
Cover neutral model/effort mapping, no ambient native agents/tools/project instructions, no fallback, tool-event rejection, malformed output, timeout, bounded input/output, and failed-turn usage.
- [ ] Run focused RED tests before code.
- [ ] Add the optional protocol/facade branch without changing generic constrained capability detection. Codex delegates to its constrained request preparation/capture with the fixed caps and strict no-tools controls. Claude uses a triage-only builder and bounded pipe capture; native tools inventory empty, no unsafe bypass, bare/isolated settings, strict empty MCP, no agents or hooks/plugins. Verify native controls from local CLI help/source; do not invent supported flags. Reject unexpected tool events and missing/error final records. Do not invoke a real model.
- [ ] Run provider-focused tests plus affected existing backend/provider tests once, self-review, commit `feat: support isolated Claude and Codex triage turns`.

## Task 3: Harness-owned triage sequence and staging

**Files:** Modify `src/harness/review_loop.py`, `prosaic/commands/echelon.review.md`, `tests/unit/test_review_loop.py`; create three `prosaic/subagents/echelon.review-{debugger,sentinel,spec-guard}.md`, `src/harness/review_triage.py`, `tests/unit/test_review_triage.py`. Modify `src/harness/review_artifacts.py` only for a scoped staging helper if needed. Update the convergence boundary and audit after verification.

**Interfaces:** review_triage.py holds deterministic grouping, strict JSON reply parsing, and bounded role-turn execution helpers; ReviewLoopController still owns calling those helpers in debugger/sentinel/spec-guard order and calling the publisher. Consume Task 1's channel/prose and Task 2's facade without provider-name branches. One monotonic deadline spans loading, groups, reads and composition.

Use strict JSON envelopes: diagnostics return either `{"action":"read","request":{...}}`, `{"action":"result","analysis":nonempty_string}`, or `{"action":"blocked","reason":nonempty_string}`. Composer returns `{"manifest":existing_manifest,"artifacts":{allocated_name:text},"tasks_append":text}`; nonempty supplied comments require one artifact per successfully diagnosed group, no partial/empty-success escape. Python gives exact schemas in the bounded invocation. Enforce exact keys, duplicate-key rejection, finite values, byte/turn bounds, and accumulate actual usage or explicitly marked estimates for every failed/successful call. Source/read output is JSON-framed untrusted data.

- [ ] Write consuming tests: real temporary worktree/spec/bundle, external process scripted, existing publisher real. Initially clean Prosaic-only invocation fails under the old loader. Test deterministic transitive grouping with literal IDs, role order/evidence propagation, malformed/read/blocked/timeout/overflow failures leaving canonical files/seen IDs unchanged, one total deadline, usage across failed turns, and rejected model-selected stage paths.
```python
# Same file, transitive proximity: literals do not use the grouping helper.
assert [[c.comment_id for c in g] for g in group_review_comments(comments, 3)] == [["a", "b", "c"], ["d"]]
```
- [ ] Run RED evidence. Replace active legacy native-agent loader/call with captured Prosaic and sequential bounded turns; remove only now-unused legacy helpers from review_loop.py. Keep legacy provider profile rejection behavior for callers still explicitly requesting it. Create self-contained neutral prose with one semantic responsibility each and no workflow conditionals.
- [ ] Validate the entire composer envelope before staging. Write only allocated names through pinned, no-follow/exclusive staging opens; reject pre-existing entries; status manifest last. Preserve publisher acceptance and journal recovery, no second canonical writer or per-role journal. Empty comments need no model.
- [ ] Update old invocation tests to new contract without dropping publisher/recovery tests. Run all new tests and existing review-loop, review-artifact, Prosaic, facade and backend suites together once; independent review then scoped fixes. Record exact evidence, no live-validation claim. Commit `fix: route PR triage through harness-owned Prosaic roles`.
