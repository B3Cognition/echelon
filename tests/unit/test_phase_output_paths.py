from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "extension" / "agents" / "control" / "checkpoint.md"
PHASE2_DECIDE = ROOT / "extension" / "workflow" / "phases" / "phase2-decide.md"
PHASE1_WHY2 = ROOT / "extension" / "workflow" / "phases" / "phase1-why2.md"
BUILD_INIT = ROOT / "extension" / "workflow" / "phases" / "build-1-init.md"
BUILD_FINALIZE = ROOT / "extension" / "workflow" / "phases" / "build-8-finalize.md"
BUILD_COMMAND = ROOT / "extension" / "commands" / "echelon.build.md"
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
        assert "specs/{NNN}-{feature}/" not in text
        assert "{spec_dir}/kill-report.md" in text
        for filename in [
            "spec.md",
            "glossary.md",
            "00-overview.md",
            "assumptions.md",
            "issues.md",
        ]:
            assert f"{{spec_dir}}/{filename}" in text
        assert "Produce outputs in `{spec_dir}/`" in text

    def test_build_init_uses_canonical_report_paths(self) -> None:
        text = BUILD_INIT.read_text(encoding="utf-8")

        assert "Read and verify these files exist in `specs/{NNN}-{feature}/`" not in text
        assert "Read and verify these files exist in `{spec_dir}/`" in text

        for filename in [
            "spec-compliance-report.md",
            "code-review-report.md",
            "test-quality-report.md",
            "progress-report.md",
        ]:
            assert f"specs/{{feature}}/{filename}" not in text
            assert f"{{spec_dir}}/{filename}" in text

    def test_build_init_warns_harness_not_to_stop_on_next_phase(self) -> None:
        text = BUILD_INIT.read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        assert "Do not return `next_phase: build-2-implement` and stop" in text
        assert "Ralph does not consume `next_phase`" in text
        assert "one bounded verified progress slice" in normalized
        assert "Ralph owns verification, commit, and the next build invocation" in normalized
        assert ".harness-build-status.json" in text

    def test_harness_status_contract_treats_done_as_iteration_completion(self) -> None:
        finalize_text = BUILD_FINALIZE.read_text(encoding="utf-8")
        command_text = BUILD_COMMAND.read_text(encoding="utf-8")
        command_normalized = " ".join(command_text.split())

        assert "useful verified progress" in finalize_text
        assert "current bounded progress slice completed cleanly" in finalize_text
        assert '"status":"done"' in finalize_text
        assert '"status":"impasse"' not in finalize_text
        assert "Do not write `impasse` for ordinary partial progress" in finalize_text

        assert "one bounded verified progress slice" in command_normalized
        assert "iteration completion, not total MVP completion" in command_text
        assert '"completed_task_ids":["T-001"]' in command_text
        assert "Ralph marks those rows DONE in `tasks.md` before verify" in command_text
        assert "Ralph owns the outer loop" in command_normalized
        assert "Do not keep selecting more tasks after writing the marker" in command_normalized
        assert 'Harness `{"status":"done"}` still means' in command_text

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

        assert "echelon artifacts" in text
        assert "NEVER hand-author `ARTIFACTS.md`" in text

    def test_build_finalize_generates_artifact_index_deterministically(self) -> None:
        text = (
            ROOT / "extension" / "workflow" / "phases" / "build-8-finalize.md"
        ).read_text(encoding="utf-8")

        assert "echelon artifacts" in text
        assert "NEVER hand-author `ARTIFACTS.md`" in text

    def test_license_exception_paths_use_canonical_spec_dir(self) -> None:
        for path in [BUILD_VERIFY_GATES, CODEGEN_SECURITY]:
            text = path.read_text(encoding="utf-8")

            assert "specs/{NNN}-{feature}/license-exceptions.md" not in text
            assert "{spec_dir}/license-exceptions.md" in text
