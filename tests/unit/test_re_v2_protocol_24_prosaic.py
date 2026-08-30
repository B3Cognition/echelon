from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader
from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.authorities import validate_installed_authorities
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.protocol_24.artifacts import (
    DEEPENING_IN_PROCESS_ADAPTER_ID,
    DEEPENING_PRODUCER_FAMILY,
    DEEPENING_VERIFIER_ID,
    L2_CONTEXT_PRODUCER_FAMILY,
    L2_EVIDENCE_PRODUCER_FAMILY,
    L2_ROOT_PRODUCER_FAMILY,
    build_deepening_executor_catalog,
)
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture
from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_PATH = REPO_ROOT / "prosaic" / "subagents" / "echelon.re-deepener.md"


def _role_artifact() -> ProsaicCommandArtifact:
    raw = ROLE_PATH.read_text(encoding="utf-8")
    _empty, frontmatter, body = raw.split("---", 2)
    return ProsaicCommandArtifact(
        frontmatter=yaml.safe_load(frontmatter),
        body=body.lstrip("\n"),
    )


@pytest.mark.unit
def test_deepener_role_is_neutral_write_only_prosaic_authority() -> None:
    artifact = _role_artifact()

    assert artifact.frontmatter == {
        "name": "echelon.re-deepener",
        "description": "RE-DEEPENER — authors one bounded selective L2 payload",
        "execution": "agent",
        "tools": "write",
        "color": "orange",
        "model_tier": "strong",
        "effort": "high",
    }
    text = ROLE_PATH.read_text(encoding="utf-8").lower()
    assert all(name not in text for name in ("codex", "claude", "copilot", "opencode"))
    assert "baseline.json" in artifact.body
    assert "never perform filesystem discovery" in artifact.body.lower()
    assert canonical_prosaic_agent_bytes(artifact) == canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(dict(artifact.frontmatter), artifact.body)
    )


@pytest.mark.unit
def test_deepening_executor_reuses_shared_adapter_with_deepener_agent_hash() -> None:
    inherited, _manifest = _input_fixture()
    artifact = _role_artifact()
    agent_bytes = canonical_prosaic_agent_bytes(artifact)
    catalog = build_deepening_executor_catalog(
        inherited.executor_contract,
        content_digest(agent_bytes),
        content_digest(b"deepening implementation"),
    )

    baseline = inherited.executor_contract.entry_for("compact-baseline")
    deepening = catalog.entry_for("compact-deepening")
    assert all(entry in catalog.entries for entry in inherited.executor_contract.entries)
    assert {
        entry.producer_family
        for entry in catalog.entries
        if entry not in inherited.executor_contract.entries
    } == {
        DEEPENING_PRODUCER_FAMILY,
        L2_CONTEXT_PRODUCER_FAMILY,
        L2_EVIDENCE_PRODUCER_FAMILY,
        L2_ROOT_PRODUCER_FAMILY,
    }
    assert deepening == replace(
        baseline,
        producer_family=DEEPENING_PRODUCER_FAMILY,
        verifier=replace(
            baseline.verifier,
            verifier_id=DEEPENING_VERIFIER_ID,
            verifier_version="v1",
            implementation_digest=content_digest(b"deepening implementation"),
        ),
        request_renderer=replace(
            baseline.request_renderer,
            agent_contract_hash=content_digest(agent_bytes),
        ),
    )
    deterministic = tuple(
        catalog.entry_for(family)
        for family in (
            L2_CONTEXT_PRODUCER_FAMILY,
            L2_EVIDENCE_PRODUCER_FAMILY,
            L2_ROOT_PRODUCER_FAMILY,
        )
    )
    assert all(
        entry.adapter_id == DEEPENING_IN_PROCESS_ADAPTER_ID
        and entry.executor_implementation_digest
        == content_digest(b"deepening implementation")
        and entry.verifier == deepening.verifier
        for entry in deterministic
    )
    registry = _registry_from_inputs(inherited)
    registry = replace(
        registry,
        executor_implementations={
            **dict(registry.executor_implementations),
            DEEPENING_IN_PROCESS_ADAPTER_ID: content_digest(
                b"deepening implementation"
            ),
        },
        verifier_implementations={
            **dict(registry.verifier_implementations),
            DEEPENING_VERIFIER_ID: content_digest(b"deepening implementation"),
        },
        agent_contracts={
            **dict(registry.agent_contracts),
            "echelon.re-deepener": content_digest(agent_bytes),
        },
    )
    assert validate_installed_authorities(catalog, registry) == ()


@pytest.mark.unit
def test_installed_loader_uses_normal_subagent_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = tmp_path / ".echelon" / "prosaic" / "subagents"
    installed.mkdir(parents=True)
    installed.joinpath("echelon.re-deepener.md").write_text(
        ROLE_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    artifact = _role_artifact()

    class _Result:
        returncode = 0
        stderr = ""
        stdout = __import__("json").dumps(
            {
                "type": "subagent",
                "frontmatter": artifact.frontmatter,
                "body": artifact.body,
            }
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", lambda *a, **k: _Result())

    loaded = ProsaicPromptLoader(tmp_path).load_subagent("echelon.re-deepener")

    assert loaded is not None
    assert loaded.frontmatter == artifact.frontmatter
