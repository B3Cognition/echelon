"""Tests for loading neutral Prosaic command artifacts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader
from harness.prompt_companions import append_prompt_companions


@pytest.mark.unit
def test_load_command_inspects_the_project_prosaic_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    (source / "commands").mkdir(parents=True)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.bugfix.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.bugfix"},
                    "body": "Fix {{args}}.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path, executable="prosaic").load_command(
        "echelon.bugfix"
    )

    assert artifact is not None
    assert artifact.frontmatter == {"name": "echelon.bugfix"}
    assert artifact.body == "Fix {{args}}."
    assert captured == {
        "command": [
            "prosaic",
            "inspect",
            "commands/echelon.bugfix.md",
            "--source",
            str(source),
        ],
        "cwd": str(tmp_path),
    }


@pytest.mark.unit
def test_load_command_returns_none_without_a_project_prosaic_bundle(tmp_path: Path) -> None:
    assert ProsaicPromptLoader(tmp_path).load_command("echelon.bugfix") is None


@pytest.mark.unit
def test_load_command_returns_none_for_an_agent_only_prosaic_bundle(tmp_path: Path) -> None:
    (tmp_path / ".echelon" / "prosaic" / "subagents").mkdir(parents=True)

    assert ProsaicPromptLoader(tmp_path).load_command("echelon.bugfix") is None


@pytest.mark.unit
def test_load_subagent_inspects_the_project_prosaic_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    (source / "subagents").mkdir(parents=True)

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "subagents/echelon.summarizer.md",
                    "type": "subagent",
                    "frontmatter": {
                        "name": "echelon.summarizer",
                        "model_tier": "fast",
                        "effort": "low",
                        "tools": "write",
                    },
                    "body": "Summarize the run for a human.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_subagent("echelon.summarizer")

    assert artifact is not None
    assert artifact.body == "Summarize the run for a human."
    assert artifact.frontmatter["model_tier"] == "fast"


@pytest.mark.unit
def test_deployed_summarizer_uses_the_id_only_selection_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "prosaic/subagents/echelon.summarizer.md").read_text(
        encoding="utf-8"
    )
    assert "selected_fact_ids" in text
    assert '"bullets"' not in text
    assert "model_tier: fast" in text
    assert "effort: low" in text
    assert "tools: write" in text


@pytest.mark.unit
def test_load_command_inlines_referenced_companion_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    companion = source / "commands" / "appendices" / "shared.md"
    companion.parent.mkdir(parents=True)
    companion.write_text("# Shared protocol\n\nCOMPANION_SENTINEL\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.demo.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.demo"},
                    "body": "Load `commands/appendices/shared.md` before acting.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_command("echelon.demo")

    assert artifact is not None
    assert "COMPANION_SENTINEL" in artifact.body
    assert artifact.body.count("COMPANION_SENTINEL") == 1
    assert "commands/appendices/shared.md" not in artifact.body
    assert "# Embedded Resource 1" in artifact.body


@pytest.mark.unit
def test_load_command_inlines_runtime_template_and_schema_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    runtime = tmp_path / ".echelon" / "runtime"
    (source / "commands").mkdir(parents=True)
    templates = runtime / "templates"
    templates.mkdir(parents=True)
    (templates / "tasks-template.md").write_text(
        "TASK_TEMPLATE_SENTINEL\n",
        encoding="utf-8",
    )
    (templates / "task-contract.schema.json").write_text(
        '{"title": "TASK_SCHEMA_SENTINEL"}\n',
        encoding="utf-8",
    )

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.demo.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.demo"},
                    "body": (
                        "Use `.echelon/runtime/templates/tasks-template.md` and "
                        "`templates/task-contract.schema.json`."
                    ),
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_command("echelon.demo")

    assert artifact is not None
    assert "TASK_TEMPLATE_SENTINEL" in artifact.body
    assert "TASK_SCHEMA_SENTINEL" in artifact.body
    assert ".echelon/runtime/templates" not in artifact.body
    assert "templates/task-contract.schema.json" not in artifact.body
    assert "Use Embedded Resource 1 and Embedded Resource 2." in artifact.body


@pytest.mark.unit
def test_prompt_resource_labels_preserve_template_identity(tmp_path: Path) -> None:
    prosaic = tmp_path / "prosaic"
    runtime = tmp_path / "runtime"
    (prosaic / "subagents").mkdir(parents=True)
    (runtime / "templates").mkdir(parents=True)
    (runtime / "templates" / "tasks-template.md").write_text(
        "TASKS_SENTINEL\n",
        encoding="utf-8",
    )
    (runtime / "templates" / "dependencies-template.md").write_text(
        "DEPENDENCIES_SENTINEL\n",
        encoding="utf-8",
    )
    body = (
        "Use `.echelon/runtime/templates/tasks-template.md` for tasks. "
        "Use `.echelon/runtime/templates/dependencies-template.md` for dependencies. "
        "Read product `contracts/api.json` as evidence."
    )

    rendered = append_prompt_companions(body, (prosaic, runtime))

    assert "Use Embedded Resource 1 for tasks." in rendered
    assert "Use Embedded Resource 2 for dependencies." in rendered
    assert "# Embedded Resource 1\n\nTASKS_SENTINEL" in rendered
    assert "# Embedded Resource 2\n\nDEPENDENCIES_SENTINEL" in rendered
    assert "contracts/api.json" in rendered
    assert ".echelon/runtime/templates" not in rendered


@pytest.mark.unit
def test_orchestrator_prompt_embeds_every_planning_template() -> None:
    repository = Path(__file__).parents[2]
    prosaic = repository / "prosaic"
    runtime = repository / "runtime"
    orchestrator = (
        prosaic / "subagents" / "echelon.orchestrator.md"
    ).read_text(encoding="utf-8")
    template_names = (
        "tasks-template.md",
        "task-entry-fragment.md",
        "task-checkpoint-fragment.md",
        "critical-path-template.md",
        "planning-risk-matrix-template.md",
        "dependencies-template.md",
    )

    rendered = append_prompt_companions(orchestrator, (prosaic, runtime))

    assert rendered.count("# Embedded Resource ") == len(template_names)
    for template_name in template_names:
        template_path = runtime / "templates" / template_name
        assert template_path.read_text(encoding="utf-8").strip() in rendered
        assert f".echelon/runtime/templates/{template_name}" not in rendered


@pytest.mark.unit
def test_prompt_resource_embedding_honors_negative_read_instructions(
    tmp_path: Path,
) -> None:
    prosaic = tmp_path / "prosaic"
    runtime = tmp_path / "runtime"
    forbidden = prosaic / "subagents" / "echelon.commander.md"
    required = runtime / "templates" / "tasks-template.md"
    forbidden.parent.mkdir(parents=True)
    required.parent.mkdir(parents=True)
    forbidden.write_text("COMMANDER_MUST_NOT_LEAK\n", encoding="utf-8")
    required.write_text("TASKS_MUST_BE_EMBEDDED\n", encoding="utf-8")
    body = (
        "Do not read `subagents/echelon.commander.md`.\n"
        "Read `.echelon/runtime/templates/tasks-template.md`."
    )

    rendered = append_prompt_companions(body, (prosaic, runtime))

    assert "COMMANDER_MUST_NOT_LEAK" not in rendered
    assert "subagents/echelon.commander.md" in rendered
    assert "TASKS_MUST_BE_EMBEDDED" in rendered


@pytest.mark.unit
def test_prompt_resource_embedding_does_not_inline_workflow_registry(
    tmp_path: Path,
) -> None:
    prosaic = tmp_path / "prosaic"
    runtime = tmp_path / "runtime"
    registry = runtime / "workflow" / "definition.yaml"
    (prosaic / "commands").mkdir(parents=True)
    registry.parent.mkdir(parents=True)
    registry.write_text("WORKFLOW_REGISTRY_MUST_NOT_LEAK\n", encoding="utf-8")

    rendered = append_prompt_companions(
        "See `workflow/definition.yaml` for controller-owned routing.",
        (prosaic, runtime),
    )

    assert "WORKFLOW_REGISTRY_MUST_NOT_LEAK" not in rendered
    assert "workflow/definition.yaml" in rendered


@pytest.mark.unit
def test_load_command_sanitizes_recursive_companion_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    appendix = source / "agents" / "appendix.md"
    nested = tmp_path / ".echelon" / "runtime" / "workflow" / "nested.md"
    (source / "commands").mkdir(parents=True)
    appendix.parent.mkdir(parents=True)
    nested.parent.mkdir(parents=True)
    appendix.write_text(
        "Read `workflow/nested.md` and apply APPENDIX_SENTINEL.\n",
        encoding="utf-8",
    )
    nested.write_text("NESTED_SENTINEL\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.demo.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.demo"},
                    "body": "Load `agents/appendix.md` before acting.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_command("echelon.demo")

    assert artifact is not None
    assert "APPENDIX_SENTINEL" in artifact.body
    assert "NESTED_SENTINEL" in artifact.body
    assert "agents/appendix.md" not in artifact.body
    assert "workflow/nested.md" not in artifact.body


@pytest.mark.unit
def test_load_command_rejects_unresolved_companion_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    (source / "commands").mkdir(parents=True)

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.demo.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.demo"},
                    "body": "Load `agents/missing.md` before acting.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="unresolved prompt companion"):
        ProsaicPromptLoader(tmp_path).load_command("echelon.demo")


@pytest.mark.unit
def test_render_command_substitutes_neutral_arguments() -> None:
    prompt = ProsaicPromptLoader.render_command(
        ProsaicCommandArtifact(frontmatter={}, body="Fix {{args}}."),
        "the regression",
    ).prompt

    assert "Fix the regression." in prompt
    assert prompt.startswith("You were dispatched as a subagent")


@pytest.mark.unit
def test_render_command_preserves_artifact_metadata() -> None:
    artifact = ProsaicCommandArtifact(
        frontmatter={"model_tier": "balanced", "effort": "high", "color": "blue"},
        body="Fix {{args}}.",
    )

    rendered = ProsaicPromptLoader.render_command(artifact, "the regression")

    assert "Fix the regression." in rendered.prompt
    assert rendered.frontmatter == artifact.frontmatter
