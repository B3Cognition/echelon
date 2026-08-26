from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_DIR = REPO_ROOT / "prosaic" / "subagents"
VALIDATOR_PATH = ROLE_DIR / "echelon.re-validator.md"
RESOLVER_PATH = ROLE_DIR / "echelon.re-resolver.md"
V2_MARKER = "\n## RE v2 Protocol 2.5 Modes\n"
VALIDATOR_V1_SHA256 = "b1979611da2d1d9c33b89ad63daf84754d3b8eec6b802c44a5b409b9ca45a912"


def _role(path: Path) -> ProsaicCommandArtifact:
    raw = path.read_text(encoding="utf-8")
    _empty, frontmatter, body = raw.split("---", 2)
    return ProsaicCommandArtifact(
        frontmatter=yaml.safe_load(frontmatter),
        body=body.lstrip("\n"),
    )


def test_validator_v1_contract_is_byte_identical_before_v2_section() -> None:
    raw = VALIDATOR_PATH.read_text(encoding="utf-8")
    prefix, marker, _v2 = raw.partition(V2_MARKER)

    assert marker == V2_MARKER
    assert hashlib.sha256(prefix.encode("utf-8")).hexdigest() == VALIDATOR_V1_SHA256


@pytest.mark.parametrize(
    ("path", "name", "description"),
    (
        (
            VALIDATOR_PATH,
            "echelon.re-validator",
            "RE-VALIDATOR — quality-checks specs and auto-resolves ambiguities from code",
        ),
        (
            RESOLVER_PATH,
            "echelon.re-resolver",
            "RE-RESOLVER — authors one bounded semantic resolution overlay",
        ),
    ),
)
def test_semantic_roles_are_provider_neutral_write_only_prosaic_authority(
    path: Path,
    name: str,
    description: str,
) -> None:
    artifact = _role(path)

    assert artifact.frontmatter == {
        "name": name,
        "description": description,
        "execution": "agent",
        "tools": "write",
        "color": "orange",
        "model_tier": "strong",
        "effort": "high",
    }
    lowered = path.read_text(encoding="utf-8").lower()
    assert all(name not in lowered for name in ("codex", "claude", "copilot", "opencode"))
    assert canonical_prosaic_agent_bytes(artifact) == canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(dict(artifact.frontmatter), artifact.body)
    )


def test_validator_v2_modes_and_outputs_are_closed() -> None:
    _prefix, _marker, v2 = VALIDATOR_PATH.read_text(encoding="utf-8").partition(V2_MARKER)

    assert "AUDIT_EPOCH_TARGET" in v2
    assert "CLOSURE_RECHECK" in v2
    assert "assessment_kind" in v2
    assert "`target`" in v2
    assert "`source-composition`" in v2
    assert "audit.json" in v2
    assert "closure.json" in v2
    assert "exactly one" in v2.lower()
    assert "never discover or read the live source workspace" in v2.lower()
    assert "never add a finding" in v2.lower()


def test_resolver_writes_only_resolution_candidate_from_frozen_authority() -> None:
    body = _role(RESOLVER_PATH).body
    lowered = body.lower()

    assert "resolution.json" in body
    assert "exactly one" in lowered
    assert "unresolved frozen finding" in lowered
    assert "never discover or read the live source workspace" in lowered
    assert "never edit or replace an l0, l1, or l2 artifact" in lowered
    assert "never write receipts, routing, counters" in lowered


def test_installed_semantic_roles_load_through_normal_prosaic_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = tmp_path / ".echelon" / "prosaic" / "subagents"
    installed.mkdir(parents=True)
    for source in (VALIDATOR_PATH, RESOLVER_PATH):
        installed.joinpath(source.name).write_text(
            source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    def inspect(command: list[str], **_kwargs):  # type: ignore[no-untyped-def]
        path = installed / Path(command[2]).name
        artifact = _role(path)

        class _Result:
            returncode = 0
            stderr = ""
            stdout = json.dumps(
                {
                    "type": "subagent",
                    "frontmatter": artifact.frontmatter,
                    "body": artifact.body,
                }
            )

        return _Result()

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    loader = ProsaicPromptLoader(tmp_path)

    for agent_id in ("echelon.re-validator", "echelon.re-resolver"):
        artifact = loader.load_subagent(agent_id)
        assert artifact is not None
        assert artifact.frontmatter["model_tier"] == "strong"
        assert artifact.frontmatter["effort"] == "high"
        assert not ({"provider", "model", "adapter"} & set(artifact.frontmatter))
