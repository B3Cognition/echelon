from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
APPENDIX_DIR = ROOT / "prosaic" / "agents" / "control" / "appendices"
AGENT = ROOT / "prosaic" / "subagents" / "echelon.scorekeeper.md"
BUILD_FINALIZE = ROOT / "runtime" / "workflow" / "phases" / "build-8-finalize.md"
PHASE4_DOCUMENT = ROOT / "runtime" / "workflow" / "phases" / "phase4-document.md"


class TestScorekeeperTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "scorekeeper-output-template.md",
                [
                    "# Agent Scorecard",
                    "## Leaderboard",
                    "## Peer Appreciation",
                    "## Token Efficiency",
                    "## Internalization Trend",
                ],
            ),
            (
                "scorekeeper-scoring-reference.md",
                [
                    "# Scorekeeper Scoring Reference",
                    "## Performance Points",
                    "## Peer Appreciation Points",
                    "## Token Efficiency Points",
                    "## Internalization Trend Points",
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

    def test_scorekeeper_prompt_references_templates_and_canonical_outputs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agents/control/appendices/scorekeeper-output-template.md" in text
        assert "agents/control/appendices/scorekeeper-scoring-reference.md" in text
        assert ".specify/..." not in text
        assert ".specify/specs/{feature}" not in text
        assert "squad-scorecard.md" not in text
        assert "{spec_dir}/agent-scorecard.md" in text
        assert "knowledge-base/agent-scores.yaml" in text
        assert "agent: echelon-scorekeeper (SCOREKEEPER)" in text
        assert "agent: SCORE" not in text

    def test_build_finalize_dispatch_includes_scorekeeper_templates(self) -> None:
        text = BUILD_FINALIZE.read_text(encoding="utf-8")

        assert "agents/control/appendices/scorekeeper-output-template.md" in text
        assert "agents/control/appendices/scorekeeper-scoring-reference.md" in text
        assert "using the provided template" in text

    def test_phase4_document_mentions_scorekeeper_templates(self) -> None:
        text = PHASE4_DOCUMENT.read_text(encoding="utf-8")

        assert "agents/control/appendices/scorekeeper-output-template.md" in text
        assert "agents/control/appendices/scorekeeper-scoring-reference.md" in text
