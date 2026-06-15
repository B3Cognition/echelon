from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_python_unit_ci_job_runs_prompt_reference_contracts() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "pytest tests/unit/ tests/kernel/test_prompt_references.py" in text
