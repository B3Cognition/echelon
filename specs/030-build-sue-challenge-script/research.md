# Architecture Research — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script (runs/spec-20260718-104053-744160/specs/030-build-sue-challenge-script/spec.md)
- Architect: speckit-echelon-architect (ARCHITECT)
- Date: 2026-07-18
- Inputs reviewed: spec.md, feasibility.md, prioritization.md, mvp-scope.md, estimates.md, glossary.md, mental-model.md, mental-model-code.md, boundaries.md, assumptions.md, unknowns.md, issues.md, risks.md, strategic-overview.md, user-intent.md, constitution (.specify/memory/constitution.md v1.0.0), reasoning-journal.jsonl, repo prior art (`scripts/contradiction-scanner.py`, `tests/unit/conftest.py`, `pyproject.toml`), live evidence from the installed claude CLI (see OQ evidence below)

## OQ-001 / OQ-002 Evidence (spike executed at HOW, 2026-07-18)

The pre-HOW INVESTIGATOR spikes recommended by WHY1/GATEKEEPER/STRATEGIST had not run when
this phase started (phase3-specialists produced no artifacts). Because both open questions
gate the two highest-blast-radius contracts (FR-026 extraction, FR-010 subprocess runner),
ARCHITECT executed the minimal spike before freezing either contract. This is a traceable
resolution per TRACKER RF-3, not a silent one.

**Environment pinned:** claude CLI version **2.1.214 (Claude Code)**, macOS (darwin 25.5.0),
2026-07-18.

**OQ-001 — invocation and raw output shape (Grade A, direct observation):**

- Call: `printf '<prompt>' | claude -p` executed with `cwd` set to a fresh `mktemp -d`
  directory outside any repository. Prompt requested a small exact JSON object.
- Result: exit code 0, wall clock ≈ 6.4 s, stdout was **byte-clean JSON plus one trailing
  newline** (21 bytes: `{"ok": true, "n": 3}\n`). No code fences, no progress noise, no ANSI
  codes on stdout in this observation. Debug/diagnostic traffic goes to stderr / debug file,
  not stdout.
- `claude --help` (2.1.214) confirms: `-p/--print` is the non-interactive mode; default
  `--output-format` is `text` (choices: text, json, stream-json); prompt is accepted as a
  positional argument or on stdin.
- Caveat: N=1 observation with a trivial prompt. Larger structured outputs may still arrive
  fence-wrapped or preceded by prose. The spec's tolerant-extraction contract (FR-026)
  therefore remains the correct defensive design; the spike confirms it is not *required*
  on the happy path, so the single-retry budget is not systematically consumed (defuses the
  MODELER V-2 / WHY1 ISS-002 "exit-3 loop on every run" scenario).

**OQ-002 — isolation completeness (Grade A, direct observation):**

- The same call was run with `--debug-file`. The debug log proves that from a neutral temp
  cwd the CLI still loaded: **user-scope settings** (`userSettings` permission rules),
  **user-scope plugins and skills** (a plugin skill was injected verbatim into the API
  request as `additionalContext`), and **user/account-scope MCP servers** (remote MCP fetch
  plus locally configured servers). Repo-scope context (`CLAUDE.md`, project settings) was
  NOT loaded — the temp cwd guarantee of FR-010 holds exactly as specified.
- Conclusion: the residual-exposure limitation in spec.md (Limitations → "Residual context
  exposure") is **confirmed real, not hypothetical**. Operator-level ambient context loads
  independently of cwd and can reach the model's reading.
- Suppression options exist in CLI 2.1.214: `--safe-mode` ("all customizations — CLAUDE.md,
  skills, plugins, hooks, MCP servers … disabled; auth, model selection work normally") and
  `--setting-sources <user,project,local>`. `--bare` also exists but restricts auth to
  `ANTHROPIC_API_KEY` only, making it unusable for OAuth-authenticated operators.
- v1 decision: see ADR-004 — the designed mechanism (temp cwd only) is kept; the limitation
  wording in spec.md stands with this evidence attached; `--safe-mode` is recorded as the
  validated candidate for a future amendment, not silently added to v1.

## ADR Index

| ADR | Decision | Status | Evidence Grade | Requirements / Constraints | Deferral |
|-----|----------|--------|----------------|----------------------------|----------|
| ADR-001 | Python 3 stdlib-only single-file script | Accepted | A | NFR-002, FR-045, A-008, A-012 | none |
| ADR-002 | Pure-function core + thin CLI shell; single shared schema constants | Accepted | B | FR-044, NFR-004, ISS-206 | none |
| ADR-003 | Model invocation: `shlex.split(cmd) + ["-p"]`, prompt on stdin, default text output | Accepted | A | FR-003, FR-007, FR-008, FR-012, FR-043, OQ-001 | none |
| ADR-004 | Isolation: fresh `mkdtemp` cwd per call, outside repo; no suppression flags in v1 | Accepted | A | FR-010, AC-012, OQ-002, A-002 | none |
| ADR-005 | Tolerant JSON extraction + strict hand-rolled validation + ID bijection | Accepted | A | FR-016, FR-024–FR-027, A-009 | none |
| ADR-006 | Failure-handling state machine: exit codes 0/1/2/3, timeout→parse-failure, 1 retry/round | Accepted | A | FR-005, FR-006, FR-011–FR-013, FR-028–FR-031, ERR-001–ERR-005, NFR-001, NFR-005 | none |
| ADR-007 | Report rendering: GFM + `<details>` collapsed audit appendix; plain overwrite; missing-line marker | Accepted | B | FR-032–FR-042, NFR-004, U-010, ISS-202 | none |
| ADR-008 | Test architecture: importable script, tmp_path-generated stub executables, pytest `unit` marker | Accepted | A | FR-043–FR-045, SC-002, AC-021, AC-022, A-008 | none |

No ADR is deferred; there are no `deferred-safe` or `deferred-risky` classifications in this
run. Every requirement has a decided verification path (ADR-008).

---

## ADR-001: Python 3 stdlib-only single-file script

### Context

The deliverable is `scripts/sue_challenge.py`, a standalone host tool (FR-045) that must run
from a fresh checkout with exactly 0 additional installed components (NFR-002) and follow
existing repository conventions (A-008). The repo has a canonical precedent:
`scripts/contradiction-scanner.py` — `#!/usr/bin/env python3`, argparse, stdlib-only,
documented usage header, own exit codes.

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Zero additional installations on fresh checkout | NFR-002 | High |
| Standalone: no orchestration imports or config reads | FR-045, A-003, boundaries.md NON-boundary | High |
| Repository convention for `scripts/` tools | A-008, SCOUT evidence (journal 4) | Medium |
| Later SUE tiers build on the CLI interface, not on internals | spec Out of Scope | Medium |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Python 3 stdlib-only single file (chosen) | Matches NFR-002 exactly; repo precedent; argparse/subprocess/tempfile/json cover every need | One file grows to ~700–900 lines | Chosen — every driver satisfied with zero cost |
| Python package under `src/` with entry point | Cleaner module split | Requires install step (violates NFR-002); couples to the venv install flow; erodes the standalone contract | Rejected |
| Bash script | No runtime question at all | JSON validation, bijection checks, and unit-testable pure functions are impractical; repo pytest conventions unusable | Rejected |
| Third-party deps (click, pydantic, jsonschema) | Less validation code | Any dependency violates NFR-002's "0 additional installed components" | Rejected |

### Decision

- Decision: `scripts/sue_challenge.py`, `#!/usr/bin/env python3`, Python ≥ 3.10 (repo floor),
  imports restricted to the standard library (`argparse`, `subprocess`, `tempfile`, `json`,
  `shlex`, `shutil`, `sys`, `os`, `pathlib`, `dataclasses`, `datetime`, `re`, `textwrap`).
  Zero imports from `harness`, `echelon`, `codegen`, `understanding`, or any project config.
- Status: Accepted
- Deferral classification: none
- Requirements covered: NFR-002, FR-045, A-003, A-008, A-012

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| `scripts/contradiction-scanner.py` header | A | repo @ 2026-07-18 | Exact standalone shape: python3, argparse, stdlib-only, usage docstring, own exit codes |
| `pyproject.toml` `[tool.pytest.ini_options]` | A | repo @ 2026-07-18 | `pythonpath = [".", "src"]`, `testpaths = ["tests"]`, `unit` marker — test file plugs in with zero config changes |
| boundaries.md "Echelon harness (explicit NON-boundary)" | B | 2026-07-18 | Harness `ClaudeCliProvider` serves a different contract (stream-json, tool policy, repo cwd) — must not be reused |

### Consequences

- Positive: fresh-checkout runnable (SC-005); no dependency management; review gate for
  FR-045 is a trivial import scan.
- Negative: hand-rolled schema validation instead of a library (accepted — see ADR-005).
- Risks introduced: single file must stay internally organized (mitigated by ADR-002).
- Follow-up validation: CODE REVIEWER / SPEC GUARD gate — zero `harness.*`/`echelon.*`
  imports, zero orchestration config reads (feasibility.md risk 5).

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | No echelon state-file writes; no assumed API (Principles I, II untouched) |
| Known pitfalls | PASS | Avoids the harness-reuse pitfall named in boundaries.md |
| Consistency with prior ADRs | PASS | First ADR |

---

## ADR-002: Pure-function core, thin CLI shell, single shared schema constants

### Context

FR-044 requires unit tests over 7 deterministic behavior groups with zero live model access;
NFR-004 requires byte-identical report bodies for identical inputs. MODELER's contract map
(journal 16) identifies three-way drift (prompt text ↔ validator ↔ stub fixtures) as the
dominant breakage risk, and WHY2 ISS-206 requires the category enum tokens to be pinned as a
single shared constant at HOW.

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Every deterministic behavior unit-testable in isolation | FR-044 | High |
| Prompt/validator/stub drift prevention | journal 16, ISS-206 | High |
| Deterministic assembly (repeatable output) | NFR-004 | High |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Pure-function core + thin imperative shell (chosen) | Pure functions test without subprocess or filesystem; shell is covered by end-to-end stub tests | Requires discipline about where I/O lives | Chosen |
| Class-based pipeline object | Groups state | Encourages hidden state; harder to test single behaviors; overkill for a linear pipeline | Rejected |
| Logic inline in `main()` | Least code | Untestable without full process runs; violates FR-044's behavior-group coverage | Rejected |

### Decision

- Decision: The script is organized as (a) **module-level constants** — `CATEGORIES`,
  `VERDICTS`, `QUESTION_ID_RE`, round-1/round-2 prompt templates, exit-code constants,
  report filename, debug dir name — referenced by prompt builders, validators, renderer,
  and (via import) tests, so the three-way contract has exactly one source of truth;
  (b) **pure functions** for numbering, prompt assembly, extraction, validation, bijection,
  partition/ranking, and rendering (no I/O, no clock reads — run date is passed in);
  (c) a **thin shell**: `main(argv) -> int` doing pre-flight, subprocess orchestration, file
  writes, and summary printing, with `sys.exit(main())` under `if __name__ == "__main__"`.
- Pinned enum tokens (ISS-206 resolution — FR-015's names are display names for these):
  - categories: `ambiguity`, `hidden-assumption`, `contradiction`, `undefined-term`,
    `missing-boundary`
  - verdicts: `ANSWERED`, `UNANSWERABLE`, `CONTRADICTED`
  - question ids: `^Q[1-9][0-9]*$` (A-010 convention)
- Status: Accepted
- Deferral classification: none
- Requirements covered: FR-044, NFR-004, FR-015, FR-023, A-010

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| mental-model-code.md contract map (journal 16) | B | 2026-07-18 | Three-way schema contracts are the dominant breakage risk; single shared constants named as mitigation |
| issues.md ISS-206 | B | 2026-07-18 | Enum tokens must be pinned as one shared constant at HOW |

### Consequences

- Positive: SENTINEL can enumerate one unit test per pure function per behavior; NFR-004
  determinism holds by construction (run date injected, everything else pure).
- Negative: prompt templates live as long string constants in code — reviewed as code.
- Risks introduced: none material.
- Follow-up validation: tests import the constants rather than re-declaring literals, so an
  enum edit that misses one side fails tests instead of green-testing wrong behavior.

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | TDD hard gate is supported, not hindered |
| Known pitfalls | PASS | Directly mitigates the MODULE_IDS/registerLazy drift failure mode cited by MODELER |
| Consistency with prior ADRs | PASS | Fits the single-file layout of ADR-001 |

---

## ADR-003: Model invocation — `shlex.split(cmd) + ["-p"]`, prompt on stdin, default text output

### Context

OQ-001 asked how the prompt is delivered and with which output flags; this fixes the
extraction design and the stub replay contract. FR-007 fixes shell-quoting word-split of the
model command with word 1 availability-checked; FR-003 fixes the default command `claude`.
The design's mechanism is "two isolated `claude -p` calls".

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Exact fidelity to the designed `claude -p` mechanism | user intent UI-004 | High |
| Confidential spec text must not leak via process listings | org data-protection posture; spec Limitations (egress) | High |
| Large specs must not hit argv size limits | A-005 | Medium |
| Stub replay contract must be trivial | FR-043, FR-044 | High |
| No stream-json / harness backend coupling | FR-045, boundaries.md | High |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Append `-p`; prompt via **stdin**; default text output (chosen) | Matches design wording; spike-verified clean stdout; prompt never appears in `ps` output (spec content is PII-adjacent); no ARG_MAX exposure; stub = "read stdin, print canned JSON" | Stub must consume stdin to avoid pipe errors | Chosen |
| Prompt as positional argv | Slightly simpler call | Spec text visible in process listings — unacceptable for confidential specs; argv size limits for large specs | Rejected |
| `--output-format json` envelope | Machine-shaped wrapper | Model's JSON is still an embedded string needing a second decode; couples the stub contract to a claude-specific envelope, breaking the generic model-command seam (FR-043 allows *any* command) | Rejected |
| Reuse harness `ClaudeCliProvider` (stream-json) | Battle-tested | Violates the standalone contract (FR-045); different contract (tool policy, repo cwd); explicitly fenced as a NON-boundary | Rejected |

### Decision

- Decision: `argv = shlex.split(model_command) + ["-p"]`. The prompt is written to the
  subprocess's **stdin** (UTF-8); stdout and stderr are captured separately;
  `subprocess.run(..., timeout=T, cwd=<fresh temp dir>)`. Raw stdout (default `text` output
  format — no output flags appended) feeds extraction. Availability pre-flight:
  `shutil.which(shlex.split(model_command)[0])` → on miss, exit 2 with one installation
  pointer (ERR-CLI-MISSING mirror); a `FileNotFoundError` at exec time (race) maps to the
  same exit 2. A non-zero subprocess exit code or empty stdout is classified as a parse
  failure (U-007 decision: exit 2 is *only* executable-not-found).
- The appended `["-p"]` and stdin delivery are the **frozen stub replay contract** (see
  `contracts/model-command-contract.md`): stubs receive the same argv tail and must read
  stdin before exiting.
- Status: Accepted
- Deferral classification: none
- Requirements covered: FR-003, FR-007, FR-008, FR-010 (cwd), FR-011, FR-012, FR-043; OQ-001
  resolved

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| Live spike (this phase) | A | claude CLI 2.1.214, 2026-07-18 | `printf <prompt> \| claude -p` from temp cwd: exit 0, stdout = clean JSON + `\n`, ≈6.4 s |
| `claude --help` | B | 2.1.214, 2026-07-18 | `-p/--print` non-interactive; `--output-format` default `text`; prompt accepted positionally or on stdin |
| `src/harness/llm_provider.py` prior art | B | repo @ 2026-07-18 | Proves subprocess-driven claude works; its stream-json contract is what SUE must *not* inherit |

### Consequences

- Positive: happy path needs no extraction gymnastics (spike-verified); privacy-preserving
  prompt delivery; the seam works identically for any operator-supplied command.
- Negative: exactly one flag (`-p`) is appended to arbitrary operator commands — documented
  in the contract; stubs and wrapper scripts must tolerate it.
- Risks introduced: claude CLI version drift could change `-p` stdout shape (unknowns.md
  "version drift") — mitigated by pinning the validated version (2.1.214) in this ADR and by
  the tolerant extractor (ADR-005).
- Follow-up validation: the manual live acceptance run (SC-001) revalidates against the
  operator's installed CLI; spec/prompt size is measured there per ISS-209 (A-005).

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | Constitution Principle V (LLM stays on host) — call runs on host; no sandbox routing |
| Known pitfalls | PASS | Avoids stream-json coupling; avoids argv secret leakage |
| Consistency with prior ADRs | PASS | stdlib `subprocess`/`shlex`/`shutil` only (ADR-001) |

---

## ADR-004: Isolation — fresh `mkdtemp` cwd per call, outside the repository; no suppression flags in v1

### Context

FR-010 requires each model subprocess to run from exactly 1 newly created neutral temporary
directory; AC-012 requires the recorded cwd to be a newly created temp directory outside the
repository. OQ-002 asked whether temp cwd fully satisfies the isolation intent. The spec
already scoped the guarantee to repository-level isolation and documents the operator-scope
residual as a limitation pending investigation.

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Repo-scope ambient context must not reach the model | FR-010, isolation contract | High |
| Exact v1 fidelity — no mechanism expansion | user intent UI-004, TRACKER RF-2/RF-3 | High |
| Traceable resolution of OQ-002 | SAGE ISS-001 path, TRACKER RF-3 | High |
| Version fragility of extra CLI flags | unknowns.md version-drift | Medium |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Fresh `tempfile.mkdtemp` per call, no extra flags (chosen) | Exactly the designed mechanism; spike-verified to block repo-scope context; works with any model command; AC-012 directly testable | Operator-scope context still loads (confirmed) — remains a documented limitation | Chosen |
| Add `--safe-mode` to the invocation | Spike-era CLI (2.1.214) disables CLAUDE.md/skills/plugins/hooks/MCP while auth works — closes most of the residual | Expands v1 beyond the approved design; claude-specific flag breaks the generic model-command seam and older CLIs; unvalidated interaction with `-p` output | Rejected for v1; recorded as the validated candidate for a future traceable amendment |
| Add `--bare` | Strongest suppression | Restricts auth to `ANTHROPIC_API_KEY` only — breaks OAuth operators outright | Rejected |
| Env-var scrubbing (`env=` cleanup) | No CLI coupling | No evidence it controls context loading; risks breaking auth/HOME resolution; pure speculation | Rejected |

### Decision

- Decision: per subprocess invocation (including retries), create one fresh directory via
  `tempfile.mkdtemp(prefix="sue-challenge-")` in the system temp location (outside the
  repository by construction; satisfies AC-012), pass it as `cwd=`, and remove it after the
  call (`shutil.rmtree(..., ignore_errors=True)`). Nothing is written into it. No isolation
  flags are appended in v1.
- OQ-002 disposition (traceable): the spike **confirmed** the residual — user-scope
  settings, plugins/skills, and MCP servers load from a temp cwd on claude 2.1.214; a plugin
  skill was observed injected into the API request. The spec's Limitations wording stands
  and is now evidence-backed rather than "under investigation". The validated suppression
  option (`--safe-mode`) is recorded here for a future design amendment; adopting it in v1
  would violate the no-expansion intent.
- Status: Accepted
- Deferral classification: none (the limitation is a spec-level accepted scope decision made
  at WHAT, not an unverified-requirement deferral: FR-010's testable guarantee — repo-scope
  isolation via temp cwd — is fully implemented and verified by AC-012)
- Requirements covered: FR-010, AC-012; OQ-002 resolved as documented-limitation-with-evidence

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| Live spike debug log | A | claude CLI 2.1.214, 2026-07-18 | From temp cwd: userSettings, user plugins/skills (injected as `additionalContext`), MCP servers all loaded; repo-scope files NOT loaded |
| `claude --help` | B | 2.1.214, 2026-07-18 | `--safe-mode` disables all customizations, auth normal; `--bare` restricts auth; `--setting-sources user,project,local` selects settings scopes |
| spec.md Limitations / FR-010 | A | 2026-07-18 | Guarantee scoped to repo-level isolation; operator-scope exposure documented as limitation pending OQ-002 |

### Consequences

- Positive: FR-010/AC-012 are mechanically testable with a directory-recording stub; the
  isolation mechanism is model-command-agnostic.
- Negative: operator-scope bias channel remains open (now with Grade A evidence of its
  existence) — the human reviewer of the report stays the backstop, as the spec states.
- Risks introduced: none new; the pre-existing limitation is confirmed and better bounded.
- Follow-up validation: usage text / README limitation wording should cite that user-scope
  plugins, hooks, and MCP servers are NOT suppressed and that `--safe-mode` (claude ≥
  2.1.214) is available to operators who need stronger isolation via
  `--claude-cmd "claude --safe-mode"` — an operator choice, not a script default.

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | No trust boundary silently widened (Principle V); the residual is documented, not hidden |
| Known pitfalls | PASS | Resolves the MODELER V-1 alert traceably per TRACKER RF-3 |
| Consistency with prior ADRs | PASS | cwd handling lives in the ADR-003 runner |

---

## ADR-005: Tolerant JSON extraction + strict hand-rolled validation + ID bijection

### Context

Model output is untrusted (boundaries.md trust boundary). FR-026/FR-027 define tolerant
extraction of exactly 1 JSON object; FR-016/FR-024 define strict per-round validation;
FR-025 defines the round-2 identifier bijection; FR-017 makes duplicate round-1 ids a parse
failure. NFR-002 forbids adding a schema library.

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Tolerate fences and surrounding noise; validate strictly | FR-026, FR-024, A-009 | High |
| Single retry budget must not be consumed by cosmetic noise | WHY1 ISS-002, journal 15 | High |
| No third-party validators | NFR-002 | High |
| Bijection is the strongest machine-checkable invariant | journal 6 | High |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Staged extractor + hand-rolled validators (chosen) | Deterministic; fully unit-testable against noisy fixtures; zero deps | ~150 lines of validation code | Chosen |
| `json.loads` on raw stdout only | Trivial | Any fence or prose = parse failure; converts systematic wrapper noise into exit-3 loops | Rejected |
| `jsonschema` library | Declarative schemas | Third-party dependency violates NFR-002 | Rejected |

### Decision

- Decision — extraction (`extract_json_object(raw: str) -> dict | ParseFailure`), staged,
  first success wins, all stages deterministic:
  1. `json.loads(raw.strip())` — the spike-verified happy path;
  2. strip a single Markdown code fence (```` ```json ```` or ```` ``` ````) and retry;
  3. scan left-to-right from each `{`, take the balanced-brace candidate (string- and
     escape-aware) and attempt `json.loads`; the first candidate that parses as a JSON
     *object* is the result.
  Zero parses → parse failure (FR-027). The extractor returns exactly one object; content
  after the extracted object is ignored (tolerated surrounding text per FR-026).
- Decision — validation (strict, against the ADR-002 shared constants):
  - Round 1 top-level shape `{"questions": [...]}`: each item has exactly the keys
    `id` (matches `^Q[1-9][0-9]*$`, unique across the list — duplicates are a parse failure,
    FR-017), `question` (non-empty str), `target` (non-empty str: requirement id or
    `general`), `lines` (list of ints), `category` (∈ CATEGORIES). Unknown keys are ignored
    (model chattiness is not an error); missing/mistyped keys are a parse failure.
  - Round 2 top-level shape `{"answers": [...]}`: each item has `id`, `verdict`
    (∈ VERDICTS), `answer` (non-empty str), `evidence_lines` (list of ints).
  - Bijection (FR-025): the multiset of answer ids must equal the set of (possibly
    truncated, FR-019) round-1 question ids — any missing, duplicate, or unknown id is a
    parse failure naming the offending ids (the message feeds the corrective retry).
  - Line references are validated as integers only; range-checking is deliberately deferred
    to render time (ADR-007) so a cosmetic out-of-range citation never burns the retry
    budget (ISS-202 rationale).
- Status: Accepted
- Deferral classification: none
- Requirements covered: FR-016, FR-017, FR-024, FR-025, FR-026, FR-027, A-009, A-010

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| Live spike | A | claude 2.1.214, 2026-07-18 | Happy path is clean JSON — stage 1 suffices in the observed case |
| unknowns.md "Output-noise channels" | C | 2026-07-18 | CLI noise varies by environment/version — stages 2–3 are the insurance |
| spec.md FR-026/FR-024 (U-003/U-008 decisions) | A | 2026-07-18 | Extraction tolerant, validation strict — contract fixed at WHAT |

### Consequences

- Positive: cosmetic wrappers never consume the retry; validation failures produce precise
  corrective messages (better round-2 retry success odds); everything unit-tests offline
  against noisy fixtures.
- Negative: hand-rolled brace scanner must handle strings/escapes correctly — it gets its
  own dedicated unit tests.
- Risks introduced: an extractor bug could accept the wrong object when multiple JSON
  objects appear; mitigated by "first parseable object wins" determinism + fixtures.
- Follow-up validation: SENTINEL derives fixtures for: clean JSON, fenced JSON, prose-then-
  JSON, multiple objects, zero objects, every single-field violation, and every bijection
  violation (missing / duplicate / unknown id).

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | — |
| Known pitfalls | PASS | Defuses the single-retry-exhaustion pitfall (journal 15) |
| Consistency with prior ADRs | PASS | Consumes ADR-003 raw stdout; uses ADR-002 shared constants |

---

## ADR-006: Failure-handling state machine — exit codes 0/1/2/3, timeout→parse-failure, one retry per round

### Context

The spec fixes a complete failure taxonomy: pre-flight exit 1 (FR-005/FR-006), executable-
not-found exit 2 (FR-012), unrecoverable parse failure exit 3 with debug dump (FR-030),
timeout classified as parse failure (FR-011), exactly one corrective retry per round with a
fresh timeout budget (FR-013, FR-028), plain re-issue after timeout (FR-029), no round-1
re-run after a round-2 failure (FR-031), one stderr diagnostic line per non-zero exit
(NFR-005), and a wall-clock bound (NFR-001).

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Deterministic, enumerable failure behavior | ERR-001–ERR-005, SC-003 | High |
| Bounded wall clock | NFR-001, SC-004 | High |
| Offline diagnosability of parse failures | FR-030, AC-015 | Medium |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Explicit typed outcome per call + per-round attempt loop (chosen) | Each transition is a pure, testable decision; exit codes fall out of one mapping | Slightly more structure than exceptions-everywhere | Chosen |
| Exception-driven control flow | Idiomatic | Exit-code mapping scattered across handlers; harder to prove "exactly 1 diagnostic line" | Rejected |
| Configurable retry count | Flexibility | Spec fixes exactly 1 retry; configurability is scope expansion | Rejected |

### Decision

- Decision: a `CallOutcome` value (ok(raw) | timeout | launch_missing | failed(raw, reason))
  is produced by the ADR-003 runner; a per-round loop runs at most 2 attempts:
  - attempt 1 fails validation/extraction → build corrective retry prompt (same prompt +
    appended corrective instruction naming the failure, zero echoed output — FR-028); if
    attempt 1 was a timeout → identical prompt, zero appended text (FR-029); fresh timeout
    budget (FR-013);
  - attempt 2 fails → write `.sue-debug/` (raw stdout+stderr of *both* failing attempts of
    that round; for a timeout attempt, whatever partial output was captured plus a one-line
    `TIMEOUT after <T>s` note — ISS-207), print one diagnostic line to stderr, exit 3;
  - round-2 failure never re-enters round 1 (FR-031).
- Pre-flight order (all before any model call): spec readable (else exit 1, ERR-001) →
  spec directory writable via `os.access(dir, W_OK)` (else exit 1, ERR-002) → model
  executable found via `shutil.which` (else exit 2, ERR-003).
- Exit-code mapping is a single constant table; every non-zero exit path funnels through one
  `fail(code, message)` helper that prints exactly 1 line to stderr (NFR-005).
- Wall-clock bound holds structurally: ≤ 4 subprocess invocations (2 rounds × 2 attempts),
  each bounded by the FR-004 timeout; local work is file I/O and pure computation (NFR-001).
- Status: Accepted
- Deferral classification: none
- Requirements covered: FR-005, FR-006, FR-011, FR-012, FR-013, FR-028–FR-031, ERR-001–ERR-005, NFR-001, NFR-005, SC-003, SC-004

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| spec.md error-handling FRs + U-005/U-007 decisions | A | 2026-07-18 | Complete assigned behavior for every failure class — no invention needed |
| Python `subprocess` docs (stdlib, in training + repo usage) | B | Python ≥3.10 | `TimeoutExpired` carries partial `stdout`/`stderr` when `capture_output` is used |

### Consequences

- Positive: SC-003's per-class reproduction tests map 1:1 onto the outcome table; the "exactly
  1 diagnostic line" NFR is enforced by a single choke point.
- Negative: none material.
- Risks introduced: `os.access` writability pre-flight can be defeated by exotic ACLs; the
  report write itself still error-handles (failure after model calls reports exit 1 with the
  diagnostic line — pre-flight makes this path practically unreachable, AC-019 covers the
  detectable case).
- Follow-up validation: SENTINEL exit-code matrix tests (SC-003) with stub commands that
  replay malformed output, sleep past the timeout, or are absent from PATH.

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | — |
| Known pitfalls | PASS | Timeout and non-zero-exit funnels are explicit, closing the U-007 masquerade gap |
| Consistency with prior ADRs | PASS | Consumes ADR-003 outcomes; feeds ADR-005 extraction |

---

## ADR-007: Report rendering — GFM with `<details>` collapsed audit appendix; plain overwrite; missing-line marker

### Context

FR-032–FR-042 fix the report: three sections in order, 4 base header facts (+ truncation
note), findings with verdict/question/target/evidence, quoted evidence lines (FR-039),
collapsed audit appendix (FR-038, the requirement DISCOVER once dropped — TRACKER RF-1),
plain overwrite semantics (U-010), explicit zero-findings statement (FR-041), terminal
summary (FR-040). WHY2 ISS-202 flagged out-of-range evidence line references as unassigned
render behavior.

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Collapsed-but-expandable audit section in plain Markdown | FR-038, AC-008 | High |
| Verifiable quoted evidence (grounding rule) | FR-039, FR-018, U-006 decision | High |
| Byte-identical bodies for identical inputs | NFR-004 | High |
| Deterministic behavior for out-of-range citations | ISS-202 | Medium |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| HTML `<details><summary>` block (chosen) | GitHub-Flavoured Markdown renders it natively collapsed and expandable; plain-text readable | Relies on GFM rendering for the collapse | Chosen — constitution's rendering default is GFM; the design demands a collapsed section a reader can expand, which raw Markdown alone cannot do |
| Plain `## Appendix` heading | No HTML | Not collapsed — violates FR-038/AC-008 (the exact fidelity-drift SAGE flagged) | Rejected |
| Atomic write (temp file + rename) | Crash safety | U-010 explicitly declines any atomicity guarantee in v1; adding it is silent scope expansion and contradicts the recorded spec decision | Rejected |

### Decision

- Decision: `render_report(...) -> str` is pure; the shell writes it to
  `<spec-dir>/socratic-challenge.md` with a plain `open(path, "w")` overwrite (U-010: no
  atomicity claimed). Layout:
  1. **Header** — `# Socratic Challenge Report` then exactly the 4 base facts (specification
     path, run date, question count, finding count) as a list, plus the truncation note line
     only when FR-019 truncation occurred.
  2. **Findings** — ranked per FR-033 (all CONTRADICTED, then all UNANSWERABLE, round-1
     question order preserved within each class); each entry states verdict, question,
     target, and evidence (quoted per line: `> line N: <text>`); UNANSWERABLE entries state
     the named gap from the answer text (FR-039). When every verdict is ANSWERED the section
     states that exactly 0 findings were produced (FR-041).
  3. **Audit appendix** — exactly one `<details>` block (`<summary>Audit appendix — N
     ANSWERED questions</summary>`) listing every ANSWERED question with its quoted
     answering lines (FR-038).
- Evidence quoting: for each cited integer, quote exactly the 1-based line from the spec's
  read-once line list (FR-018/FR-039). A cited number `< 1` or `> line count` renders the
  deterministic marker `> line N: (not present in the specification)` — resolving ISS-202 at
  render time so a cosmetic model slip never consumes the retry budget (consistent with
  ADR-005's integer-only validation).
- Terminal summary (FR-040): after the report write, print finding counts per verdict class
  and the top 3 findings in rank order to stdout; human-oriented, no machine contract
  (A-011). Run date is injected into the renderer (ISO date), keeping NFR-004's
  "identical outside the run-date field" trivially satisfiable in tests.
- Status: Accepted
- Deferral classification: none
- Requirements covered: FR-032–FR-042, NFR-004, AC-002–AC-009, U-010, ISS-202

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| Constitution "Rendering" default | A | v1.0.0, 2026-07-18 | Artifacts are GitHub-Flavoured Markdown — `<details>` is the GFM collapse idiom |
| spec.md FR-038 + issues.md ISS-202 recommendation | A/B | 2026-07-18 | Collapsed section mandatory; render-time marker recommended over validation failure |

### Consequences

- Positive: the audit appendix satisfies "collapsed, reader can expand" in every GFM
  renderer while degrading readably in plain text; rendering is 100% unit-testable.
- Negative: a torn report file is possible if the process dies mid-write — explicitly
  accepted by U-010.
- Risks introduced: none beyond the accepted U-010 posture.
- Follow-up validation: NFR-004 test renders twice from identical inputs and diffs bodies
  excluding the run-date line.

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | GFM rendering default honoured |
| Known pitfalls | PASS | Does not reintroduce the atomicity embellishment SAGE struck (ISS-008/ISS-204) |
| Consistency with prior ADRs | PASS | Pure renderer per ADR-002; consumes ADR-005 validated answers |

---

## ADR-008: Test architecture — importable script, tmp_path-generated stub executables, pytest `unit` marker

### Context

FR-044 requires offline unit tests over 7 deterministic behavior groups; FR-043 makes the
model-command option the test seam; SC-002 requires zero network calls and zero live model
commands; AC-011/AC-012 require prompt-recording and cwd-recording stubs; A-008 binds to
repo pytest conventions (`testpaths=["tests"]`, `pythonpath=[".", "src"]`, `unit` marker,
`tests/fixtures` not collected).

### Decision Drivers

| Driver | Source | Weight |
|--------|--------|--------|
| Zero live model access in CI | SC-002, AC-022 | High |
| Existing pytest conventions, zero config changes | A-008, journal 17 | High |
| Stub must record prompts and cwd, and replay per-call outputs | AC-011, AC-012, AC-016 | High |

### Considered Options

| Option | Pros | Cons | Why Rejected / Chosen |
|--------|------|------|-----------------------|
| Tests generate stub scripts into `tmp_path` (chosen) | Each test customizes replay/record behavior; no committed executables, no permission-bit or fixture-drift concerns; stub is 10–20 lines written by a helper | Small stub-writing helper needed in the test file | Chosen |
| Committed stub executables in `tests/fixtures/sue/` | Reusable | One rigid stub can't cover record/replay/sleep/absent variants without env-var protocols; executable bits and fixture drift to manage | Rejected |
| Monkeypatching `subprocess.run` | No processes spawned | Bypasses the real seam — FR-043/AC-021 explicitly require the *command substitution* path to be exercised end-to-end | Rejected for seam tests; still fine for pure-function tests that never reach the runner |

### Decision

- Decision: `tests/unit/test_sue_challenge.py`, marked `@pytest.mark.unit`. The script
  module is loaded once via `importlib.util.spec_from_file_location` from
  `scripts/sue_challenge.py` (scripts/ is not a package; `main()` is guarded so import has
  no side effects). Two test styles:
  1. **Pure-function tests** call extraction/validation/partition/ranking/rendering
     directly, importing the ADR-002 shared constants instead of re-declaring literals.
  2. **Seam tests** write a small python3 stub into `tmp_path` (chmod +x), pass it via the
     model-command option, and run `main([...])` in-process asserting exit codes, report
     content, summary output, and side effects. Stub template: read all of stdin; append
     argv/cwd/prompt to a recording file given by an environment variable; print the next
     canned reply from a numbered replay directory (supports the AC-016 invalid-then-valid
     sequence); optional sleep mode for timeout tests (with a sub-second timeout option to
     keep the suite fast).
  Behavior-group coverage map (FR-044): argument handling → argparse tests; prompt assembly
  → pure builders + AC-011 recording stub; extraction → noisy fixtures; validation +
  bijection → per-violation fixtures; filtering + ranking → pure tests; report rendering →
  golden-string tests incl. NFR-004 double-render; exit codes → SC-003 matrix via stubs.
- The one live validation in v1 remains the manual acceptance run (SC-001/AC-023) against
  `specs/029-builder-spec-workbench/spec.md`, executed at FINALIZE with the A-004 anchor
  re-verify/freeze step first. It is a manual gate, not a pytest test.
- Status: Accepted
- Deferral classification: none (the acceptance run is a spec-mandated manual criterion,
  SC-001 — not an unverified-requirement deferral; every FR has automated coverage)
- Requirements covered: FR-043, FR-044, FR-045 (import scan test), SC-002, SC-005, AC-011,
  AC-012, AC-016, AC-021, AC-022, A-008

### Evidence

| Source | Grade | Version / Date Checked | Finding |
|--------|-------|------------------------|---------|
| `pyproject.toml` pytest config + `tests/unit/conftest.py` | A | repo @ 2026-07-18 | Conventions verified: `unit` marker, testpaths, fixtures dir excluded from collection |
| MODELER journal 17 | B | 2026-07-18 | Repo pytest config supports the planned test file with zero changes |

### Consequences

- Positive: the entire deterministic core is verified offline; the seam tests exercise the
  same code path a live run uses, differing only in the command string.
- Negative: stub-writing helper adds ~30 lines to the test file.
- Risks introduced: in-process `main()` calls must not leak `sys.exit` — `main` returns an
  int and only the `__main__` guard exits (ADR-002).
- Follow-up validation: SENTINEL owns the full test enumeration; the ISS-201/ISS-203
  counting rewordings should land in spec.md before that enumeration (flagged to COMMANDER
  in plan.md Risks — CARTOGRAPHER-owned, not an architecture change).

### Self-Check

| Check | Result | Notes |
|-------|--------|-------|
| Constitution NEVER rules | PASS | Test-First hard gate directly supported |
| Known pitfalls | PASS | Seam tested for real, not monkeypatched away |
| Consistency with prior ADRs | PASS | Depends on ADR-002 importability and ADR-003 frozen argv/stdin contract |

---

## Cross-Cutting Concern Coverage

| Concern | ADR(s) | Summary | Gaps |
|---------|--------|---------|------|
| Security | ADR-003, ADR-004 | Prompt via stdin (no argv leakage of confidential spec text into process listings); model command is an operator-trust seam never sourced from config/network (spec Limitations); untrusted model output is validated, never executed or eval'd; spec file strictly read-only (FR-042); no secrets handled; egress disclosure in usage text (NFR-003) | Operator-scope ambient context reaches the model (confirmed OQ-002 residual) — documented limitation, human reviewer is the backstop |
| Observability | ADR-006, ADR-007 | Exactly 1 diagnostic stderr line per non-zero exit naming the failure class (NFR-005); terminal summary on success (FR-040); `.sue-debug/` raw dumps incl. timeout notes for offline diagnosis (FR-030, ISS-207) | No verbose/log-level flag — deliberate: v1 interface is frozen at 1 positional + 3 options |
| Performance | ADR-006 | Wall clock structurally bounded: ≤ 4 timeout budgets + trivial local work (NFR-001); spec read once (FR-045); no polling, no retries beyond the fixed budget | Context-window overflow for oversized specs is an accepted spec limitation (A-005), measured at acceptance |
| Error Handling | ADR-005, ADR-006 | Complete taxonomy: pre-flight (exit 1) / executable-not-found (exit 2) / unrecoverable parse failure incl. timeout (exit 3); tolerant extraction so cosmetic noise never consumes the single corrective retry; bijection violations produce precise corrective messages | none |

## Proposed Technical Principles

| Principle | Source ADR | Reason | Requires Human Approval |
|-----------|------------|--------|-------------------------|
| (none proposed) | — | The governing constitution (v1.0.0) is scoped to the echelon Builder FE domain; CHIEF verified it non-conflicting with this standalone tool (journal 32). The tool-level invariants worth enforcing (stdlib-only, no harness imports, single shared schema constants) are already binding spec requirements (NFR-002, FR-045) or ADR decisions with review gates — encoding them as FE-constitution amendments would mis-scope the document. No `constitution-amendment-candidates.md` is emitted. | — |
