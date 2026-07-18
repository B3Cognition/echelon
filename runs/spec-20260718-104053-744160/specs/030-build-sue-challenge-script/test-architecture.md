# Test Architecture — SUE Challenge Script

## Metadata

- Spec: 030-build-sue-challenge-script
- Sentinel: speckit-echelon-sentinel (SENTINEL)
- Date: 2026-07-18

## Framework Choices

| Layer | Framework / Tool | Reason | Alternatives Rejected |
|-------|------------------|--------|-----------------------|
| Unit | pytest with `@pytest.mark.unit`, pure-function calls on the imported script module | Repo convention (A-008: `pyproject.toml` `testpaths=["tests"]`, `unit` marker, `pythonpath=[".", "src"]`); zero config changes; NFR-002 forbids new deps | unittest (repo standard is pytest); pytest plugins (pytest-repeat, pytest-mock — extra installs violate NFR-002's spirit) |
| Integration | same pytest file, stub-seam style: in-process `main(argv)` + real generated stub executables spawned by `subprocess.run` | FR-043/AC-021 require the command-substitution path exercised for real; ADR-008 explicitly rejects monkeypatching the seam | monkeypatching `subprocess.run` (bypasses the real seam — allowed only for pure-function tests that never reach the runner); committed stub fixtures (rigid, permission-bit drift — ADR-008) |
| E2E | none automated. The single live-model validation is the manual FINALIZE acceptance run (SC-001), outside pytest | SC-002 forbids live model calls in the suite; the spec defines the live check as a manual gate with tolerance (AC-023) | a pytest-marked "live" test tier (would normalize live calls in CI and violate SC-002's zero-live-command guarantee) |
| Contract | shared-constant imports: tests import `CATEGORIES`, `VERDICTS`, `QUESTION_ID_RE`, `REPORT_FILENAME`, `DEBUG_DIR_NAME`, exit-code constants from the script module (ADR-002) and assert prompts/validators/stubs agree | The three-way contract (prompt ↔ validator ↔ stub fixture) is the dominant breakage risk (ISS-206); one source of truth makes drift a test failure | re-declared literals in tests (green-tests wrong behavior on enum drift); jsonschema (dependency, NFR-002) |

## Module Loading (the import seam)

`scripts/` is not a package. The test file loads the deliverable once per session via:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("sue_challenge", SCRIPTS_DIR / "sue_challenge.py")
sue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sue)   # import must be side-effect-free (ADR-002 __main__ guard)
```

exposed as a session-scoped fixture `sue` in the test file. `main(argv) -> int` is called in-process and must never raise `SystemExit` (asserted by T-SEAM-01's plain return-code check).

## Test Folder Structure

```text
echelon/
└── tests/
    └── unit/
        └── test_sue_challenge.py     single file, @pytest.mark.unit throughout
            # internal layout (classes group the FR-044 behavior groups):
            #   module fixtures: sue (loaded module), spec_file, make_stub
            #   TestArgumentHandling      (group 1: T-ARG-*)
            #   TestPromptAssembly        (group 2: T-PRM-*)
            #   TestExtraction            (group 3: T-EXT-*)
            #   TestValidationBijection   (group 4: T-VAL-*)
            #   TestFilteringRanking      (group 5: T-RNK-*)
            #   TestReportRendering       (group 6: T-RPT-*)
            #   TestExitCodes             (group 7: T-EXC-*)
            #   TestSeamEndToEnd          (cross-group: T-SEAM-*)
```

No new fixture directories: `tests/fixtures/` stays untouched (ADR-008); all file-shaped test data (spec fixtures, stub executables, replay files, recording files) is generated into `tmp_path` per test. Malformed-JSON and report-golden fixtures live as inline string constants in the test file.

## Shared Test Utilities

| Utility | Purpose | Owner Layer | Location |
|---------|---------|-------------|----------|
| `sue` (session fixture) | importlib-load `scripts/sue_challenge.py` once; expose module for pure-function calls, shared constants, and `main` | all | top of `test_sue_challenge.py` |
| `make_spec(tmp_path, lines) -> Path` | write a synthetic markdown spec fixture with known numbered lines | unit + integration | test file helper |
| `make_stub(tmp_path, *, replies=None, mode="replay", sleep=None, exit_code=0) -> tuple[Path, Path]` | write an executable python3 stub honouring the stub replay contract (model-command-contract.md rules 1–5): reads stdin to EOF; appends argv/cwd/prompt to a recording file named by env var `SUE_TEST_RECORD`; replies with `replies[n]` on the nth call via a counter file; optional sleep mode; optional non-zero exit. Returns (stub path, recording dir) | integration | test file helper (~30 lines, per ADR-008) |
| `run_main(sue, argv, env) -> (code, stdout, stderr)` | call `main(argv)` in-process with capsys/monkeypatched env; assert exactly-one-stderr-line invariants centrally (NFR-005) | integration | test file helper |
| `read_record(record_dir) -> list[CallRecord]` | parse the stub recording file into per-call (argv, cwd, prompt) entries for AC-011/AC-012 assertions | integration | test file helper |
| canned JSON constants | valid round-1/round-2 replies, every per-field violation, bijection-violation variants, fenced/prose-wrapped/multi-object envelopes | unit + integration | module-level string constants in the test file |
| golden report constants | expected `socratic-challenge.md` bodies (mixed verdicts, zero findings, zero questions, truncated) with the run-date line parameterized | unit | module-level constants |

## Test Doubles

| Dependency | Double Type | Scope | Contract Verification |
|------------|-------------|-------|-----------------------|
| Model command (`claude`) | fake — generated executable stub passed via `--claude-cmd` | all integration/seam tests | stub implements the frozen replay contract (accept trailing `-p`; read stdin to EOF; reply/sleep/fail per mode; record argv+cwd+prompt via env var); the same contract file binds the real CLI, so the double and the production dependency share one written contract |
| Model command absent | absence — `--claude-cmd` naming a nonexistent executable, with stub dir removed from PATH | exit-2 tests (T-EXC-03) | `shutil.which` miss is the contract trigger (FR-012) |
| Clock (run date) | parameter injection — `render_report` receives `run_date`; no monkeypatching needed | rendering tests | NFR-004 double-render byte-diff proves no hidden clock read |
| Filesystem | real, sandboxed to pytest `tmp_path` | all | spec-untouched check hashes the fixture before/after (FR-042) |
| `subprocess.run` | real (never doubled in seam tests); monkeypatch permitted only in pure-function tests that never reach the runner | per ADR-008 | seam tests spawn real processes so the argv/stdin/cwd/timeout contract is observed, not simulated |
| Network | none exists to double — script performs no network I/O (all egress is inside the model command, which is the stub) | suite-wide | SC-002 holds by construction; CI runs with no `claude` installed |

## Naming Conventions

| Test Type | Naming Pattern | Example |
|-----------|----------------|---------|
| Unit | `test_<function>__<behavior>` inside the behavior-group class; docstring carries the coverage-map test ID + requirement IDs | `def test_validate_round2__duplicate_id_names_offender(self): """T-VAL-09 — FR-025, AC-018"""` |
| Integration | `test_<scenario>__<expected_outcome>` inside `TestExitCodes`/`TestSeamEndToEnd`; docstring carries test ID + AC | `def test_missing_executable__exit_2_with_install_pointer(self): """T-EXC-03 — FR-012, ERR-003, AC-014"""` |
| E2E | n/a in pytest — the FINALIZE manual run is documented in plan.md Final Phase, evidence recorded in the run journal | — |

Test IDs (`T-ARG-*`, `T-PRM-*`, `T-EXT-*`, `T-VAL-*`, `T-RNK-*`, `T-RPT-*`, `T-EXC-*`, `T-SEAM-*`, `T-META-*`) are the join key to `coverage-map.md`; every test docstring must carry its ID so IMPLEMENTATION MAPPER can trace coverage mechanically.

## Harness Configuration Notes

- Timeout tests pass `--timeout` values around 0.2–0.5 s with stub sleeps ≥ 3× the budget, keeping the whole suite inside the pre-commit 30 s target while leaving a wide anti-flake margin.
- The FR-045 import-scan test (T-SEAM-07) asserts two things from the loaded module: (a) every top-level import of `sue_challenge.py` resolves to the standard library (also evidencing NFR-002), and (b) no name from `harness`, `echelon`, `codegen`, or `understanding` appears in `sys.modules` as a result of the import.
- The NFR-005 single-diagnostic-line assertion is centralized in `run_main` so every non-zero-exit test verifies it for free (the SC-003 matrix then holds by construction across T-EXC-01..T-EXC-10).
- Call counting for FR-008/FR-009/FR-031/NFR-001 reuses the stub's recording file: the number of recorded calls is the number of subprocess invocations.
