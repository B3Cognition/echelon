from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "prosaic" / "subagents" / "echelon.checkpoint.md"
PHASE2_DECIDE = ROOT / "runtime" / "workflow" / "phases" / "phase2-decide.md"
PHASE1_WHAT = ROOT / "runtime" / "workflow" / "phases" / "phase1-what.md"
PHASE1_WHY2 = ROOT / "runtime" / "workflow" / "phases" / "phase1-why2.md"
PHASE3_CONSENSUS = ROOT / "runtime" / "workflow" / "phases" / "phase3-consensus.md"
PHASE3_SPECIALISTS = ROOT / "runtime" / "workflow" / "phases" / "phase3-specialists.md"
PHASE4_DOCUMENT = ROOT / "runtime" / "workflow" / "phases" / "phase4-document.md"


class TestPhaseOutputPaths:
    def test_checkpoint_uses_canonical_internalization_report_path(self) -> None:
        text = CHECKPOINT.read_text(encoding="utf-8")

        assert "specs/{feature}/internalization-report.md" not in text
        assert "{spec_dir}/internalization-report.md" in text

    def test_phase2_decide_uses_canonical_kill_report_path(self) -> None:
        text = PHASE2_DECIDE.read_text(encoding="utf-8")

        assert "specs/{feature}/kill-report.md" not in text
        assert "specs/{NNN}-{feature}/" not in text
        assert "{spec_dir}/kill-report.md" in text
        for filename in [
            "spec.md",
            "glossary.md",
            "requirements-overview.md",
            "assumptions.md",
            "issues.md",
        ]:
            assert f"{{spec_dir}}/{filename}" in text
        assert "Produce outputs in `{spec_dir}/`" in text

    def test_phase1_what_outputs_requirements_overview_not_final_overview(self) -> None:
        text = PHASE1_WHAT.read_text(encoding="utf-8")

        assert "{spec_dir}/requirements-overview.md` exists" in text
        assert "`00-overview.md` exists" not in text
        assert "Expected Outputs — BOTH REQUIRED" in text
        assert "- `requirements-overview.md`" in text
        assert "- `00-overview.md`" not in text

    def test_phase2_decide_reads_requirements_overview_not_final_overview(self) -> None:
        text = PHASE2_DECIDE.read_text(encoding="utf-8")

        assert "{spec_dir}/requirements-overview.md" in text
        assert "{spec_dir}/00-overview.md" not in text

    def test_phase3_specialists_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE3_SPECIALISTS.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "artifacts from `{spec_dir}/`" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert text.count("Produce outputs in `{spec_dir}/`") == 6

    def test_phase1_why2_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE1_WHY2.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "Produce in `{spec_dir}/`" in text

    def test_phase3_consensus_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE3_CONSENSUS.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "artifacts in `{spec_dir}/`" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert text.count("Produce outputs in `{spec_dir}/`") == 3

    def test_phase4_document_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE4_DOCUMENT.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "specs/{NNN}-{feature}/" not in text
        assert "artifacts in `{spec_dir}/`" in text
        assert "expected artifacts exist in `{spec_dir}/`" in text
        assert text.count("Produce outputs in `{spec_dir}/`") == 2
        assert "writes `calibration-dashboard.md` to `{spec_dir}/`" in text
        assert (
            "Produce `confidence-flags.md` and `calibration-dashboard.md` in `{spec_dir}/`"
            in text
        )
        assert "ARTIFACTS: {count} files in {spec_dir}/" in text

    def test_phase4_document_generates_artifact_index_deterministically(self) -> None:
        text = PHASE4_DOCUMENT.read_text(encoding="utf-8")

        assert "writes\n`ARTIFACTS.md`" in text
        assert "NEVER hand-author `ARTIFACTS.md`" in text

    def test_phase4_finalization_keeps_git_under_python_ownership(self) -> None:
        text = PHASE4_DOCUMENT.read_text(encoding="utf-8")

        assert "Python-owned finalization" in text
        assert "finalize-run.sh" not in text
        assert "git checkout" not in text
        assert "sibling branch from the configured default branch" in text
