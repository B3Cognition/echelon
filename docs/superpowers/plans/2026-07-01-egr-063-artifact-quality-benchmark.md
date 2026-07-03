# EGR-063 Artifact Quality Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in benchmark path that measures whether cleansing constitution, tasks, and ADR artifacts improves downstream Echelon build speed and quality.

**Architecture:** Add a small deterministic benchmark module under `src/echelon/` that owns fixture definitions, variant definitions, command planning, result aggregation, and summary writing. Keep workflow changes opt-in by registering experimental `phase-exp-*` nodes in `extension/workflow/definition.yaml` and running them only through `echelon phase run` or the benchmark command. Use existing squad, harness, state, and journal contracts instead of creating a parallel LLM runner.

**Tech Stack:** Python 3.11+, `dataclasses`, `pathlib`, `json`, existing `echelon` CLI dispatch, existing `harness.phase_graph`, pytest, Markdown phase specs.

## Global Constraints

- Default Phase A and harness workflows remain unchanged.
- Artifact cleansing is opt-in and runnable through targeted phase execution.
- Benchmark verdicts are based on build outcomes, not Understanding or Lexicon scores alone.
- Constitution repair must go through CHIEF / `speckit.constitution`; do not directly edit `.specify/memory/constitution.md` in the quality phase.
- Experimental phases must write state only through declared `allowed_state_updates`.
- EGR-063 must remain tracked in `docs/findings/echelon-grounded-review-register.md` and must receive a `CHANGELOG.md` `[Unreleased]` entry before implementation is complete.
- GitHub issue tracking is required for this work.

---

## File Structure

Create these files:

- `src/echelon/benchmark.py`: fixture and variant definitions, command plan generation, summary aggregation, and result writing.
- `tests/unit/test_benchmark.py`: pure unit coverage for variants, command plans, aggregation, and summary file writing.
- `extension/workflow/phases/phase-exp-constitution-quality.md`: constitution artifact-quality phase contract.
- `extension/workflow/phases/phase-exp-tasks-quality.md`: tasks artifact-quality phase contract.
- `extension/workflow/phases/phase-exp-adr-quality.md`: ADR artifact-quality phase contract.

Modify these files:

- `src/echelon/cli.py`: add `echelon benchmark list` and `echelon benchmark run <fixture> --variant <variant> [--dry-run]`.
- `extension/workflow/definition.yaml`: register the three experimental phases with no default-path incoming transition.
- `tests/kernel/test_phase_graph.py`: assert experimental phases are registered and have allowed state updates.
- `tests/unit/test_cli_phase.py`: assert manual phase replay accepts the experimental phases with fake provider responses.
- `docs/findings/echelon-grounded-review-register.md`: keep EGR-063 evidence, issue link, and completion notes current.
- `CHANGELOG.md`: add the EGR-063 completion entry when code lands.

---

### Task 1: EGR and Issue Tracking

**Files:**
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/specs/2026-07-01-artifact-quality-benchmark-design.md`
- Modify: `docs/superpowers/plans/2026-07-01-egr-063-artifact-quality-benchmark.md`

**Interfaces:**
- Consumes: approved design document and GitHub issue `https://github.com/B3Cognition/echelon/issues/85`.
- Produces: EGR-063 tracking entry with design, plan, and GitHub issue evidence.

- [ ] **Step 1: Confirm EGR-063 is registered**

Run:

```bash
rg -n "EGR-063|artifact-quality-benchmark|Artifact Quality Benchmark" docs/findings/echelon-grounded-review-register.md docs/superpowers/specs/2026-07-01-artifact-quality-benchmark-design.md docs/superpowers/plans/2026-07-01-egr-063-artifact-quality-benchmark.md
```

Expected: all three files mention the benchmark work, and the register row has status `in-progress`.

- [ ] **Step 2: Confirm the GitHub issue URL is recorded**

Confirm the EGR-063 register row evidence includes `GitHub issue #85`.

The row should retain this shape:

```markdown
| EGR-063 | P2 | in-progress | Echelon lacks a benchmark-backed way to test whether cleansing non-spec LLM-consumed artifacts improves build speed or quality. | Approved design: `docs/superpowers/specs/2026-07-01-artifact-quality-benchmark-design.md`; implementation plan: `docs/superpowers/plans/2026-07-01-egr-063-artifact-quality-benchmark.md`; GitHub issue #85. Current workflow applies Understanding primarily to `spec.md`; constitution, ADRs, and most planning artifacts enter later LLM context without a comparable opt-in quality benchmark. | Implement an experimental benchmark command and opt-in artifact-quality phases for constitution, tasks, and ADRs; measure real build outcomes before considering default workflow changes. |
```

- [ ] **Step 3: Verify tracking files**

Run:

```bash
rg -n "EGR-063|GitHub issue" docs/findings/echelon-grounded-review-register.md docs/superpowers/plans/2026-07-01-egr-063-artifact-quality-benchmark.md
```

Expected: the register and plan both mention EGR-063; the register includes GitHub issue #85.

- [ ] **Step 4: Commit tracking changes**

Run:

```bash
git add docs/findings/echelon-grounded-review-register.md docs/superpowers/specs/2026-07-01-artifact-quality-benchmark-design.md docs/superpowers/plans/2026-07-01-egr-063-artifact-quality-benchmark.md
git commit -m "docs: track EGR-063 artifact quality benchmark"
```

Expected: commit succeeds.

---

### Task 2: Benchmark Domain Model

**Files:**
- Create: `src/echelon/benchmark.py`
- Create: `tests/unit/test_benchmark.py`

**Interfaces:**
- Consumes: no runtime Echelon state.
- Produces:
  - `BenchmarkFixture`
  - `BenchmarkVariant`
  - `BenchmarkCommandPlan`
  - `BenchmarkRunRecord`
  - `list_fixtures() -> list[BenchmarkFixture]`
  - `list_variants() -> list[BenchmarkVariant]`
  - `plan_variant_commands(fixture_id: str, variant_id: str) -> BenchmarkCommandPlan`
  - `summarize_records(records: list[BenchmarkRunRecord]) -> dict`

- [ ] **Step 1: Write failing tests for fixtures, variants, and command plans**

Add to `tests/unit/test_benchmark.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.benchmark import (
    BenchmarkRunRecord,
    list_fixtures,
    list_variants,
    plan_variant_commands,
    summarize_records,
    write_summary,
)


def test_lists_tiny_notes_fixture() -> None:
    fixtures = {fixture.id: fixture for fixture in list_fixtures()}

    fixture = fixtures["tiny-notes"]

    assert "notes" in fixture.prompt.lower()
    assert "local persistence" in fixture.prompt.lower()
    assert "automated test" in fixture.prompt.lower()


def test_lists_expected_variants() -> None:
    variants = {variant.id: variant for variant in list_variants()}

    assert list(variants) == [
        "baseline",
        "constitution",
        "constitution-tasks",
        "constitution-tasks-adrs",
    ]
    assert variants["constitution-tasks"].phases == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
    )


def test_plans_baseline_without_cleanse_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "baseline")

    assert plan.fixture_id == "tiny-notes"
    assert plan.variant_id == "baseline"
    assert plan.phase_ids == ()
    assert plan.commands[0][:2] == ("echelon", "run")
    assert plan.commands[-1][:3] == ("echelon", "harness", "run")


def test_plans_constitution_tasks_adrs_with_ordered_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "constitution-tasks-adrs")

    assert plan.phase_ids == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
        "phase-exp-adr-quality",
    )
    assert ("echelon", "phase", "run", "phase-exp-constitution-quality") in plan.commands
    assert ("echelon", "phase", "run", "phase-exp-tasks-quality") in plan.commands
    assert ("echelon", "phase", "run", "phase-exp-adr-quality") in plan.commands


def test_unknown_fixture_and_variant_fail_clearly() -> None:
    with pytest.raises(ValueError, match="Unknown benchmark fixture"):
        plan_variant_commands("missing", "baseline")

    with pytest.raises(ValueError, match="Unknown benchmark variant"):
        plan_variant_commands("tiny-notes", "missing")


def test_summarize_records_prefers_build_outcomes() -> None:
    records = [
        BenchmarkRunRecord(
            variant_id="baseline",
            status="complete",
            build_dispatches=8,
            retries=2,
            blocked_states=1,
            verification_failures=2,
            fulfillment_gaps=3,
            elapsed_seconds=600.0,
        ),
        BenchmarkRunRecord(
            variant_id="constitution-tasks",
            status="complete",
            build_dispatches=5,
            retries=0,
            blocked_states=0,
            verification_failures=0,
            fulfillment_gaps=1,
            elapsed_seconds=420.0,
        ),
    ]

    summary = summarize_records(records)

    assert summary["best_variant"] == "constitution-tasks"
    assert summary["variants"]["baseline"]["build_dispatches"] == 8
    assert summary["variants"]["constitution-tasks"]["fulfillment_gaps"] == 1


def test_write_summary_outputs_json_and_markdown(tmp_path: Path) -> None:
    records = [
        BenchmarkRunRecord(
            variant_id="baseline",
            status="complete",
            build_dispatches=8,
            retries=2,
            blocked_states=1,
            verification_failures=2,
            fulfillment_gaps=3,
            elapsed_seconds=600.0,
        )
    ]

    json_path, md_path = write_summary(tmp_path, records)

    assert json.loads(json_path.read_text(encoding="utf-8"))["best_variant"] == "baseline"
    assert "| baseline | complete | 8 | 2 | 1 | 2 | 3 | 600.0 |" in md_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_benchmark.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'echelon.benchmark'`.

- [ ] **Step 3: Implement the benchmark model**

Create `src/echelon/benchmark.py`:

```python
"""Experimental benchmark definitions for EGR-063 artifact-quality evaluation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkFixture:
    id: str
    name: str
    prompt: str


@dataclass(frozen=True)
class BenchmarkVariant:
    id: str
    label: str
    phases: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkCommandPlan:
    fixture_id: str
    variant_id: str
    phase_ids: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class BenchmarkRunRecord:
    variant_id: str
    status: str
    build_dispatches: int = 0
    retries: int = 0
    blocked_states: int = 0
    verification_failures: int = 0
    fulfillment_gaps: int = 0
    elapsed_seconds: float = 0.0
    issue_url: str = ""
    run_id: str = ""
    spec_id: str = ""

    def score_tuple(self) -> tuple[int, int, int, int, int, float]:
        return (
            self.fulfillment_gaps,
            self.verification_failures,
            self.blocked_states,
            self.retries,
            self.build_dispatches,
            self.elapsed_seconds,
        )


_FIXTURES = (
    BenchmarkFixture(
        id="tiny-notes",
        name="Tiny Notes",
        prompt=(
            "Build a tiny notes app. Users can create, list, and delete notes. "
            "Empty note text is rejected with a clear validation message. The app "
            "shows an empty state when there are no notes, persists notes locally "
            "between reloads, supports keyboard use for the primary create/delete "
            "flow, and includes at least one automated test for validation or "
            "persistence."
        ),
    ),
)

_VARIANTS = (
    BenchmarkVariant("baseline", "Baseline", ()),
    BenchmarkVariant("constitution", "Constitution cleanse", ("phase-exp-constitution-quality",)),
    BenchmarkVariant(
        "constitution-tasks",
        "Constitution and tasks cleanse",
        ("phase-exp-constitution-quality", "phase-exp-tasks-quality"),
    ),
    BenchmarkVariant(
        "constitution-tasks-adrs",
        "Constitution, tasks, and ADR cleanse",
        (
            "phase-exp-constitution-quality",
            "phase-exp-tasks-quality",
            "phase-exp-adr-quality",
        ),
    ),
)


def list_fixtures() -> list[BenchmarkFixture]:
    return list(_FIXTURES)


def list_variants() -> list[BenchmarkVariant]:
    return list(_VARIANTS)


def _fixture(fixture_id: str) -> BenchmarkFixture:
    for fixture in _FIXTURES:
        if fixture.id == fixture_id:
            return fixture
    raise ValueError(f"Unknown benchmark fixture: {fixture_id}")


def _variant(variant_id: str) -> BenchmarkVariant:
    for variant in _VARIANTS:
        if variant.id == variant_id:
            return variant
    raise ValueError(f"Unknown benchmark variant: {variant_id}")


def plan_variant_commands(fixture_id: str, variant_id: str) -> BenchmarkCommandPlan:
    fixture = _fixture(fixture_id)
    variant = _variant(variant_id)
    commands: list[tuple[str, ...]] = [("echelon", "run", fixture.prompt)]
    commands.extend(("echelon", "phase", "run", phase_id) for phase_id in variant.phases)
    commands.append(("echelon", "harness", "run", "RESOLVE_SPEC_ID_FROM_CURRENT_RUN"))
    return BenchmarkCommandPlan(
        fixture_id=fixture.id,
        variant_id=variant.id,
        phase_ids=variant.phases,
        commands=tuple(commands),
    )


def summarize_records(records: list[BenchmarkRunRecord]) -> dict:
    if not records:
        return {"best_variant": None, "variants": {}}
    best = min(records, key=lambda record: record.score_tuple())
    return {
        "best_variant": best.variant_id,
        "variants": {
            record.variant_id: asdict(record)
            for record in records
        },
    }


def write_summary(output_dir: Path, records: list[BenchmarkRunRecord]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_records(records)
    json_path = output_dir / "summary.json"
    md_path = output_dir / "summary.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Benchmark Summary",
        "",
        "| Variant | Status | Dispatches | Retries | Blocks | Verify Failures | Fulfillment Gaps | Seconds |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for record in records:
        lines.append(
            f"| {record.variant_id} | {record.status} | {record.build_dispatches} | "
            f"{record.retries} | {record.blocked_states} | {record.verification_failures} | "
            f"{record.fulfillment_gaps} | {record.elapsed_seconds:.1f} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
pytest tests/unit/test_benchmark.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/echelon/benchmark.py tests/unit/test_benchmark.py
git commit -m "feat: add artifact benchmark model"
```

Expected: commit succeeds.

---

### Task 3: Benchmark CLI List and Dry-Run

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_benchmark.py`

**Interfaces:**
- Consumes: `list_fixtures`, `list_variants`, `plan_variant_commands`.
- Produces: `_cmd_benchmark(args: list[str], project_root: Path) -> None` and `echelon benchmark` entrypoint.

- [ ] **Step 1: Add CLI tests**

Append to `tests/unit/test_benchmark.py`:

```python
from echelon.cli import _cmd_benchmark


def test_benchmark_list_prints_fixtures_and_variants(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "tiny-notes" in out
    assert "constitution-tasks-adrs" in out


def test_benchmark_dry_run_prints_commands(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(
        ["run", "tiny-notes", "--variant", "constitution-tasks", "--dry-run"],
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "echelon run" in out
    assert "phase-exp-constitution-quality" in out
    assert "phase-exp-tasks-quality" in out
    assert "echelon harness run RESOLVE_SPEC_ID_FROM_CURRENT_RUN" in out


def test_benchmark_rejects_unknown_variant(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(["run", "tiny-notes", "--variant", "missing"], project_root=tmp_path)

    assert exc.value.code == 1
    assert "Unknown benchmark variant" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_benchmark.py -q
```

Expected: fails because `_cmd_benchmark` is not defined.

- [ ] **Step 3: Add usage text**

In `src/echelon/cli.py`, add this block in `USAGE` near `phase`:

```text
  benchmark list                            List experimental benchmark fixtures and variants.
  benchmark run <fixture> --variant <id> [--dry-run]
                                            Run or print an artifact-quality benchmark variant.
```

- [ ] **Step 4: Add `_cmd_benchmark`**

Add this function near `_cmd_phase` in `src/echelon/cli.py`:

```python
def _cmd_benchmark(args: list[str], project_root: Path) -> None:
    from echelon.benchmark import list_fixtures, list_variants, plan_variant_commands

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  echelon benchmark list\n"
            "  echelon benchmark run <fixture> --variant <id> [--dry-run]",
            flush=True,
        )
        return

    if args[0] == "list":
        _banner(
            "BENCHMARKS",
            [(fixture.id, fixture.name) for fixture in list_fixtures()]
            + [(f"variant:{variant.id}", variant.label) for variant in list_variants()],
            subtitle="Experimental artifact-quality benchmark fixtures and variants",
        )
        return

    if args[0] != "run" or len(args) < 2:
        print("✗ Usage: echelon benchmark run <fixture> --variant <id> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    fixture_id = args[1]
    variant_id = "baseline"
    dry_run = False
    i = 2
    while i < len(args):
        if args[i] == "--variant" and i + 1 < len(args):
            variant_id = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            print(f"✗ Unknown benchmark argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    try:
        plan = plan_variant_commands(fixture_id, variant_id)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        _banner(
            "BENCHMARK DRY RUN",
            [("fixture", plan.fixture_id), ("variant", plan.variant_id)],
            subtitle="Commands that would run",
        )
        for command in plan.commands:
            print(" ".join(command))
        return

    print("✗ Benchmark execution is not implemented yet; use --dry-run.", file=sys.stderr)
    sys.exit(1)
```

- [ ] **Step 5: Wire the entrypoint**

In `main()` in `src/echelon/cli.py`, add before `phase`:

```python
    if command == "benchmark":
        _cmd_benchmark(args[1:], project_root=Path.cwd())
        return
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/unit/test_benchmark.py -q
```

Expected: all benchmark tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/echelon/cli.py tests/unit/test_benchmark.py
git commit -m "feat: add benchmark dry-run CLI"
```

Expected: commit succeeds.

---

### Task 4: Experimental Workflow Phase Registration

**Files:**
- Modify: `extension/workflow/definition.yaml`
- Create: `extension/workflow/phases/phase-exp-constitution-quality.md`
- Create: `extension/workflow/phases/phase-exp-tasks-quality.md`
- Create: `extension/workflow/phases/phase-exp-adr-quality.md`
- Modify: `tests/kernel/test_phase_graph.py`

**Interfaces:**
- Consumes: existing `PhaseGraph`.
- Produces: three `agent` phase nodes runnable by `echelon phase run`.

- [ ] **Step 1: Add phase graph tests**

Append to `tests/kernel/test_phase_graph.py`:

```python
def test_experimental_artifact_quality_phases_are_registered():
    graph = PhaseGraph(DEFINITION, EXT_YML)

    expected = {
        "phase-exp-constitution-quality": {
            "agent": "speckit-echelon-chief",
            "updates": {
                "constitution_quality_pass",
                "constitution_quality_attempts",
                "constitution_quality_findings",
                "blocked_reason",
                "status",
            },
        },
        "phase-exp-tasks-quality": {
            "agent": "speckit-echelon-orchestrator",
            "updates": {
                "tasks_quality_pass",
                "tasks_quality_attempts",
                "tasks_quality_findings",
                "blocked_reason",
                "status",
            },
        },
        "phase-exp-adr-quality": {
            "agent": "speckit-echelon-architect",
            "updates": {
                "adr_quality_pass",
                "adr_quality_attempts",
                "adr_quality_findings",
                "blocked_reason",
                "status",
            },
        },
    }

    for phase_id, contract in expected.items():
        node = graph.get(phase_id)
        assert node.type == "agent"
        assert node.agent == contract["agent"]
        assert set(node.allowed_state_updates or []) == contract["updates"]
        assert node.transitions == [{"to": "done", "condition": "always"}]
```

- [ ] **Step 2: Run phase graph test to verify failure**

Run:

```bash
pytest tests/kernel/test_phase_graph.py::test_experimental_artifact_quality_phases_are_registered -q
```

Expected: fails with `Phase not found in definition.yaml`.

- [ ] **Step 3: Register phases in definition.yaml**

Add these nodes near the end of `extension/workflow/definition.yaml`, before terminal or reopen-only nodes if the file groups phases that way:

```yaml
  # --------------------------------------------------------------------------
  - id: phase-exp-constitution-quality
    label: "Experimental Constitution Quality"
    spec_file: workflow/phases/phase-exp-constitution-quality.md
    type: agent
    agent: speckit-echelon-chief
    tier: experimental
    context_pack:
      - .specify/memory/constitution.md
      - constitution.md
      - spec.md
      - plan.md
      - .specify/squad/reasoning-journal.jsonl
    outputs:
      - constitution-quality-report.md
      - constitution_quality_pass → state.json
    allowed_state_updates:
      - constitution_quality_pass
      - constitution_quality_attempts
      - constitution_quality_findings
      - blocked_reason
      - status
    transitions:
      - to: done
        condition: always

  # --------------------------------------------------------------------------
  - id: phase-exp-tasks-quality
    label: "Experimental Tasks Quality"
    spec_file: workflow/phases/phase-exp-tasks-quality.md
    type: agent
    agent: speckit-echelon-orchestrator
    tier: experimental
    context_pack:
      - spec.md
      - plan.md
      - tasks.md
      - requirements.lexicon.md
      - test-strategy.md
      - .specify/squad/reasoning-journal.jsonl
    outputs:
      - tasks.md
      - tasks-quality-report.md
      - tasks_quality_pass → state.json
    allowed_state_updates:
      - tasks_quality_pass
      - tasks_quality_attempts
      - tasks_quality_findings
      - blocked_reason
      - status
    transitions:
      - to: done
        condition: always

  # --------------------------------------------------------------------------
  - id: phase-exp-adr-quality
    label: "Experimental ADR Quality"
    spec_file: workflow/phases/phase-exp-adr-quality.md
    type: agent
    agent: speckit-echelon-architect
    tier: experimental
    context_pack:
      - plan.md
      - architecture.md
      - adr/ADR-*.md
      - tasks.md
      - .specify/squad/reasoning-journal.jsonl
    outputs:
      - adr-quality-report.md
      - adr_quality_pass → state.json
    allowed_state_updates:
      - adr_quality_pass
      - adr_quality_attempts
      - adr_quality_findings
      - blocked_reason
      - status
    transitions:
      - to: done
        condition: always
```

- [ ] **Step 4: Create phase spec files**

Create `extension/workflow/phases/phase-exp-constitution-quality.md`:

```markdown
# Phase: phase-exp-constitution-quality
# Agent: speckit-echelon-chief (CHIEF)
# Read by: speckit-echelon-commander (COMMANDER) for manual experimental phase runs only

## Purpose

Audit and repair constitution clarity before build benchmarking. This phase is experimental and must never run on the default Phase A path.

## Context Pack

Read `.specify/memory/constitution.md`, published `constitution.md`, `spec.md`, `plan.md` when present, and the reasoning journal.

## Dispatch Prompt

```xml
<instructions>
You are CHIEF. Read agents/control/chief.md for your complete protocol.
Operate in experimental constitution-quality mode for EGR-063.

Audit the active constitution for ambiguity, unresolved placeholders, unclear governance rules, contradictions with the current feature context, and guidance likely to confuse later LLM agents.

ALWAYS use the constitution protocol and `speckit.constitution` for any repair.
NEVER directly edit `.specify/memory/constitution.md` or the published `constitution.md` snapshot with shell redirection, Write, or Edit outside the constitution protocol.

Write `constitution-quality-report.md` in `{spec_dir}/` with findings, attempted repair steps, and final verdict.
Return `echelon_result.state_updates.constitution_quality_pass`, `constitution_quality_attempts`, and `constitution_quality_findings`.
</instructions>
```

## Expected `echelon_result`

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    constitution_quality_pass: true
    constitution_quality_attempts: 1
    constitution_quality_findings: 0
  journal_entries: []
```
```

Create `extension/workflow/phases/phase-exp-tasks-quality.md`:

```markdown
# Phase: phase-exp-tasks-quality
# Agent: speckit-echelon-orchestrator (ORCHESTRATOR)
# Read by: speckit-echelon-commander (COMMANDER) for manual experimental phase runs only

## Purpose

Audit and repair `tasks.md` so build agents receive self-contained, testable, requirement-linked work. This phase is experimental and must never run on the default Phase A path.

## Context Pack

Read `spec.md`, `plan.md`, `tasks.md`, `requirements.lexicon.md` when present, `test-strategy.md` when present, and the reasoning journal.

## Dispatch Prompt

```xml
<instructions>
You are ORCHESTRATOR. Read agents/solution/orchestrator.md for your complete protocol.
Operate in experimental tasks-quality mode for EGR-063.

Audit tasks for missing requirement links, vague implementation instructions, missing test obligations, hidden dependencies, impossible sequencing, and task descriptions that require unstated context.

Run `lexicon validate "{spec_dir}/tasks.md" --type tasks --spec-ref "{spec_dir}/requirements.lexicon.md" --json` when `requirements.lexicon.md` exists. Treat parser or validation failures as quality findings and repair `tasks.md` using the normal ORCHESTRATOR task-authoring protocol.

Preserve existing task IDs when the task intent remains the same. Split tasks only when one task mixes independent work that cannot be implemented and tested together.

Write `tasks-quality-report.md` in `{spec_dir}/` with findings, repairs, and final verdict.
Return `echelon_result.state_updates.tasks_quality_pass`, `tasks_quality_attempts`, and `tasks_quality_findings`.
</instructions>
```

## Expected `echelon_result`

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    tasks_quality_pass: true
    tasks_quality_attempts: 1
    tasks_quality_findings: 0
  journal_entries: []
```
```

Create `extension/workflow/phases/phase-exp-adr-quality.md`:

```markdown
# Phase: phase-exp-adr-quality
# Agent: speckit-echelon-architect (ARCHITECT)
# Read by: speckit-echelon-commander (COMMANDER) for manual experimental phase runs only

## Purpose

Audit and repair ADRs so implementation agents receive coherent decision context. This phase is experimental and must never run on the default Phase A path.

## Context Pack

Read `plan.md`, `architecture.md` when present, `adr/ADR-*.md`, `tasks.md`, and the reasoning journal.

## Dispatch Prompt

```xml
<instructions>
You are ARCHITECT. Read agents/solution/architect.md for your complete protocol.
Operate in experimental ADR-quality mode for EGR-063.

Audit ADRs for unclear decisions, missing status, missing consequences, contradictions between ADRs, drift from `plan.md`, and missing links from important task or architecture choices.

Repair ADRs using the existing ADR style in the spec directory. Do not create ADRs for trivial implementation details.

Write `adr-quality-report.md` in `{spec_dir}/` with findings, repairs, and final verdict.
Return `echelon_result.state_updates.adr_quality_pass`, `adr_quality_attempts`, and `adr_quality_findings`.
</instructions>
```

## Expected `echelon_result`

```yaml
echelon_result:
  verdict: DONE
  state_updates:
    adr_quality_pass: true
    adr_quality_attempts: 1
    adr_quality_findings: 0
  journal_entries: []
```
```

- [ ] **Step 5: Run phase graph tests**

Run:

```bash
pytest tests/kernel/test_phase_graph.py::test_experimental_artifact_quality_phases_are_registered -q
```

Expected: the new test passes.

- [ ] **Step 6: Run workflow validation tests**

Run:

```bash
pytest tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q
```

Expected: both test files pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add extension/workflow/definition.yaml extension/workflow/phases/phase-exp-constitution-quality.md extension/workflow/phases/phase-exp-tasks-quality.md extension/workflow/phases/phase-exp-adr-quality.md tests/kernel/test_phase_graph.py
git commit -m "feat: register experimental artifact quality phases"
```

Expected: commit succeeds.

---

### Task 5: Manual Phase Replay Coverage

**Files:**
- Modify: `tests/unit/test_cli_phase.py`

**Interfaces:**
- Consumes: experimental phase nodes from Task 4.
- Produces: confidence that `echelon phase run` can execute each experimental phase through existing manual replay plumbing.

- [ ] **Step 1: Add fake-provider phase replay test**

Append to `tests/unit/test_cli_phase.py`:

```python
@pytest.mark.parametrize(
    ("phase_id", "state_key", "report_name"),
    [
        ("phase-exp-constitution-quality", "constitution_quality_pass", "constitution-quality-report.md"),
        ("phase-exp-tasks-quality", "tasks_quality_pass", "tasks-quality-report.md"),
        ("phase-exp-adr-quality", "adr_quality_pass", "adr-quality-report.md"),
    ],
)
def test_phase_run_experimental_artifact_quality_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase_id: str,
    state_key: str,
    report_name: str,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (spec_dir / "constitution.md").write_text("# Constitution\n", encoding="utf-8")
    (spec_dir / "adr").mkdir()
    (spec_dir / "adr" / "ADR-001-demo.md").write_text("# ADR-001\n", encoding="utf-8")

    class FakeProvider:
        def __init__(self, _config: object) -> None:
            pass

        def exec_agent(self, project_root: str, _prompt: str, timeout_ms: int | None = None) -> SquadAgentResult:
            target = Path(project_root) / "specs" / "001-demo" / report_name
            target.write_text("# Quality Report\n\nPass.\n", encoding="utf-8")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {
                        state_key: True,
                        state_key.replace("_pass", "_attempts"): 1,
                        state_key.replace("_pass", "_findings"): 0,
                    },
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=10,
                timed_out=False,
            )

    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", FakeProvider)

    _cmd_phase(["run", phase_id, "--spec", "001"], project_root=tmp_path, ext_dir=EXT_DIR)

    current = (tmp_path / "runs" / ".current").read_text(encoding="utf-8").strip()
    state = json.loads((tmp_path / "runs" / current / "state.json").read_text(encoding="utf-8"))
    assert state[state_key] is True
    assert state["last_dispatch"]["manual_phase_run"] is True
    assert (spec_dir / report_name).exists()
```

- [ ] **Step 2: Run test to verify pass**

Run:

```bash
pytest tests/unit/test_cli_phase.py::test_phase_run_experimental_artifact_quality_phases -q
```

Expected: all three parameterized cases pass.

- [ ] **Step 3: Run focused phase tests**

Run:

```bash
pytest tests/unit/test_cli_phase.py tests/kernel/test_phase_graph.py -q
```

Expected: both files pass.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/unit/test_cli_phase.py
git commit -m "test: cover experimental artifact phase replay"
```

Expected: commit succeeds.

---

### Task 6: Benchmark Execution Skeleton and Summary Writing

**Files:**
- Modify: `src/echelon/benchmark.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_benchmark.py`

**Interfaces:**
- Consumes: `BenchmarkCommandPlan`.
- Produces:
  - `run_benchmark_variant(project_root: Path, fixture_id: str, variant_id: str, runner: Callable[[tuple[str, ...]], int] | None = None) -> Path`
  - real CLI writes `runs/benchmarks/<timestamp>-<fixture>/<variant>/summary.json` and `summary.md`.

- [ ] **Step 1: Add execution skeleton test**

Append to `tests/unit/test_benchmark.py`:

```python
from echelon.benchmark import run_benchmark_variant


def test_run_benchmark_variant_writes_summary_with_injected_runner(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> int:
        commands.append(command)
        return 0

    output_dir = run_benchmark_variant(
        tmp_path,
        "tiny-notes",
        "constitution",
        runner=runner,
        timestamp="20260701-120000",
    )

    assert output_dir == tmp_path / "runs" / "benchmarks" / "20260701-120000-tiny-notes" / "constitution"
    assert commands[0][:2] == ("echelon", "run")
    assert ("echelon", "phase", "run", "phase-exp-constitution-quality") in commands
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "summary.md").exists()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/unit/test_benchmark.py::test_run_benchmark_variant_writes_summary_with_injected_runner -q
```

Expected: fails because `run_benchmark_variant` does not exist.

- [ ] **Step 3: Implement injected-runner execution**

Add to `src/echelon/benchmark.py`:

```python
import subprocess
from datetime import datetime, timezone
from typing import Callable


CommandRunner = Callable[[tuple[str, ...]], int]


def _default_runner(command: tuple[str, ...]) -> int:
    return subprocess.run(command, check=False).returncode


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def run_benchmark_variant(
    project_root: Path,
    fixture_id: str,
    variant_id: str,
    *,
    runner: CommandRunner | None = None,
    timestamp: str | None = None,
) -> Path:
    plan = plan_variant_commands(fixture_id, variant_id)
    run = runner or _default_runner
    output_dir = project_root / "runs" / "benchmarks" / f"{timestamp or _timestamp()}-{fixture_id}" / variant_id
    output_dir.mkdir(parents=True, exist_ok=True)

    status = "complete"
    retries = 0
    for command in plan.commands:
        exit_code = run(command)
        if exit_code != 0:
            status = "failed"
            retries += 1
            break

    record = BenchmarkRunRecord(
        variant_id=variant_id,
        status=status,
        build_dispatches=len(plan.commands),
        retries=retries,
        blocked_states=1 if status == "failed" else 0,
    )
    write_summary(output_dir, [record])
    return output_dir
```

- [ ] **Step 4: Wire non-dry-run CLI execution**

In `_cmd_benchmark`, replace the current non-dry-run error with:

```python
    from echelon.benchmark import run_benchmark_variant

    output_dir = run_benchmark_variant(project_root, fixture_id, variant_id)
    _banner(
        "BENCHMARK COMPLETE",
        [("fixture", fixture_id), ("variant", variant_id), ("output", str(output_dir))],
    )
```

- [ ] **Step 5: Run benchmark tests**

Run:

```bash
pytest tests/unit/test_benchmark.py -q
```

Expected: all benchmark tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/echelon/benchmark.py src/echelon/cli.py tests/unit/test_benchmark.py
git commit -m "feat: add benchmark execution skeleton"
```

Expected: commit succeeds.

---

### Task 7: Documentation and Completion Gate

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`

**Interfaces:**
- Consumes: completed implementation and verification results.
- Produces: operator docs and EGR-063 completion evidence.

- [ ] **Step 1: Add README benchmark command documentation**

In `README.md`, add a short row or paragraph near the terminal CLI command table:

```markdown
| `echelon benchmark list` / `echelon benchmark run <fixture> --variant <id>` | — | Experimental EGR-063 artifact-quality benchmark runner. Variants compare baseline Phase A/build behavior against opt-in constitution, tasks, and ADR cleanse phases. |
```

- [ ] **Step 2: Add changelog entry**

Under `CHANGELOG.md` `[Unreleased]`, add:

```markdown
- EGR-063: Added an experimental artifact-quality benchmark path. `echelon benchmark` can compare baseline builds against opt-in constitution, tasks, and ADR cleanse variants; experimental `phase-exp-*` workflow nodes are manually runnable through `echelon phase run` and are not part of the default workflow.
```

- [ ] **Step 3: Update EGR-063 to fixed**

Replace the EGR-063 current finding row with:

```markdown
| EGR-063 | P2 | fixed | Echelon lacked a benchmark-backed way to test whether cleansing non-spec LLM-consumed artifacts improves build speed or quality. | `src/echelon/benchmark.py`, `src/echelon/cli.py`, `extension/workflow/definition.yaml`, `extension/workflow/phases/phase-exp-constitution-quality.md`, `extension/workflow/phases/phase-exp-tasks-quality.md`, `extension/workflow/phases/phase-exp-adr-quality.md`, `tests/unit/test_benchmark.py`, `tests/unit/test_cli_phase.py`, `tests/kernel/test_phase_graph.py`, GitHub issue: https://github.com/B3Cognition/echelon/issues/85. | Fixed: benchmark fixtures and variants are deterministic, experimental artifact-quality phases are manually runnable, and benchmark summaries compare build outcome metrics without changing the default workflow. |
```

- [ ] **Step 4: Add review log completion note**

Append a review log row:

```markdown
| 2026-07-01 | `codex/artifact-quality-benchmark-design` | EGR-063 implemented experimental artifact-quality benchmarking with constitution, tasks, and ADR cleanse variants. Verification: `pytest tests/unit/test_benchmark.py tests/unit/test_cli_phase.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q` passed. |
```

- [ ] **Step 5: Run final focused verification**

Run:

```bash
pytest tests/unit/test_benchmark.py tests/unit/test_cli_phase.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Run whitespace and tracking checks**

Run:

```bash
git diff --check
rg -n "EGR-063|artifact-quality benchmark|phase-exp-constitution-quality|phase-exp-tasks-quality|phase-exp-adr-quality" CHANGELOG.md README.md docs/findings/echelon-grounded-review-register.md extension/workflow/definition.yaml tests/unit/test_benchmark.py tests/kernel/test_phase_graph.py
```

Expected: `git diff --check` has no output; `rg` finds the EGR and phase references in the expected files.

- [ ] **Step 7: Commit**

Run:

```bash
git add README.md CHANGELOG.md docs/findings/echelon-grounded-review-register.md
git commit -m "docs: complete EGR-063 artifact benchmark"
```

Expected: commit succeeds.

---

## Self-Review Notes

- Spec coverage: benchmark variants, constitution/tasks/ADR phases, metrics, storage, error handling, and rollout are covered by Tasks 2 through 7.
- Tracking coverage: EGR and GitHub issue tracking are covered by Task 1 and the completion gate in Task 7.
- Type consistency: `BenchmarkFixture`, `BenchmarkVariant`, `BenchmarkCommandPlan`, `BenchmarkRunRecord`, `plan_variant_commands`, `summarize_records`, `write_summary`, and `run_benchmark_variant` are introduced before use.
- Scope boundary: benchmark execution starts with an injected-runner skeleton and deterministic summaries. Full extraction of real harness metrics can be added after this lands without changing the phase contracts.
