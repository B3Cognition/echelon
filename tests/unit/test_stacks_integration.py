from __future__ import annotations

from pathlib import Path

import pytest

from harness.stacks import load_stack_definitions, resolve_stacks
from harness.stacks.errors import StackResolutionError


ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = ROOT / "runtime"


def _definitions():
    return load_stack_definitions(extension_root=EXTENSION_ROOT)


def _resolve_bundled(*stack_ids: str):
    return resolve_stacks(list(stack_ids), _definitions())


@pytest.mark.unit
def test_runnability_browser_3d_with_persistence_requires_all_service_observations() -> None:
    resolved = _resolve_bundled("browser-3d-game", "game-persistence-postgres")

    assert resolved.runnability.policy == "required"
    assert resolved.runnability.runner == "linux_container"
    assert resolved.runnability.required_observations == (
        "browser_dom",
        "http",
        "postgres_query",
    )
    assert "DATABASE_URL" in resolved.services[0].environment_names


@pytest.mark.unit
def test_runnability_browser_wasm_requires_linux_container_user_journey() -> None:
    resolved = _resolve_bundled("browser-wasm-game")

    assert resolved.runnability.policy == "required"
    assert resolved.runnability.runner == "linux_container"
    assert "browser_dom" in resolved.runnability.required_observations


@pytest.mark.unit
def test_runnability_ios_records_future_macos_runner_without_required_policy() -> None:
    resolved = _resolve_bundled("ios-ar-game")

    assert resolved.runnability.runner == "macos_simulator"
    assert resolved.runnability.policy == "advisory"


@pytest.mark.unit
def test_loads_bundled_stack_catalog() -> None:
    definitions = _definitions()

    assert sorted(definitions) == [
        "browser-3d-game",
        "browser-wasm-game",
        "game-persistence-postgres",
        "ios-ar-game",
        "statsperform-msa-service",
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]


@pytest.mark.unit
def test_resolves_browser_3d_game_with_shared_persistence() -> None:
    resolved = resolve_stacks(
        ["game-persistence-postgres", "browser-3d-game"],
        _definitions(),
        target_archetypes={"browser_3d_game"},
    )

    assert resolved.resolved_ids == [
        "game-persistence-postgres",
        "browser-3d-game",
    ]
    assert resolved.capabilities["data.database"].value == "postgres"
    assert resolved.capabilities["web_app.rendering"].value == "react-three-fiber"
    assert resolved.capabilities["x.game.client_runtime"].value == "browser-3d"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("stack_id", "archetype", "runtime"),
    [
        ("ios-ar-game", "ios_ar_game", "ios-ar"),
        ("browser-wasm-game", "browser_wasm_game", "browser-wasm"),
    ],
)
def test_resolves_game_client_with_shared_persistence(
    stack_id: str, archetype: str, runtime: str
) -> None:
    resolved = resolve_stacks(
        ["game-persistence-postgres", stack_id],
        _definitions(),
        target_archetypes={archetype},
    )

    assert resolved.capabilities["data.database"].value == "postgres"
    assert resolved.capabilities["x.game.client_runtime"].value == runtime


@pytest.mark.unit
def test_rejects_two_game_client_archetypes() -> None:
    with pytest.raises(StackResolutionError, match="x.game.client_runtime"):
        resolve_stacks(
            ["browser-3d-game", "browser-wasm-game"],
            _definitions(),
            target_archetypes={"browser_3d_game", "browser_wasm_game"},
        )


@pytest.mark.unit
def test_bundled_statsperform_stacks_include_detection_hints() -> None:
    definitions = _definitions()

    assert "playbook" in definitions["statsperform-playbook"].detection.positive.technologies
    assert (
        "@statsperform/react-playbook"
        in definitions["statsperform-playbook"].detection.positive.dependencies
    )
    assert "nextjs" in definitions["statsperform-stark-webapp"].detection.modernization.technologies
    assert "fastapi" in definitions["statsperform-msa-service"].detection.positive.technologies


@pytest.mark.unit
def test_playbook_preflight_probe_checks_cli_availability_without_source_tree() -> None:
    commands = _definitions()["statsperform-playbook"].tools["playbook_cli"].commands

    assert commands["availability"].args == ["--version"]
    assert commands["availability"].gate is True
    assert commands["compliance_scan"].args == ["compliance", "scan"]
    assert commands["compliance_scan"].gate is False


@pytest.mark.unit
def test_stark_resolves_playbook_dependency_first() -> None:
    resolved = resolve_stacks(
        ["statsperform-stark-webapp"],
        _definitions(),
        target_archetypes={"web_app"},
    )

    assert resolved.resolved_ids == [
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]
    assert resolved.implied_by == {"statsperform-playbook": "statsperform-stark-webapp"}
    assert resolved.capabilities["ui.components"].value == "playbook"
    assert resolved.capabilities["web_app.framework"].value == "nextjs"


@pytest.mark.unit
def test_msa_resolves_without_web_or_infra_capabilities() -> None:
    resolved = resolve_stacks(
        ["statsperform-msa-service"],
        _definitions(),
        target_archetypes={"service"},
    )

    assert resolved.resolved_ids == ["statsperform-msa-service"]
    assert "statsperform-playbook" not in resolved.resolved_ids
    assert "statsperform-stark-webapp" not in resolved.resolved_ids
    assert resolved.capabilities["service.framework"].value == "fastapi"
    assert not any(key.startswith("ui.") for key in resolved.capabilities)
    assert not any(key.startswith("web_app.") for key in resolved.capabilities)
    assert not any(key.startswith("data.") for key in resolved.capabilities)
    assert not any(key.startswith("messaging.") for key in resolved.capabilities)
    assert not any(key.startswith("stream.") for key in resolved.capabilities)


@pytest.mark.unit
def test_playbook_resolves_without_stark() -> None:
    resolved = resolve_stacks(
        ["statsperform-playbook"],
        _definitions(),
        target_archetypes={"web_app"},
    )

    assert resolved.resolved_ids == ["statsperform-playbook"]
    assert "statsperform-stark-webapp" not in resolved.resolved_ids
    assert resolved.capabilities["ui.components"].value == "playbook"
    assert "web_app.framework" not in resolved.capabilities


@pytest.mark.unit
def test_rejects_msa_for_web_app_target() -> None:
    with pytest.raises(StackResolutionError, match="statsperform-msa-service"):
        resolve_stacks(
            ["statsperform-msa-service"],
            _definitions(),
            target_archetypes={"web_app"},
        )


@pytest.mark.unit
def test_rejects_stark_for_service_target() -> None:
    with pytest.raises(StackResolutionError, match="statsperform-playbook|statsperform-stark-webapp"):
        resolve_stacks(
            ["statsperform-stark-webapp"],
            _definitions(),
            target_archetypes={"service"},
        )
