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
            "shows an empty state when there are no notes, provides local persistence "
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
        "variants": {record.variant_id: asdict(record) for record in records},
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
