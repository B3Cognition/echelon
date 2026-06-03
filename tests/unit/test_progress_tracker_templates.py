from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "build" / "progress-tracker.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "build-6-progress.md"


class TestProgressTrackerTemplates:
    def test_progress_tracker_prompt_uses_canonical_outputs_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert ".specify/..." not in text
        assert "{spec_dir}/progress-report.md" in text
        assert "{spec_dir}/process-metrics.md" in text
        assert "agent: speckit-echelon-progress-tracker (PROGRESS TRACKER)" in text
        assert "agent: PROGRESS_TRACKER" not in text

    def test_progress_phase_uses_canonical_output_paths(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "Append to `{spec_dir}/progress-report.md`" in text
        assert "Update `{spec_dir}/process-metrics.md`" in text
