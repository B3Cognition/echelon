from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "prosaic" / "subagents" / "echelon.progress-tracker.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "build-6-progress.md"


class TestProgressTrackerTemplates:
    def test_progress_tracker_prompt_uses_canonical_outputs_and_agent_label(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert ".specify/..." not in text
        assert "{spec_dir}/progress-report.md" in text
        assert "{spec_dir}/process-metrics.md" in text
        assert "agent: echelon-progress-tracker (PROGRESS TRACKER)" in text
        assert "agent: PROGRESS_TRACKER" not in text

    def test_retained_progress_tracker_does_not_restore_legacy_delivery_routing(self) -> None:
        workflow = yaml.safe_load((ROOT / "runtime/workflow/definition.yaml").read_text())
        assert "build-6-progress" not in {phase["id"] for phase in workflow["phases"]}
        assert not PHASE.exists()
