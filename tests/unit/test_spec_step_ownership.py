"""Structural ownership guard for the current-only Phase A step protocol."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "src" / "harness"

RETIRED_STATE_NAMES = (
    "pending_controller_completion",
    "pending_external_publication",
    "external_publication_failure",
    "controller_completion_failure",
)

ACTIVE_STATE_OWNERS = (
    "squad.py",
    "squad_state.py",
    "prepared_phase_result.py",
    "state_transaction_namespace.py",
    "discovery_bootstrap_state.py",
)

RETIRED_CONTROLLER_ENTRY_POINTS = (
    "_prepare_controller_completion",
    "_drain_pending_controller_completion",
    "_recover_pending_external_publication",
    "_cleanup_controller_completion_orphans",
    "_record_controller_completion_failure_best_effort",
)

RETIRED_COMPLETION_API = (
    "PreparedControllerCompletion",
    "prepare_controller_completion",
    "load_prepared_controller_completion",
    "advance_controller_completion",
)


def _source(name: str) -> str:
    return (HARNESS / name).read_text(encoding="utf-8")


def _imports(name: str) -> set[str]:
    tree = ast.parse(_source(name), filename=name)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_active_state_owners_have_no_retired_phase_a_keys() -> None:
    violations = {
        name: [token for token in RETIRED_STATE_NAMES if token in _source(name)]
        for name in ACTIVE_STATE_OWNERS
    }
    assert not {name: tokens for name, tokens in violations.items() if tokens}


def test_controller_has_only_the_common_step_recovery_loop() -> None:
    source = _source("squad.py")
    assert not [
        name for name in RETIRED_CONTROLLER_ENTRY_POINTS if name in source
    ]
    assert ".completion-outbox" not in source
    assert "pending_spec_step" in source


def test_state_store_depends_on_spec_steps_not_completion_protocols() -> None:
    imports = _imports("squad_state.py")
    assert "harness.spec_step" in imports
    assert "harness.squad_completion" not in imports
    assert "harness.squad_publication" not in imports


def test_completion_module_has_no_outbox_or_recovery_authority() -> None:
    source = _source("squad_completion.py")
    assert ".completion-outbox" not in source
    assert not [name for name in RETIRED_COMPLETION_API if name in source]


def test_secure_publication_transaction_remains_without_import_cycle() -> None:
    publication = _source("squad_publication.py")
    snapshot = _source("squad_publication_snapshot.py")
    assert "class SquadPublicationTransaction" in publication
    assert ".publication-outbox" in publication
    assert not (
        "harness.squad_publication_snapshot" in _imports("squad_publication.py")
        and "harness.squad_publication" in _imports(
            "squad_publication_snapshot.py"
        )
    )
    for token in RETIRED_STATE_NAMES:
        assert token not in publication
        assert token not in snapshot


def test_controller_shape_run_locked_delegates_to_one_step_loop() -> None:
    tree = ast.parse(_source("squad.py"), filename="squad.py")
    controller = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SquadController"
    )
    methods = {
        node.name: node
        for node in controller.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_run_current_phase_step" in methods
    run_locked = methods["_run_locked"]
    calls = {
        node.func.attr
        for node in ast.walk(run_locked)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_run_current_phase_step" in calls
    assert not calls & {
        "_prepare_external_phase_effects",
        "_advance_prepared_result_or_block",
        "_apply_spec_step_publication",
        "_apply_companion_completion_effect",
    }
    constants = {
        node.value
        for node in ast.walk(run_locked)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not constants & {
        "publication",
        "journal",
        "timing",
        "quality",
        "checkpoint",
        "context",
        "mining",
    }
