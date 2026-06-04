from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "extension" / "agents" / "control" / "checkpoint.md"
PHASE2_DECIDE = ROOT / "extension" / "workflow" / "phases" / "phase2-decide.md"
PHASE1_WHY2 = ROOT / "extension" / "workflow" / "phases" / "phase1-why2.md"
BUILD_INIT = ROOT / "extension" / "workflow" / "phases" / "build-1-init.md"
PHASE3_CONSENSUS = ROOT / "extension" / "workflow" / "phases" / "phase3-consensus.md"
PHASE3_SPECIALISTS = ROOT / "extension" / "workflow" / "phases" / "phase3-specialists.md"
PHASE4_DOCUMENT = ROOT / "extension" / "workflow" / "phases" / "phase4-document.md"
BUILD_VERIFY_GATES = (
    ROOT / "extension" / "workflow" / "phases" / "appendices" / "build-8-verify-gates.md"
)
CODEGEN_SECURITY = ROOT / "extension" / "workflow" / "phases" / "codegen-6b-security.md"


class TestPhaseOutputPaths:
    def test_checkpoint_uses_canonical_internalization_report_path(self) -> None:
        text = CHECKPOINT.read_text(encoding="utf-8")

        assert "specs/{feature}/internalization-report.md" not in text
        assert "{spec_dir}/internalization-report.md" in text

    def test_phase2_decide_uses_canonical_kill_report_path(self) -> None:
        text = PHASE2_DECIDE.read_text(encoding="utf-8")

        assert "specs/{feature}/kill-report.md" not in text
        assert "{spec_dir}/kill-report.md" in text

    def test_build_init_uses_canonical_report_paths(self) -> None:
        text = BUILD_INIT.read_text(encoding="utf-8")

        for filename in [
            "spec-compliance-report.md",
            "code-review-report.md",
            "test-quality-report.md",
            "progress-report.md",
        ]:
            assert f"specs/{{feature}}/{filename}" not in text
            assert f"{{spec_dir}}/{filename}" in text

    def test_phase3_specialists_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE3_SPECIALISTS.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "artifacts from `{spec_dir}/`" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert text.count("Produce outputs in `{spec_dir}/`") == 6

    def test_phase1_why2_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE1_WHY2.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "artifacts in `{spec_dir}/`" in text

    def test_phase3_consensus_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE3_CONSENSUS.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "artifacts in `{spec_dir}/`" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert text.count("Produce outputs in `{spec_dir}/`") == 3

    def test_phase4_document_uses_canonical_context_artifact_path(self) -> None:
        text = PHASE4_DOCUMENT.read_text(encoding="utf-8")

        assert "specs/{feature}/" not in text
        assert "artifacts in `{spec_dir}/`" in text
        assert "expected artifacts exist in `{spec_dir}/`" in text

    def test_license_exception_paths_use_canonical_spec_dir(self) -> None:
        for path in [BUILD_VERIFY_GATES, CODEGEN_SECURITY]:
            text = path.read_text(encoding="utf-8")

            assert "specs/{NNN}-{feature}/license-exceptions.md" not in text
            assert "{spec_dir}/license-exceptions.md" in text
