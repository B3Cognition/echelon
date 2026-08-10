from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
APPENDIX_DIR = ROOT / "prosaic" / "agents" / "learning" / "appendices"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.internalizer.md"
PHASE = ROOT / "runtime" / "workflow" / "phases" / "phase4-document.md"


class TestInternalizerTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "internalizer-output-formats.md",
                [
                    "## Agent Scores Proposal Payload Format",
                    "## Internalization Log Proposal Fields",
                    "## Agent Internalization Health Dashboard Section",
                    "## Cross-Validation Flags Summary",
                ],
            ),
            (
                "internalizer-tier-definitions.md",
                [
                    "| Tier | Description | Absorption Threshold | Accuracy Threshold |",
                    "**Deep**",
                    "**Moderate**",
                    "**Minimal**",
                    "**Exempt**",
                ],
            ),
        ],
    )
    def test_appendices_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (APPENDIX_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_internalizer_prompt_references_appendices_and_canonical_outputs(
        self,
    ) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agents/learning/appendices/internalizer-output-formats.md" in text
        assert "agents/learning/appendices/internalizer-tier-definitions.md" in text
        assert ".specify/specs/" not in text
        assert "{spec_dir}/internalization-metrics.md" in text
        assert "knowledge-base/internalization-log.yaml" in text
        assert "knowledge-base/agent-scores.yaml" in text
        assert "knowledge-base/evolution-signals.yaml" in text
        assert "internalization-observation-proposal-template.yaml" in text
        assert "${SQUAD_DIR}/kb-proposals/" in text
        assert "kb-write.sh" not in text
        assert "agent: echelon-internalizer (INTERNALIZER)" in text
        assert "agent: INTERNALIZE_METRICS" not in text
        assert "downstream_agent: SPEC_GUARD" not in text
        assert "downstream_agent: CODE_REVIEWER" not in text
        assert "downstream_agent: TEST_GUARDIAN" not in text

    def test_finalize_mentions_internalizer_appendices(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "agents/learning/appendices/internalizer-output-formats.md" in text
        assert "agents/learning/appendices/internalizer-tier-definitions.md" in text
