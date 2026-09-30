"""Controlled semantic review of retained browser images."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness import visual_evidence


def _case(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    worktree = project / "candidate"
    worktree.mkdir()
    (worktree / "app.ts").write_text("export const ready = true;\n", encoding="utf-8")
    spec = project / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("The pitch is green under a cloudy sky.\n", encoding="utf-8")
    (spec / "tasks.md").write_text("- [x] T-001 Render a pitch.\n", encoding="utf-8")
    screenshot = tmp_path / "journey.png"
    screenshot.write_bytes(b"image-content")
    from harness.product_inventory import product_evidence_fingerprint

    fingerprint = product_evidence_fingerprint(worktree)
    visual = visual_evidence.write_visual_receipt(
        evidence_dir=project / "runs" / "build-1" / "evidence" / "visual",
        spec_id="001", build_id="build-1", candidate_commit="abc123",
        candidate_fingerprint=fingerprint, screenshot_dir="test-results",
        playwright={"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        artifact_paths=[screenshot], required_artifacts=True, attempt_sequence=1,
    )
    image = json.loads(visual.path.read_text(encoding="utf-8"))["artifacts"][0]["path"]
    return project, spec, worktree, visual, image, fingerprint


def test_semantic_validator_reads_retained_images_and_seals_pass(tmp_path, monkeypatch):
    """A model PASS becomes authoritative only after exact input binding."""
    from harness import semantic_visual_validator as semantic
    from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader

    project, spec, worktree, visual, image, fingerprint = _case(tmp_path)
    monkeypatch.setattr(
        ProsaicPromptLoader, "load_subagent",
        lambda self, name: ProsaicCommandArtifact(
            frontmatter={"model_tier": "strong", "effort": "high"},
            body="Inspect every retained image against the published spec.",
        ) if name == "echelon.delivery-visual-validator" else None,
    )

    class Executor:
        supports_read_only_review = True

        def run_agent_result(self, cwd, prompt, *, request_metadata):
            assert cwd == str(worktree)
            metadata = request_metadata["prompt_metadata"]
            assert metadata["tool_write_scope_exclusive"] is True
            assert str(visual.path.parent) in metadata["tool_read_roots"]
            assert str(spec) in metadata["tool_read_roots"]
            assignment = json.loads(prompt.split("## Controller assignment\n", 1)[1].split("\n##", 1)[0])
            assert image in prompt
            return SimpleNamespace(
                exit_code=0, timed_out=False, token_usage=17, stderr="",
                stdout=json.dumps({
                    **assignment, "verdict": "PASS", "summary": "Pitch and sky match",
                    "findings": [], "reviewed_artifacts": [image],
                }),
            )

    run = getattr(semantic, "run_semantic_visual_validation", None)
    assert callable(run)
    result = run(
        executor=Executor(), project_dir=project, spec_dir=spec,
        worktree=worktree, visual_ref=visual,
    )

    assert result["status"] == "passed"
    assert result["tokens_used"] == 17
    assert visual_evidence.validate_semantic_visual_receipt(
        result["receipt"], visual_ref=visual,
        candidate_fingerprint=fingerprint,
        spec_digest=semantic.semantic_spec_digest(spec),
    ).valid


def test_semantic_validator_rejects_uninspected_pass(tmp_path, monkeypatch):
    """An image filename in the prompt is not a completed visual inspection."""
    from harness import semantic_visual_validator as semantic
    from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader

    project, spec, worktree, visual, _, _ = _case(tmp_path)
    monkeypatch.setattr(
        ProsaicPromptLoader, "load_subagent",
        lambda self, name: ProsaicCommandArtifact(
            frontmatter={"model_tier": "strong", "effort": "high"}, body="Inspect images.",
        ),
    )

    class Executor:
        supports_read_only_review = True

        def run_agent_result(self, cwd, prompt, *, request_metadata):
            assignment = json.loads(prompt.split("## Controller assignment\n", 1)[1].split("\n##", 1)[0])
            return SimpleNamespace(
                exit_code=0, timed_out=False, token_usage=9, stderr="",
                stdout=json.dumps({
                    **assignment, "verdict": "PASS", "summary": "Looks fine",
                    "findings": [], "reviewed_artifacts": [],
                }),
            )

    result = semantic.run_semantic_visual_validation(
        executor=Executor(), project_dir=project, spec_dir=spec,
        worktree=worktree, visual_ref=visual,
    )

    assert result["status"] == "blocked"
    assert "artifact coverage" in result["reason"]
    assert not list(visual.path.parent.glob("semantic-*.json"))


def test_semantic_validator_blocks_provider_candidate_mutation(tmp_path, monkeypatch):
    """Read-only review may not turn a changed candidate into a passing receipt."""
    from harness import semantic_visual_validator as semantic
    from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader

    project, spec, worktree, visual, image, _ = _case(tmp_path)
    monkeypatch.setattr(
        ProsaicPromptLoader, "load_subagent",
        lambda self, name: ProsaicCommandArtifact(
            frontmatter={"model_tier": "strong", "effort": "high"}, body="Inspect images.",
        ),
    )

    class Executor:
        supports_read_only_review = True

        def run_agent_result(self, cwd, prompt, *, request_metadata):
            (worktree / "app.ts").write_text("export const changed = true;\n", encoding="utf-8")
            assignment = json.loads(prompt.split("## Controller assignment\n", 1)[1].split("\n##", 1)[0])
            return SimpleNamespace(
                exit_code=0, timed_out=False, token_usage=9, stderr="",
                stdout=json.dumps({
                    **assignment, "verdict": "PASS", "summary": "Looks fine",
                    "findings": [], "reviewed_artifacts": [image],
                }),
            )

    result = semantic.run_semantic_visual_validation(
        executor=Executor(), project_dir=project, spec_dir=spec,
        worktree=worktree, visual_ref=visual,
    )

    assert result["status"] == "blocked"
    assert "inputs changed" in result["reason"]
    assert not list(visual.path.parent.glob("semantic-*.json"))


def test_spec_lifecycle_status_does_not_invalidate_visual_requirements(tmp_path):
    """Finalization's frontmatter update must not reopen an unchanged visual review."""
    from harness.semantic_visual_validator import semantic_spec_digest

    spec = tmp_path / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(
        "---\nstatus: in_progress\n---\n# Green pitch under clouds\n",
        encoding="utf-8",
    )
    (spec / "tasks.md").write_text("- [x] T-001 Render pitch\n", encoding="utf-8")
    before = semantic_spec_digest(spec)
    (spec / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Green pitch under clouds\n",
        encoding="utf-8",
    )

    assert semantic_spec_digest(spec) == before
    (spec / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Blue pitch under clouds\n",
        encoding="utf-8",
    )
    assert semantic_spec_digest(spec) != before
