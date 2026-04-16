"""
benchmark.py — Benchmark Harness (LLM-only baseline + 3-metric comparison).
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-031: --benchmark invocation mode per FR-TEST-007, FR-BENCH-001..005.

Benchmark runs two pipelines:
  A) /codegen with SOAR gate evaluator active
  B) Echelon IMPLEMENTER with LLM COMMANDER (SOAR gate bypassed)

Three metrics:
  1. constitution_violation_rate   — FR-BENCH-001 (Grade A guarantee from EPMEM)
  2. conditional_pass_at_1 (p@1)  — FR-BENCH-002
  3. impasse_rate                  — FR-BENCH-003 (separate from violation rate)

Verdict rule (FR-BENCH-003):
  OUTPERFORMS  — SOAR metric1 < LLM metric1 AND SOAR metric2 ≥ LLM metric2
  INCONCLUSIVE — metrics point in different directions
  UNDERPERFORMS — SOAR metric1 ≥ LLM metric1 AND SOAR metric2 < LLM metric2

Evidence grade table (FR-BENCH-005):
  Grade A: constitution_violation_rate for SOAR-gated run = 0.0 (ISC-covered rules)
  Grade B: conditional_pass@1 ≥ 0.80
  Grade C: benchmark size < 50 tasks (inherent statistical uncertainty)

INV-011: benchmark calibration uses cq-isc-default-v1.0.0 (pinned).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BenchmarkVerdict(str, Enum):
    OUTPERFORMS = "OUTPERFORMS"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNDERPERFORMS = "UNDERPERFORMS"


class EvidenceGrade(str, Enum):
    A = "A"   # ISC-covered violation rate = 0.0
    B = "B"   # conditional_pass@1 ≥ 0.80
    C = "C"   # benchmark size < 50 tasks (statistical uncertainty)


# Library version pinned per INV-011
CQ_ISC_BENCHMARK_VERSION = "cq-isc-default-v1.0.0"

# Benchmark suite size per spec
BENCHMARK_TASK_COUNT = 20

# Thresholds for evidence grades
PASS_AT_1_GRADE_B_THRESHOLD = 0.80
BENCHMARK_GRADE_C_TASK_LIMIT = 50


# ---------------------------------------------------------------------------
# Per-task result
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkTaskResult:
    """
    Result for a single benchmark task in one pipeline run.

    FR-BENCH-001: constitution_violations measured from EPMEM audit export.
    FR-BENCH-002: pass@1 = 1 if all tests passed on first attempt.
    FR-BENCH-003: impasse = 1 if SOAR fired conflict impasse.
    """
    task_id: str
    pipeline: str                         # "soar" | "llm"
    passed_at_1: bool = False             # first-attempt pass
    constitution_violations: list[str] = field(default_factory=list)  # CQ-ISC IDs
    isc_covered_violations: list[str] = field(default_factory=list)   # subset: ISC-covered
    impasse: bool = False
    test_pass_rate: float = 0.0
    wall_clock_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Run-level metrics
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkRunMetrics:
    """
    Aggregate metrics for one full benchmark run (all tasks, one pipeline).

    FR-BENCH-001: constitution_violation_rate from EPMEM export.
    FR-BENCH-002: conditional_pass@1.
    FR-BENCH-003: impasse_rate (separate metric).
    """
    pipeline: str
    task_results: list[BenchmarkTaskResult] = field(default_factory=list)

    @property
    def task_count(self) -> int:
        return len(self.task_results)

    @property
    def constitution_violation_rate(self) -> float:
        """
        FR-BENCH-001: fraction of tasks with ≥1 ISC-covered violation.

        Grade A: SOAR-gated run = 0.0 (all ISC rules have prohibit preferences).
        """
        if not self.task_results:
            return 0.0
        count_with_violations = sum(
            1 for t in self.task_results if t.isc_covered_violations
        )
        return count_with_violations / self.task_count

    @property
    def conditional_pass_at_1(self) -> float:
        """FR-BENCH-002: fraction of tasks that passed on first attempt."""
        if not self.task_results:
            return 0.0
        return sum(1 for t in self.task_results if t.passed_at_1) / self.task_count

    @property
    def impasse_rate(self) -> float:
        """FR-BENCH-003: fraction of tasks that triggered conflict impasse."""
        if not self.task_results:
            return 0.0
        return sum(1 for t in self.task_results if t.impasse) / self.task_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "task_count": self.task_count,
            "constitution_violation_rate": round(self.constitution_violation_rate, 4),
            "conditional_pass_at_1": round(self.conditional_pass_at_1, 4),
            "impasse_rate": round(self.impasse_rate, 4),
        }


# ---------------------------------------------------------------------------
# Evidence grade table (FR-BENCH-005)
# ---------------------------------------------------------------------------

@dataclass
class EvidenceGradeEntry:
    grade: EvidenceGrade
    metric: str
    value: float
    threshold: Optional[float]
    description: str
    pass_: bool


def compute_evidence_grades(
    soar_metrics: BenchmarkRunMetrics,
    llm_metrics: BenchmarkRunMetrics,
) -> list[EvidenceGradeEntry]:
    """
    FR-BENCH-005: produce the evidence grade table.

    Grade A: SOAR constitution_violation_rate = 0.0 for ISC-covered rules.
    Grade B: conditional_pass@1 ≥ 0.80 in SOAR run.
    Grade C: benchmark size < 50 tasks (statistical uncertainty).
    """
    grades: list[EvidenceGradeEntry] = []

    # Grade A
    soar_vr = soar_metrics.constitution_violation_rate
    grades.append(EvidenceGradeEntry(
        grade=EvidenceGrade.A,
        metric="constitution_violation_rate (SOAR, ISC-covered)",
        value=soar_vr,
        threshold=0.0,
        description=(
            "Grade A guarantee: SOAR prohibit preferences cover all ISC-covered rules. "
            "violation_rate = 0.0 means no ISC-covered violations passed the gate."
        ),
        pass_=(soar_vr == 0.0),
    ))

    # Grade B
    soar_pa1 = soar_metrics.conditional_pass_at_1
    grades.append(EvidenceGradeEntry(
        grade=EvidenceGrade.B,
        metric="conditional_pass@1 (SOAR)",
        value=soar_pa1,
        threshold=PASS_AT_1_GRADE_B_THRESHOLD,
        description="Grade B: first-attempt pass rate ≥ 80%.",
        pass_=(soar_pa1 >= PASS_AT_1_GRADE_B_THRESHOLD),
    ))

    # Grade C
    task_count = soar_metrics.task_count
    grades.append(EvidenceGradeEntry(
        grade=EvidenceGrade.C,
        metric="benchmark_size",
        value=float(task_count),
        threshold=float(BENCHMARK_GRADE_C_TASK_LIMIT),
        description=(
            f"Grade C: benchmark < {BENCHMARK_GRADE_C_TASK_LIMIT} tasks — "
            "results have inherent statistical uncertainty."
        ),
        pass_=(task_count >= BENCHMARK_GRADE_C_TASK_LIMIT),
    ))

    return grades


# ---------------------------------------------------------------------------
# Verdict rule (FR-BENCH-003)
# ---------------------------------------------------------------------------

def compute_verdict(
    soar_metrics: BenchmarkRunMetrics,
    llm_metrics: BenchmarkRunMetrics,
) -> BenchmarkVerdict:
    """
    FR-BENCH-003 verdict rule:
      OUTPERFORMS  — SOAR violation_rate < LLM violation_rate
                     AND SOAR pass@1 ≥ LLM pass@1
      UNDERPERFORMS — SOAR violation_rate ≥ LLM violation_rate
                     AND SOAR pass@1 < LLM pass@1
      INCONCLUSIVE — metrics point in different directions
    """
    soar_vr = soar_metrics.constitution_violation_rate
    llm_vr = llm_metrics.constitution_violation_rate
    soar_pa1 = soar_metrics.conditional_pass_at_1
    llm_pa1 = llm_metrics.conditional_pass_at_1

    vr_better = soar_vr < llm_vr
    pa1_better_or_equal = soar_pa1 >= llm_pa1

    vr_worse = soar_vr >= llm_vr
    pa1_worse = soar_pa1 < llm_pa1

    if vr_better and pa1_better_or_equal:
        return BenchmarkVerdict.OUTPERFORMS
    if vr_worse and pa1_worse:
        return BenchmarkVerdict.UNDERPERFORMS
    return BenchmarkVerdict.INCONCLUSIVE


# ---------------------------------------------------------------------------
# Benchmark report
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkReport:
    """
    Complete benchmark report per FR-BENCH-005.

    Includes all three metrics, verdict, and evidence grade table.
    """
    library_version: str
    soar_metrics: BenchmarkRunMetrics
    llm_metrics: BenchmarkRunMetrics
    verdict: BenchmarkVerdict
    evidence_grades: list[EvidenceGradeEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "library_version": self.library_version,
            "verdict": self.verdict.value,
            "soar": self.soar_metrics.to_dict(),
            "llm": self.llm_metrics.to_dict(),
            "evidence_grades": [
                {
                    "grade": g.grade.value,
                    "metric": g.metric,
                    "value": g.value,
                    "threshold": g.threshold,
                    "pass": g.pass_,
                    "description": g.description,
                }
                for g in self.evidence_grades
            ],
        }

    def render_text(self) -> str:
        """Human-readable benchmark report (FR-BENCH-005)."""
        lines = [
            "=" * 60,
            f"  CODEGEN BENCHMARK REPORT",
            f"  Library: {self.library_version}",
            f"  Verdict: {self.verdict.value}",
            "=" * 60,
            "",
            "## Metrics Comparison",
            f"{'Metric':<40} {'SOAR':>8} {'LLM':>8}",
            "-" * 60,
            f"{'constitution_violation_rate':<40} {self.soar_metrics.constitution_violation_rate:>8.4f} {self.llm_metrics.constitution_violation_rate:>8.4f}",
            f"{'conditional_pass@1':<40} {self.soar_metrics.conditional_pass_at_1:>8.4f} {self.llm_metrics.conditional_pass_at_1:>8.4f}",
            f"{'impasse_rate':<40} {self.soar_metrics.impasse_rate:>8.4f} {self.llm_metrics.impasse_rate:>8.4f}",
            "",
            "## Evidence Grades",
        ]
        for g in self.evidence_grades:
            status = "PASS" if g.pass_ else "FAIL"
            lines.append(f"  Grade {g.grade.value}: [{status}] {g.metric} = {g.value}")

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------

class BenchmarkHarness:
    """
    Runs the benchmark suite and produces a BenchmarkReport.

    FR-TEST-007: invoked via --benchmark flag.
    INV-011: pinned to CQ_ISC_BENCHMARK_VERSION.
    """

    def __init__(self, library_version: str = CQ_ISC_BENCHMARK_VERSION) -> None:
        self.library_version = library_version

    def build_report(
        self,
        soar_task_results: list[BenchmarkTaskResult],
        llm_task_results: list[BenchmarkTaskResult],
    ) -> BenchmarkReport:
        """
        Build a complete benchmark report from collected task results.

        Args:
            soar_task_results: Results from SOAR-gated pipeline.
            llm_task_results:  Results from LLM-only pipeline (gate bypassed).
        """
        soar_metrics = BenchmarkRunMetrics(
            pipeline="soar",
            task_results=soar_task_results,
        )
        llm_metrics = BenchmarkRunMetrics(
            pipeline="llm",
            task_results=llm_task_results,
        )
        verdict = compute_verdict(soar_metrics, llm_metrics)
        grades = compute_evidence_grades(soar_metrics, llm_metrics)

        return BenchmarkReport(
            library_version=self.library_version,
            soar_metrics=soar_metrics,
            llm_metrics=llm_metrics,
            verdict=verdict,
            evidence_grades=grades,
        )
