from __future__ import annotations

from pathlib import Path

import pytest

from harness.stacks import load_stack_definitions, resolve_stacks
from harness.stacks.errors import StackResolutionError


ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = ROOT / "runtime"


def _definitions():
    return load_stack_definitions(extension_root=EXTENSION_ROOT)


@pytest.mark.unit
def test_loads_bundled_statsperform_stacks() -> None:
    definitions = _definitions()

    assert sorted(definitions) == [
        "statsperform-msa-service",
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]


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
    tool = _definitions()["statsperform-playbook"].tools["playbook_cli"]
    commands = tool.commands

    assert tool.args == [
        "-y",
        "--registry=https://nexus.statsperform.tools/repository/public-npm/",
        "@statsperform/playbook-cli",
    ]
    assert commands["availability"].args == ["--version"]
    assert commands["availability"].gate is True
    assert commands["compliance_scan"].args == ["compliance", "scan"]
    assert commands["compliance_scan"].gate is False


@pytest.mark.unit
def test_playbook_guidance_uses_the_declared_private_registry() -> None:
    context = (
        ROOT / "runtime" / "stacks" / "statsperform-playbook" / "context.md"
    ).read_text(encoding="utf-8")

    assert (
        "npx -y --registry=https://nexus.statsperform.tools/repository/public-npm/ "
        "@statsperform/playbook-cli"
    ) in context


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
