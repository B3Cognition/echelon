# Assumptions

## Critical Assumptions

### A-001: `claude -p` can be driven non-interactively with plain-text-out, prompt-in semantics
- **Statement:** The claude CLI, invoked as `claude -p` in a subprocess, accepts the assembled prompt (mechanism unspecified in the design: argv vs stdin) and returns the model's answer on stdout in a form from which strict JSON can be extracted.
- **Basis:** Design doc mechanism section (IN-REQ-CF04C07BA415); repo prior art (`src/harness/llm_provider.py` + `ai_cli_backend`) proves subprocess-driven `claude -p` works, but that path uses stream-json output — a different output contract than SUE's plain strict-JSON expectation.
- **Risk if wrong:** JSON extraction becomes unreliable (wrappers, event streams, ANSI noise) and the retry/exit-3 path fires constantly; the acceptance run fails.
- **Validation method:** Spike one real `claude -p` call with the intended flags from a temp cwd and inspect raw stdout; encode the finding in the prompt-assembly and extraction design (feeds U-001).
- **Status:** unvalidated

### A-002: Neutral temp cwd is sufficient to keep repo context out of the model's reading
- **Statement:** Setting the subprocess working directory to a neutral temp directory prevents `claude -p` from loading the repo's CLAUDE.md, and this satisfies the isolation contract.
- **Basis:** Design doc statement (IN-REQ-2F84DF72B209, IN-REQ-DDDD35B79FFA): "`claude -p` loads CLAUDE.md from cwd".
- **Risk if wrong:** Claude CLI also loads user-level configuration (e.g. `~/.claude/CLAUDE.md`, global settings, MCP servers) independent of cwd. The reading would be silently contaminated — no crash, just biased questions/answers, undermining the grounding rule.
- **Validation method:** Run `claude -p` from a temp dir on a machine with a user-level CLAUDE.md containing a detectable marker instruction; check whether the marker influences output. Consider additional CLI flags to suppress user-scope context if available (feeds U-002).
- **Status:** unvalidated

### A-003: Standalone means standalone — no dependency on `src/harness` or echelon config
- **Statement:** `scripts/sue_challenge.py` is self-contained (stdlib-level dependencies), does not import harness modules, does not read `echelon-config.yml`, and is not deployed by the extension.
- **Basis:** Design scope "standalone script" (IN-REQ-8E578B6660BB); non-goals exclude the echelon CLI verb (IN-REQ-D9CE68110258); repo precedent: `scripts/contradiction-scanner.py` is exactly this shape ("Dependencies: stdlib only", argparse, own exit codes). CLAUDE.md documents `scripts/` as host tooling not deployed by the extension.
- **Risk if wrong:** Coupling to harness internals (stream-json, tool policy, config cascade) would contradict the design's stable-interface promise and complicate the pytest stub seam.
- **Validation method:** Code review gate: no `harness.*`/`echelon.*` imports in the script; unit tests run without the installed venv.
- **Status:** unvalidated (design-time; trivially checkable at review)

### A-004: The spec 029 acceptance target retains its known issues
- **Statement:** `specs/029-builder-spec-workbench/spec.md` still contains the REQ-009/AC-010 ordering contradiction, the score-recording loop, and the undefined active-run pointer that the acceptance run must rediscover.
- **Basis:** Verified in the current working tree: REQ-009 at line 61, AC-010 at lines 74/257, active-run pointer references at lines 13–16/218 of `specs/029-builder-spec-workbench/spec.md`.
- **Risk if wrong:** If spec 029 is fixed before the acceptance run, the overlap criterion becomes unsatisfiable and acceptance needs a new target or frozen copy.
- **Validation method:** Re-check spec 029 immediately before the acceptance run; if amended, snapshot the current version as the acceptance fixture.
- **Status:** validated (as of this run's base commit ef2643c9)

### A-005: Both rounds fit within model context limits for realistic specs
- **Statement:** A challenged spec (spec 029 is the acceptance benchmark) plus instructions — and in round 2 additionally up to 15 questions — fits in a single `claude -p` call without truncation.
- **Basis:** Analogy: the harness routinely sends whole specs to `claude -p`; spec 029 is a few hundred lines.
- **Risk if wrong:** Truncated spec text silently weakens the "text testifies" guarantee for large specs; answers cite lines the model never saw.
- **Validation method:** Acceptance run observation; note a size guideline (not a v1 feature) if issues appear.
- **Status:** unvalidated

## Standard Assumptions

- **A-006 — Report co-location is writable:** `<spec-dir>` (directory of the challenged spec) is writable for `socratic-challenge.md` and `.sue-debug/`. Basis: normal developer workflow; the design gives no exit code for a write failure (tracked as U-005). Status: unvalidated.
- **A-007 — Timeout is per subprocess invocation:** the 300s default applies independently to each call, and a retry gets a fresh timeout budget. Basis: "per-call timeout" wording (IN-REQ-F124765D491A, IN-REQ-35B2A2BF9F9D). Status: unvalidated.
- **A-008 — Unit tests follow repo pytest conventions:** `tests/unit/test_sue_challenge.py` collected by the existing pytest config (testpaths `tests`, `unit` marker, pythonpath `.`/`src`), stub executable shipped as a test fixture. Basis: `pyproject.toml` [tool.pytest.ini_options] verified; `tests/unit/conftest.py` fixture pattern. Status: validated (conventions exist).
- **A-009 — "Strict JSON" tolerates extraction:** the model may wrap JSON (e.g. code fences); the script extracts the JSON payload rather than requiring stdout to be byte-pure JSON. Basis: design demands strict JSON output but also specifies an extraction step ("JSON extraction/validation" among unit-tested parts, IN-REQ-BE91B88E2D80). Status: unvalidated.

## Low-Risk Assumptions

- **A-010:** Question ids follow the `Q1`..`Qn` convention shown in the schema; ordering within the report follows round-1 order within each verdict class (design doesn't say otherwise).
- **A-011:** The stdout summary is human-oriented and has no machine-parsing contract in v1 (no JSON mode flag exists in the interface).
- **A-012:** Python 3 available as `python3` on developer machines running the script, matching every other script in `scripts/`.
