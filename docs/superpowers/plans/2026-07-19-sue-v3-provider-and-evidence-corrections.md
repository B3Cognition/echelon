# SUE v3 Provider and Evidence Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make heterogeneous SUE readers executable across Claude and Copilot, remove model/framing confounding, replace the retention overclaim with requirement-local evidence metrics, and keep witness classification explicitly heuristic.

**Architecture:** Preserve the v1 Claude subprocess contract by default while adding an internal provider protocol selected by v3 model-command specifications. Build a deterministic Cartesian reader matrix of model commands × framings, record provider provenance separately from framing, and compute evidence overlap and coverage per requirement. Keep `proto_justification` as an explicitly incomplete schema seam for the later dialectic-produced Justification Graph.

**Tech Stack:** Python 3.10+ standard library, pytest, existing SUE v1 subprocess/retry plumbing.

## Global Constraints

- Preserve all existing v1 and v2 command behavior.
- Keep the implementation standard-library only.
- Keep model output parsing and retries on the existing v1 path.
- Preserve `--claude-cmd` as a backward-compatible alias.
- Treat Copilot prompt-in-argv exposure as an explicit provider limitation.
- Do not claim evidence overlap is critical-fact retention.
- Do not claim negation asymmetry proves behavioural incompatibility.
- Do not commit changes unless the user explicitly requests it.

---

### Task 1: Provider-Aware Model Invocation

**Files:**
- Modify: `scripts/sue_challenge.py:155`
- Modify: `scripts/sue_challenge.py:420`
- Modify: `scripts/sue_reproducibility.py:654`
- Test: `tests/unit/test_sue_challenge.py`
- Test: `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Produces: `RunConfig.model_protocol: str = "claude-stdin"`
- Produces: `ModelCommand(provider: str, command: str, model_tag: str)`
- Produces: `parse_model_command(value: str) -> ModelCommand`
- Consumes: provider specifications `claude=COMMAND`, `copilot=COMMAND`, or legacy command text with provider inferred from executable name.

- [ ] **Step 1: Write failing invocation tests**

```python
def test_claude_protocol_appends_print_flag_and_sends_prompt_on_stdin():
    config = sue.RunConfig(Path("spec.md"), 1, "claude", 30, "claude-stdin")
    invocation = sue.build_model_invocation(config, "PROMPT")
    assert invocation.argv == ["claude", "-p"]
    assert invocation.stdin_text == "PROMPT"


def test_copilot_protocol_passes_prompt_after_p_and_requests_silent_output():
    config = sue.RunConfig(Path("spec.md"), 1, "copilot", 30, "copilot-argv")
    invocation = sue.build_model_invocation(config, "PROMPT")
    assert invocation.argv == [
        "copilot", "-p", "PROMPT", "-s", "--no-custom-instructions"
    ]
    assert invocation.stdin_text is None
```

- [ ] **Step 2: Run invocation tests and verify RED**

Run: `pytest -q tests/unit/test_sue_challenge.py -k model_invocation`

Expected: FAIL because `model_protocol`, `ModelInvocation`, and `build_model_invocation` do not exist.

- [ ] **Step 3: Implement the provider invocation seam**

Add:

```python
@dataclass(frozen=True)
class ModelInvocation:
    argv: list[str]
    stdin_text: str | None


def build_model_invocation(config: RunConfig, prompt: str) -> ModelInvocation:
    words = shlex.split(config.model_command)
    if config.model_protocol == "copilot-argv":
        return ModelInvocation(
            words + ["-p", prompt, "-s", "--no-custom-instructions"],
            None,
        )
    return ModelInvocation(words + ["-p"], prompt)
```

Update `run_model_call()` to use `ModelInvocation.argv` and pass `stdin_text` to `communicate()`. The default protocol remains `claude-stdin`, preserving all v1/v2 stubs.

- [ ] **Step 4: Write failing provider-parser tests**

```python
def test_explicit_copilot_provider_spec():
    command = v3.parse_model_command("copilot=copilot --no-color")
    assert command.provider == "copilot"
    assert command.command == "copilot --no-color"
    assert command.model_tag == "copilot"


def test_legacy_claude_command_is_inferred():
    command = v3.parse_model_command("claude --model sonnet")
    assert command.provider == "claude"
```

- [ ] **Step 5: Run provider-parser tests and verify RED**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k model_command`

Expected: FAIL because `ModelCommand` and `parse_model_command` do not exist.

- [ ] **Step 6: Implement parsing and backward-compatible CLI aliases**

Support:

```text
--model-cmd claude=claude
--model-cmd copilot=copilot
--claude-cmd /path/to/legacy-stub
```

Use one argparse destination with repeatable `--model-cmd` and `--claude-cmd` aliases. Explicit provider prefixes govern the protocol; otherwise infer `copilot` only when the executable basename is `copilot`, with all other commands retaining the legacy Claude/stdin contract.

- [ ] **Step 7: Run focused provider tests**

Run: `pytest -q tests/unit/test_sue_challenge.py tests/unit/test_sue_reproducibility.py -k 'invocation or model_command'`

Expected: PASS.

---

### Task 2: Unconfounded H4 Reader Matrix

**Files:**
- Modify: `scripts/sue_reproducibility.py:112`
- Modify: `scripts/sue_reproducibility.py:718`
- Test: `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Produces: `ReaderJob(reader_no, framing_name, framing_suffix, model_command)`
- Produces: `build_reader_jobs(model_commands, readers_per_model, framings) -> list[ReaderJob]`
- Changes: `--readers` means readers per model command; each model receives the same framing sequence.
- Produces sidecar reader fields: `provider`, `model_tag`, and `framing`.

- [ ] **Step 1: Write the failing Cartesian-matrix test**

```python
def test_two_models_receive_the_same_three_framings():
    commands = [
        v3.ModelCommand("claude", "claude", "claude"),
        v3.ModelCommand("copilot", "copilot", "copilot"),
    ]
    jobs = v3.build_reader_jobs(commands, 3, v3.FRAMINGS)
    assert [(j.model_command.provider, j.framing_name) for j in jobs] == [
        ("claude", "structural"),
        ("claude", "behavioural"),
        ("claude", "adversarial"),
        ("copilot", "structural"),
        ("copilot", "behavioural"),
        ("copilot", "adversarial"),
    ]
```

- [ ] **Step 2: Run matrix test and verify RED**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k same_three_framings`

Expected: FAIL because `ReaderJob` and `build_reader_jobs` do not exist.

- [ ] **Step 3: Implement deterministic job construction**

Loop model commands outermost and reader offsets innermost so every model receives identical framing coverage. Number jobs densely from 1. Main must iterate jobs rather than independently cycling commands and framings.

- [ ] **Step 4: Write failing provenance and preflight tests**

Test that every configured command is preflighted, and that sidecar reader records provider and model tag separately from framing.

- [ ] **Step 5: Run provenance tests and verify RED**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k 'preflight or provenance'`

Expected: FAIL until the main loop and sidecar are updated.

- [ ] **Step 6: Update main and sidecar**

Do not concatenate `framing/model_tag`. Store:

```json
{
  "reader": 4,
  "provider": "copilot",
  "model_tag": "copilot",
  "framing": "structural"
}
```

- [ ] **Step 7: Run matrix and scenario tests**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k 'framing or provenance or Scenario'`

Expected: PASS.

---

### Task 3: Requirement-Local Evidence Metrics

**Files:**
- Modify: `scripts/sue_reproducibility.py:439`
- Modify: `scripts/sue_reproducibility.py:502`
- Modify: `scripts/sue_reproducibility.py:581`
- Test: `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Replaces: `shared_evidence(readers) -> float`
- Produces: `evidence_metrics(readers) -> dict`
- Result fields: `mean_overlap: float | None`, `coverage: float`, and per-requirement `overlap`, `reader_coverage`, `union_lines`.

- [ ] **Step 1: Write failing evidence-semantic tests**

```python
def test_no_evidence_is_na_not_perfect_overlap():
    metrics = v3.evidence_metrics([_reader(1, {}), _reader(2, {})])
    assert metrics["mean_overlap"] is None
    assert metrics["coverage"] == 0.0


def test_evidence_is_compared_per_requirement():
    left = {
        "FR-001": _interp([_edge("system", "write", line=1)]),
        "FR-002": _interp([_edge("system", "read", line=2)]),
    }
    right = {
        "FR-001": _interp([_edge("system", "write", line=1)]),
        "FR-002": _interp([_edge("system", "read", line=3)]),
    }
    metrics = v3.evidence_metrics([_reader(1, left), _reader(2, right)])
    assert metrics["per_requirement"]["FR-001"]["overlap"] == 1.0
    assert metrics["per_requirement"]["FR-002"]["overlap"] == 0.0
```

- [ ] **Step 2: Run evidence tests and verify RED**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k evidence`

Expected: FAIL because the current global `shared_evidence()` returns a scalar and reports no-evidence as 1.0.

- [ ] **Step 3: Implement requirement-local metrics**

For each requirement and surviving reader, collect cited edge and assertion lines. Compute:

```text
overlap = intersection / union, or null when union is empty
reader_coverage = readers citing at least one line / surviving readers
coverage = nonempty requirement-reader cells / all requirement-reader cells
mean_overlap = mean of non-null requirement overlaps
```

- [ ] **Step 4: Update report and sidecar**

Measurement vector labels must be:

```text
evidence overlap (mean/requirement): N/A | 0.00..1.00
evidence coverage: 0.00..1.00
```

Sidecar key must be `evidence`, not `shared_evidence` or `critical_fact_retention`.

- [ ] **Step 5: Run evidence and rendering tests**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k 'evidence or report or sidecar'`

Expected: PASS.

---

### Task 4: Honest Witness Naming and Documentation

**Files:**
- Modify: `scripts/sue_reproducibility.py:122`
- Modify: `scripts/sue_reproducibility.py:398`
- Modify: `docs/superpowers/specs/2026-07-19-sue-v3-reproducibility-design.md`
- Modify: `docs/superpowers/specs/2026-07-19-sue-dialectic-design-draft.md`
- Test: `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Replaces witness kind `polarity-opposed` with `negation-asymmetric`.
- Keeps every classified item under the unverified witness-candidate contract.
- Documents `proto_justification` as a schema seam, not a completed Reasoning Graph.

- [ ] **Step 1: Write failing witness naming tests**

```python
def test_one_negation_marker_is_only_negation_asymmetry():
    positive = {"FR-001": _interp(assertions=[v3.Assertion(
        given="save", when="complete", then="the file persists", lines=[1]
    )])}
    expanded = {"FR-001": _interp(assertions=[v3.Assertion(
        given="save", when="complete",
        then="the file not only persists but is replicated", lines=[1]
    )])}
    witnesses, _ = v3.find_witnesses([_reader(1, positive), _reader(2, expanded)])
    assert witnesses[0].kind == "negation-asymmetric"
```

- [ ] **Step 2: Run witness test and verify RED**

Run: `pytest -q tests/unit/test_sue_reproducibility.py -k negation_asymmetry`

Expected: FAIL because the current label is `polarity-opposed`.

- [ ] **Step 3: Rename the heuristic and update rendering**

Do not add semantic opposition claims. Preserve the report section title `Divergence witness candidates (heuristic — behavioural verification is v4)`.

- [ ] **Step 4: Correct design status language**

Document:

- provider adapters and Cartesian model × framing matrix;
- evidence overlap as a parallel-reader diagnostic, not retention;
- `proto_justification` as a schema seam only;
- full Justification Graph, inter-round critical-fact retention, and exhibited behavioural witnesses remain gated on dialectic traces.

- [ ] **Step 5: Run the complete SUE suite**

Run:

```bash
pytest -q \
  tests/unit/test_sue_challenge.py \
  tests/unit/test_sue_consensus.py \
  tests/unit/test_sue_reproducibility.py
```

Expected: all tests pass with zero failures.

- [ ] **Step 6: Run static CLI checks**

Run:

```bash
python3 scripts/sue_reproducibility.py --help
python3 -m py_compile scripts/sue_challenge.py scripts/sue_reproducibility.py
git diff --check
```

Expected: help documents `--model-cmd`, compilation exits 0, and `git diff --check` prints nothing.
