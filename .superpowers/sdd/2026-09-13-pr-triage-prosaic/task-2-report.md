# Task 2 report: isolated no-tools triage turns

## Outcome

Implemented the optional, runtime-checkable `ReviewTriageBackend` operation and
the exact `AICodingCliProvider.run_review_triage_turn(...)` facade. Only the
Claude and Codex adapters implement the operation. Unsupported backends fail
with exit 125 and never fall back to `run_prompt` or `run_agent`.

The facade passes the supplied neutral frontmatter under `prompt_metadata`,
caps the caller deadline by the configured provider timeout, and exposes no
tool-scope or execution-profile argument. Both adapters require the caller's
private invocation directory to be empty and non-symlinked.

Codex delegates to its existing constrained request preparation and bounded
pipe capture with fixed 1 MiB input and 256 KiB combined capture caps. The only
change to constrained preparation is an opt-in `model_reasoning_effort` config
override when neutral `effort` metadata is present; requests without that
metadata retain their prior command shape and defaults.

Claude uses a triage-only builder and the existing deadline-aware bounded pipe
capture. It sends the full prompt through stdin, forces the configured unsafe
policy off, and emits the locally verified native controls: `--safe-mode`, an
empty `--setting-sources`, strict explicit empty MCP configuration, empty
`--tools`, `dontAsk`, disabled slash commands, no session persistence, and no
Chrome integration. It maps neutral model tier and effort in the adapter and
runs under `sandbox-exec`; unavailable macOS isolation fails before launch.
There is no generic constrained-capability marker on Claude.

Both adapters normalize only the successful final answer, reject malformed or
missing final records and tool-execution events, bound capture, enforce one
deadline, and retain observed usage on failed turns when the stream reports it.

## TDD evidence

### Initial RED

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_review_triage_provider.py
```

Observed expected collection failure before the interface existed:

```text
ImportError: cannot import name 'ReviewTriageBackend' from 'harness.ai_cli_backend'
1 error in 0.22s
```

### Behavioral RED after minimal importable interface

The same focused command then exercised importable stubs and produced the
expected behavior failures:

```text
3 failed, 3 passed in 0.24s
```

The failures named absent isolation reporting, missing Codex constrained
delegation, and missing Claude isolated execution controls.

Additional RED cycles caught concrete behavior gaps:

```text
4 failed, 40 passed in 0.83s
```

Those failures caught non-object Claude JSON raising instead of failing closed
and exposed a test-process patching issue, which was corrected in the test
utility before implementation claims.

```text
3 failed, 44 deselected in 0.28s
```

Those failures caught missing Codex final-answer normalization, an unrecognized
Claude server-tool event variant, and lost usage reported before a failed Claude
final record.

### GREEN and affected regression suite

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_review_triage_provider.py tests/unit/test_codex_knowledge_request.py tests/unit/test_codex_screened_capture.py tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py tests/unit/test_claude_delivery_scope.py
```

Output:

```text
403 passed in 4.71s
```

Compilation and whitespace checks also completed successfully:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m compileall -q src/harness/ai_cli_backend.py src/harness/llm_provider.py src/harness/ai_cli_backends/claude.py src/harness/ai_cli_backends/codex.py src/harness/ai_cli_backends/codex_constrained.py src/harness/ai_cli_backends/claude_triage.py tests/unit/test_review_triage_provider.py
git diff --check
```

Both commands exited 0 with no output.

## Native-control verification

No model was invoked. Local help/source inspection used Claude Code 2.1.236 and
Codex CLI 0.154.0. Claude help confirms stdin print mode and all emitted flags,
including `--safe-mode` retaining auth while disabling customizations and
`--effort` accepting low/medium/high. Codex help confirms stdin input,
`--strict-config`, ephemeral execution, ignored user configuration/rules,
read-only sandboxing, never-approval behavior, and JSONL output. The installed
Codex binary's local schema contains `model_reasoning_effort`.

Local `getconf ARG_MAX` was measured as 1,048,576 bytes, equal to the triage
input cap before environment and other argument overhead. The Claude prompt is
therefore deliberately piped through stdin rather than placed in argv.

## Files

- `src/harness/ai_cli_backend.py`
- `src/harness/llm_provider.py`
- `src/harness/ai_cli_backends/claude.py`
- `src/harness/ai_cli_backends/claude_triage.py`
- `src/harness/ai_cli_backends/codex.py`
- `src/harness/ai_cli_backends/codex_constrained.py`
- `tests/unit/test_review_triage_provider.py`
- `.superpowers/sdd/2026-09-13-pr-triage-prosaic/task-2-report.md`

## Self-review

- Confirmed the facade has no provider branch and only detects the optional
  protocol structurally.
- Confirmed Claude does not advertise the generic constrained-prompt contract.
- Confirmed neither adapter calls a generic provider execution path on error.
- Confirmed caller metadata cannot inject an execution profile, provider model,
  reasoning override, or tool/source scope.
- Confirmed user unsafe policy cannot add either provider's bypass flag.
- Confirmed all prompt bytes are bounded after policy-preamble injection and
  are supplied through stdin.
- Confirmed stdout and stderr share the fixed capture cap and deadline.
- Confirmed success requires exactly one valid final record and tool events
  fail the turn even if a later final answer is present.
- Mutation review covered wrong mappings/flags, missing isolation gates, generic
  fallback, removed caps, accepted tool events, unnormalized final text, and
  dropped failed-turn usage; focused tests fail for each mutation.
- Existing generic provider defaults and controller wiring are unchanged.

## Concerns and limitations

Per task constraints, verification used only scripted stand-ins and local CLI
help/schema inspection. It did not invoke a real model, install or migrate a
workspace, or push/merge. Live authenticated-provider behavior remains an
explicit later validation boundary rather than evidence claimed by this task.

## Fix round 1: sandbox containment and failed-turn accounting

### Review findings addressed

The first implementation's sandbox rule inverted its intended boundary: it
allowed filesystem reads and writes everywhere except the private invocation
directory. A direct `sandbox-exec` probe reproduced the issue by reading
`/etc/passwd` successfully.

The Claude triage profile now places an explicit deny over every filesystem
read outside a triage-local runtime/auth whitelist. The whitelist contains:

- the lexical and resolved configured Claude executable;
- the private, initially empty invocation directory;
- exact device, resolver, and credential-file paths required by startup;
- immutable macOS library, ICU, framework, dyld-cache, and certificate trees.

Filesystem writes are denied everywhere except the private invocation
directory. `TMPDIR`, `XDG_CACHE_HOME`, and `XDG_CONFIG_HOME` are redirected
there. The optional plaintext Claude credential file is read-only and exact;
symlink components are rejected before launch. Normal macOS keychain auth is
retained through the Security framework and normal non-filesystem runtime
operations. Product, staging, general home, and general temporary trees are
not granted.

The Codex screened parser now records usage carried directly by a
`turn.failed` event before marking the observation untrusted. A failed event
that carries no usage does not create a spurious incomplete observation or
erase complete details retained from an earlier turn.

### Focused RED

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_review_triage_provider.py -k 'real_sandbox_allows_only or lone_failed_turn'
```

Observed before the fixes:

```text
2 failed, 47 deselected in 0.26s
```

The real sandbox probe returned `1111` rather than the required `1000`: the
synthetic credential, product source, `/etc/passwd`, and product write were all
accessible. The lone Codex `turn.failed` record returned no usage rather than
the reported 12 tokens.

A broader pre-final run then exposed a compatibility edge case in the first
accounting patch:

```text
FAILED test_screened_capture_preserves_safe_usage_when_later_provider_event_fails
1 failed, 197 passed in 3.31s
```

That failure showed that a later failed event without a `usage` member must
not degrade complete usage details from an earlier completed event.

### Focused GREEN

After the sandbox and accounting changes, the original two focused tests
passed:

```text
2 passed, 47 deselected in 0.24s
```

After tightening the failed-event condition, the new regressions plus the
existing compatibility case passed together:

```text
3 passed in 0.25s
```

### Runtime and containment evidence

No model was invoked. The installed executable resolves from
`/opt/homebrew/bin/claude` to
`/opt/homebrew/Caskroom/claude-code/2.1.236/claude`. Local Mach-O dependency and
binary-string inspection identified its macOS runtime, Security/keychain,
certificate, and optional `.credentials.json` dependencies.

Four bounded profile families were tried, followed by path bisection using
only local `--version` and `--help` startup probes. With the final filesystem
whitelist, both commands exited 0. The exact missing reads found through those
diagnostics were literal `/` metadata/traversal (`--version` otherwise aborted
with signal 6) and `/usr/share/icu` (`--help` otherwise failed).

The committed real-sandbox regression executes `/bin/sh` under the generated
profile and observes `1000`: the exact synthetic auth credential is readable,
while a sibling product source, `/etc/passwd`, and a sibling product write are
all denied. The attempted output file is not created.

### Final affected regression suite

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_review_triage_provider.py tests/unit/test_codex_screened_capture.py tests/unit/test_codex_knowledge_request.py tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py tests/unit/test_claude_delivery_scope.py
```

Output:

```text
405 passed in 4.76s
```

### Fix-round self-review

- Confirmed filesystem denial is behavioral, not only a string assertion.
- Confirmed arbitrary product/staging and unrelated host reads and writes are
  outside the profile while the private invocation directory remains usable.
- Confirmed no broad home or temporary subtree and no existing operational
  helper exception was reused as an auth grant.
- Confirmed Claude prompts still travel by stdin and all no-tools/output
  validation remains in the adapter.
- Confirmed successful Codex accounting and the existing failed-event-without-
  usage behavior remain unchanged.
- Confirmed the sandbox change is triage-local and adds no runtime framework,
  provider configuration, controller wiring, or fallback.
