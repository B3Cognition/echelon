from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "extension" / "templates"
AGENT = ROOT / "extension" / "agents" / "solution" / "orchestrator.md"
PHASE = ROOT / "extension" / "workflow" / "phases" / "phase3-plan.md"


class TestOrchestratorTemplates:
    @pytest.mark.parametrize(
        ("filename", "anchors"),
        [
            (
                "critical-path-template.md",
                [
                    "## Minimum Timeline",
                    "## Critical Path",
                    "| Task | Effort | Dependents | Why Bottleneck |",
                    "## Float Analysis",
                ],
            ),
            (
                "planning-risk-matrix-template.md",
                [
                    "## High-Risk Tasks",
                    "| Task | Probability | Impact | Score | Mitigation |",
                    "## Systemic Risks",
                    "## Risk Summary",
                ],
            ),
            (
                "dependencies-template.md",
                [
                    "## Dependency Graph",
                    "## Parallel Execution Lanes",
                    "| Task | Dependency | Status | Risk |",
                    "## Circular Dependency Check",
                ],
            ),
        ],
    )
    def test_templates_exist_with_required_anchors(
        self, filename: str, anchors: list[str]
    ) -> None:
        text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

        for anchor in anchors:
            assert anchor in text

    def test_orchestrator_prompt_references_all_templates(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        for filename in [
            "tasks-template.md",
            "task-entry-fragment.md",
            "task-checkpoint-fragment.md",
            "critical-path-template.md",
            "planning-risk-matrix-template.md",
            "dependencies-template.md",
        ]:
            assert f"extension/templates/{filename}" in text

        assert ".specify/..." not in text
        assert (
            "  output_files:\n"
            "    - {spec_dir}/tasks.md\n"
            "    - {spec_dir}/critical-path.md\n"
            "  state_updates: {}\n"
            "  journal_entries:\n"
            in text
        )
        assert "agent: speckit-echelon-orchestrator (ORCHESTRATOR)" in text
        assert "agent: PLAN" not in text
        assert "sources/<source-id>/" in text
        assert "exactly one declared IMPLEMENTATION_TARGET" in text
        assert "NEVER infer a target from RE artifacts or file paths" in text

    def test_phase3_plan_dispatch_includes_templates(self) -> None:
        text = PHASE.read_text(encoding="utf-8")

        assert "extension/templates/tasks-template.md" in text
        assert "extension/templates/task-entry-fragment.md" in text
        assert "extension/templates/task-checkpoint-fragment.md" in text
        assert "extension/templates/critical-path-template.md" in text
        assert "extension/templates/planning-risk-matrix-template.md" in text
        assert "extension/templates/dependencies-template.md" in text
        assert "Produce outputs in `specs/{NNN}-{feature}/`" not in text
        assert "Produce outputs in `{spec_dir}/`" in text
        assert "files in `specs/{NNN}-{feature}/`" not in text
        assert "files in `{spec_dir}/`" in text
        assert 'python -m harness validate-task-targets "{spec_dir}"' in text
        assert "It never\nwrites `targets.yml`" in text
