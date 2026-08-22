from pathlib import Path

from echelon.stack_selection import StackSelection
from harness.stack_contract import build_stack_contract, render_stack_contract
from harness.stacks.schema import StackDefinition
from harness.squad_state import SquadStateStore
from harness.squad_executors import _render_controller_owned_prompt_context
from harness.squad import _human_input_policy_error_code
from harness.human_input import HumanInputPolicyError


def _definition(tmp_path: Path, stack_id: str, *, implies: list[str] | None = None) -> StackDefinition:
    stack_dir = tmp_path / stack_id
    stack_dir.mkdir()
    (stack_dir / "context.md").write_text(
        f"Use {stack_id} guidance.", encoding="utf-8"
    )
    return StackDefinition(
        id=stack_id,
        name=stack_id.title(),
        version="1.2.3",
        kind="framework",
        owner="test",
        description=f"{stack_id} description",
        source_path=stack_dir / "stack.yml",
        applies_to_archetypes=["web"],
        provides={f"ui.{stack_id}": stack_id},
        implies=implies or [],
        requires_commands=["pytest"],
        requires_registries=["registry"],
        tools={},
        context_files=["context.md"],
    )


def test_stack_contract_captures_resolved_semantics_and_guidance(tmp_path: Path) -> None:
    definitions = {
        "web": _definition(tmp_path, "web", implies=["ui"]),
        "ui": _definition(tmp_path, "ui"),
    }
    selection = StackSelection(
        explicit=["web"], effective=["web"], resolved=["ui", "web"], local_override=False
    )

    contract = build_stack_contract(selection, definitions)

    assert contract["schema_version"] == 1
    assert contract["explicit_ids"] == ["web"]
    assert contract["resolved_ids"] == ["ui", "web"]
    assert contract["stacks"][0]["description"] == "ui description"
    assert contract["context_files"][0]["content"] == "Use ui guidance."
    assert len(contract["context_files"][0]["sha256"]) == 64
    rendered = render_stack_contract(contract)
    assert "Selected Stack Contract" in rendered
    assert "Use web guidance." in rendered


def test_initial_state_persists_stack_contract(tmp_path: Path) -> None:
    contract = {"schema_version": 1, "resolved_ids": ["web"]}
    store = SquadStateStore(tmp_path / "run")

    store.initialize(
        run_id="run-1",
        mode="greenfield",
        user_message="hello",
        token_budget=0,
        entry_phase="init",
        stack_contract=contract,
    )

    assert store.load()["stack_contract"] == contract


def test_cli_builds_contract_from_effective_stack_selection(
    tmp_path: Path, monkeypatch
) -> None:
    import echelon.cli as cli

    definitions = {"web": _definition(tmp_path, "web")}
    monkeypatch.setattr(cli, "_load_stack_definitions_for_project", lambda _root: definitions)
    monkeypatch.setattr(
        cli,
        "get_stack_selection",
        lambda _root, _definitions: StackSelection(
            explicit=["web"], effective=["web"], resolved=["web"], local_override=False
        ),
    )

    contract = cli._fresh_stack_contract_or_exit(tmp_path)

    assert contract["resolved_ids"] == ["web"]


def test_provider_context_renders_frozen_stack_and_clarification_receipt(
    tmp_path: Path,
) -> None:
    definitions = {"web": _definition(tmp_path, "web")}
    contract = build_stack_contract(
        StackSelection(
            explicit=["web"], effective=["web"], resolved=["web"], local_override=False
        ),
        definitions,
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "user-clarifications.md").write_text(
        "# Clarification\n\nAnswer: Provide a web page.", encoding="utf-8"
    )

    context = _render_controller_owned_prompt_context(
        {"stack_contract": contract, "staging_dir": str(staging)}
    )

    assert "Selected Stack Contract" in context
    assert "Use web guidance." in context
    assert "Provide a web page." in context


def test_human_input_policy_diagnostic_code_does_not_include_provider_text() -> None:
    code = _human_input_policy_error_code(HumanInputPolicyError("secret provider text"))

    assert code == "human_input_policy_invalid"
    assert "secret" not in code
