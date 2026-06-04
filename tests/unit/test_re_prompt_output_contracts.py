from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RE_SPECIFIER = ROOT / "extension" / "agents" / "re" / "specifier.md"
RE_EXTRACT_2_SPECIFY = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-2-specify.md"
)
RE_PLANNER = ROOT / "extension" / "agents" / "re" / "planner.md"
RE_PLANNING_1_PLAN = (
    ROOT / "extension" / "workflow" / "phases" / "re-planning-1-plan.md"
)
RE_TASKER = ROOT / "extension" / "agents" / "re" / "tasker.md"
RE_PLANNING_2_TASKS = (
    ROOT / "extension" / "workflow" / "phases" / "re-planning-2-tasks.md"
)
RE_CHECKLISTER = ROOT / "extension" / "agents" / "re" / "checklister.md"
RE_EXTRACT_6_CHECKLIST = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-6-checklist.md"
)


class TestRePromptOutputContracts:
    def test_re_specifier_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_SPECIFIER, RE_EXTRACT_2_SPECIFY]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/spec.md" not in text
            assert "specs/NNN-re-{domain}/spec.md" in text

    def test_re_planner_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_PLANNER, RE_PLANNING_1_PLAN]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/plan.md" not in text
            assert "specs/002-re-api/plan.md" not in text
            assert "specs/NNN-re-{domain}/plan.md" in text

    def test_re_tasker_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_TASKER, RE_PLANNING_2_TASKS]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/tasks.md" not in text
            assert "specs/002-re-api/tasks.md" not in text
            assert "specs/NNN-re-{domain}/tasks.md" in text

    def test_re_checklister_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_CHECKLISTER, RE_EXTRACT_6_CHECKLIST]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/checklist.md" not in text
            assert "specs/000-re-overview/checklist.md" in text
            assert "specs/NNN-re-{domain}/checklist.md" in text
