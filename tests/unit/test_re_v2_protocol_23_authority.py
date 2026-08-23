from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_23.authority import (
    ProsaicAgentAuthorityV1,
    Protocol23AuthorityError,
    load_re_agent_authorities,
)


def _artifact() -> ProsaicCommandArtifact:
    return ProsaicCommandArtifact(
        frontmatter={
            "name": "echelon.re-baseliner",
            "description": "RE-BASELINER — authors one bounded compact baseline payload",
            "execution": "agent",
            "tools": "write",
            "color": "orange",
            "model_tier": "strong",
            "effort": "high",
        },
        body="# Baseliner\n\nUse only supplied context.\n",
    )


@pytest.mark.unit
def test_authority_separates_and_hashes_body_and_frontmatter() -> None:
    authority = ProsaicAgentAuthorityV1.from_artifact(
        "echelon.re-baseliner", _artifact()
    )

    assert authority.body_bytes == _artifact().body.encode("utf-8")
    assert authority.body_hash == content_digest(authority.body_bytes)
    assert authority.frontmatter_hash == content_digest(
        canonical_json_bytes(_artifact().frontmatter)
    )
    assert authority.to_json_dict()["frontmatter"] == _artifact().frontmatter
    assert authority.artifact_id == content_digest(authority.to_json_dict())


@pytest.mark.unit
def test_authority_frontmatter_is_immutable() -> None:
    authority = ProsaicAgentAuthorityV1.from_artifact(
        "echelon.re-baseliner", _artifact()
    )

    with pytest.raises(TypeError):
        authority.frontmatter["effort"] = "low"  # type: ignore[index]
    with pytest.raises(Protocol23AuthorityError, match="frontmatter"):
        replace(authority, frontmatter={"name": "echelon.re-baseliner"})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("name", "another-agent"),
        ("execution", "command"),
        ("tools", "none"),
        ("model_tier", "standard"),
        ("effort", "low"),
    ),
)
def test_authority_rejects_wrong_neutral_metadata(field: str, value: str) -> None:
    artifact = _artifact()
    artifact.frontmatter[field] = value

    with pytest.raises(Protocol23AuthorityError, match=field):
        ProsaicAgentAuthorityV1.from_artifact("echelon.re-baseliner", artifact)


class _LoaderSpy:
    def __init__(self, artifact: ProsaicCommandArtifact | None) -> None:
        self.artifact = artifact
        self.calls: list[str] = []

    def load_subagent(self, agent_id: str) -> ProsaicCommandArtifact | None:
        self.calls.append(agent_id)
        return self.artifact


@pytest.mark.unit
def test_inventory_loads_no_prosaic_authority(tmp_path: Path) -> None:
    loader = _LoaderSpy(None)

    authorities = load_re_agent_authorities(
        tmp_path, goal="inventory", loader=loader  # type: ignore[arg-type]
    )

    assert dict(authorities) == {}
    assert loader.calls == []


@pytest.mark.unit
def test_baseline_loads_exactly_the_baseliner(tmp_path: Path) -> None:
    loader = _LoaderSpy(_artifact())

    authorities = load_re_agent_authorities(
        tmp_path, goal="baseline", loader=loader  # type: ignore[arg-type]
    )

    assert loader.calls == ["echelon.re-baseliner"]
    assert tuple(authorities) == ("echelon.re-baseliner",)
    assert authorities["echelon.re-baseliner"].frontmatter["effort"] == "high"
    with pytest.raises(TypeError):
        authorities["another"] = authorities["echelon.re-baseliner"]  # type: ignore[index]


@pytest.mark.unit
def test_baseline_fails_closed_when_installed_agent_is_missing(
    tmp_path: Path,
) -> None:
    loader = _LoaderSpy(None)

    with pytest.raises(
        Protocol23AuthorityError,
        match="workspace migrate-to-prosaic",
    ):
        load_re_agent_authorities(
            tmp_path, goal="baseline", loader=loader  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_authority_loader_rejects_unknown_goal(tmp_path: Path) -> None:
    with pytest.raises(Protocol23AuthorityError, match="goal"):
        load_re_agent_authorities(tmp_path, goal="audit")
