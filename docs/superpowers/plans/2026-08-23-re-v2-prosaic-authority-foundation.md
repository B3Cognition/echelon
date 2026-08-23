# RE v2 Prosaic Authority Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a closed, immutable, goal-aware Prosaic agent authority that L1 requires and L0 never loads, without changing protocol-2.2 authority bytes.

**Architecture:** Add a small protocol-2.3 authority module without wiring a new runtime protocol yet. It consumes the existing `ProsaicPromptLoader`, validates the neutral baseliner frontmatter, hashes the separated body and metadata canonically, and returns no authority at all for deterministic inventory work. This increment deliberately leaves protocol-2.2 execution and artifact schemas unchanged.

**Tech Stack:** Python 3.11 dataclasses and immutable mappings, existing RE v2 canonical JSON/digest helpers, Prosaic inspection through `ProsaicPromptLoader`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-re-v2-provider-neutral-execution-design.md`

## Global Constraints

- Every RE model invocation must ultimately be a pinned Prosaic agent invocation dispatched through Echelon's shared AI coding provider path.
- L0 remains deterministic and must not inspect Prosaic, construct a provider, or acquire provider/model budget.
- L1 authority is `echelon.re-baseliner` with `execution: agent`, `tools: write`, `model_tier: strong`, and `effort: high`.
- Prosaic frontmatter is the sole model-intent authority; this increment adds no provider, concrete-model, credential, or transport configuration.
- Protocol 2.2 remains byte-compatible and is not modified by this foundation increment; specifically, do not edit the baseliner source that protocol 2.2 currently hashes as raw bytes.
- Preserve the unrelated dirty workspace-snapshot changes in `src/harness/re_v2/snapshot.py` and `tests/unit/test_re_v2_workspace_snapshot.py`.

## File Structure

- Create `src/harness/re_v2/protocol_23/__init__.py`: export the protocol-2.3 authority surface only.
- Create `src/harness/re_v2/protocol_23/authority.py`: own neutral frontmatter validation, canonical authority hashing, and goal-aware Prosaic loading.
- Create `tests/unit/test_re_v2_protocol_23_authority.py`: prove closed schema, immutability, canonical hashes, L0 zero-inspection, and L1 fail-closed inspection.

---

### Task 1: Add the immutable protocol-2.3 Prosaic authority value

**Files:**

- Create: `src/harness/re_v2/protocol_23/__init__.py`
- Create: `src/harness/re_v2/protocol_23/authority.py`
- Create: `tests/unit/test_re_v2_protocol_23_authority.py`

**Interfaces:**

- Consumes: `ProsaicCommandArtifact(frontmatter: dict[str, Any], body: str)`.
- Produces: `ProsaicAgentAuthorityV1.from_artifact(agent_id: str, artifact: ProsaicCommandArtifact) -> ProsaicAgentAuthorityV1`.
- Produces properties: `body_bytes: bytes`, `body_hash: str`, `frontmatter_hash: str`, `inspection_receipt_hash: str`, and `artifact_id: str`.
- Produces: `to_json_dict() -> dict[str, object]` with the exact closed authority representation.

- [ ] **Step 1: Write failing closed-authority tests**

Create `tests/unit/test_re_v2_protocol_23_authority.py` with these initial tests:

```python
from __future__ import annotations

from dataclasses import replace

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_23.authority import (
    ProsaicAgentAuthorityV1,
    Protocol23AuthorityError,
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
```

- [ ] **Step 2: Run the new test module and verify the missing module failure**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_23_authority.py -v
```

Expected: collection ERROR with `ModuleNotFoundError` for
`harness.re_v2.protocol_23`.

- [ ] **Step 3: Implement the closed authority value**

Create `src/harness/re_v2/protocol_23/authority.py` with:

```python
"""Pinned Prosaic agent authority for RE engine protocol 2.3."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest


class Protocol23AuthorityError(ValueError):
    """Raised when inspected Prosaic authority is absent or malformed."""


RE_BASELINER_AGENT_ID = "echelon.re-baseliner"
_FRONTMATTER_FIELDS = frozenset(
    {"name", "description", "execution", "tools", "color", "model_tier", "effort"}
)
_REQUIRED_VALUES = {
    "name": RE_BASELINER_AGENT_ID,
    "execution": "agent",
    "tools": "write",
    "color": "orange",
    "model_tier": "strong",
    "effort": "high",
}


@dataclass(frozen=True, slots=True)
class ProsaicAgentAuthorityV1:
    agent_id: str
    body: str
    frontmatter: Mapping[str, Any]
    schema_version: int = field(default=1, init=False)
    artifact_type: str = field(default="prosaic_agent_authority", init=False)
    loader_schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        if self.agent_id != RE_BASELINER_AGENT_ID:
            raise Protocol23AuthorityError(
                f"unsupported Prosaic agent authority: {self.agent_id!r}"
            )
        if not isinstance(self.body, str) or not self.body.strip():
            raise Protocol23AuthorityError("Prosaic agent body must be nonempty text")
        try:
            self.body.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise Protocol23AuthorityError("Prosaic agent body must be UTF-8") from exc
        if not isinstance(self.frontmatter, Mapping):
            raise Protocol23AuthorityError("Prosaic frontmatter must be an object")
        copied = dict(self.frontmatter)
        if set(copied) != _FRONTMATTER_FIELDS:
            raise Protocol23AuthorityError(
                "Prosaic frontmatter must contain exactly "
                + ", ".join(sorted(_FRONTMATTER_FIELDS))
            )
        description = copied.get("description")
        if not isinstance(description, str) or not description.strip():
            raise Protocol23AuthorityError("Prosaic frontmatter description must be nonempty")
        for key, expected in _REQUIRED_VALUES.items():
            if copied.get(key) != expected:
                raise Protocol23AuthorityError(
                    f"Prosaic frontmatter {key} must be {expected!r}"
                )
        object.__setattr__(self, "frontmatter", MappingProxyType(copied))

    @classmethod
    def from_artifact(
        cls, agent_id: str, artifact: ProsaicCommandArtifact
    ) -> "ProsaicAgentAuthorityV1":
        if not isinstance(artifact, ProsaicCommandArtifact):
            raise Protocol23AuthorityError("Prosaic inspection returned no agent artifact")
        return cls(agent_id=agent_id, body=artifact.body, frontmatter=artifact.frontmatter)

    @property
    def body_bytes(self) -> bytes:
        return self.body.encode("utf-8")

    @property
    def body_hash(self) -> str:
        return content_digest(self.body_bytes)

    @property
    def frontmatter_hash(self) -> str:
        return content_digest(canonical_json_bytes(dict(self.frontmatter)))

    @property
    def inspection_receipt_hash(self) -> str:
        return content_digest(
            {
                "loader_schema_version": self.loader_schema_version,
                "agent_id": self.agent_id,
                "body_hash": self.body_hash,
                "frontmatter_hash": self.frontmatter_hash,
            }
        )

    @property
    def artifact_id(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "agent_id": self.agent_id,
            "body_hash": self.body_hash,
            "frontmatter_hash": self.frontmatter_hash,
            "frontmatter": dict(self.frontmatter),
            "inspection": {
                "loader_schema_version": self.loader_schema_version,
                "receipt_hash": self.inspection_receipt_hash,
            },
        }
```

Create `src/harness/re_v2/protocol_23/__init__.py` with explicit exports:

```python
"""RE v2 engine protocol 2.3 Prosaic-first authority."""

from .authority import (
    ProsaicAgentAuthorityV1,
    Protocol23AuthorityError,
    RE_BASELINER_AGENT_ID,
)

__all__ = (
    "ProsaicAgentAuthorityV1",
    "Protocol23AuthorityError",
    "RE_BASELINER_AGENT_ID",
)
```

- [ ] **Step 4: Run the authority tests**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_23_authority.py -v
```

Expected: all tests added in Step 1 PASS.

- [ ] **Step 5: Commit the immutable authority value**

```bash
git add src/harness/re_v2/protocol_23/__init__.py src/harness/re_v2/protocol_23/authority.py tests/unit/test_re_v2_protocol_23_authority.py
git commit -m "feat(re-v2): add pinned Prosaic agent authority"
```

### Task 2: Enforce the goal-aware L0/L1 Prosaic boundary

**Files:**

- Modify: `src/harness/re_v2/protocol_23/authority.py`
- Modify: `src/harness/re_v2/protocol_23/__init__.py`
- Modify: `tests/unit/test_re_v2_protocol_23_authority.py`

**Interfaces:**

- Consumes: `load_re_agent_authorities(project_root: Path, *, goal: str, loader: ProsaicPromptLoader | None = None)`.
- Produces: immutable `Mapping[str, ProsaicAgentAuthorityV1]`.
- For `goal="inventory"`: returns an empty mapping without constructing or calling a loader.
- For `goal="baseline"`: loads exactly `echelon.re-baseliner`, fails closed when missing, and returns it keyed by agent ID.

- [ ] **Step 1: Add failing goal-boundary tests**

Append to `tests/unit/test_re_v2_protocol_23_authority.py`:

```python
from pathlib import Path

from harness.re_v2.protocol_23.authority import load_re_agent_authorities


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
def test_baseline_fails_closed_when_installed_agent_is_missing(tmp_path: Path) -> None:
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
```

- [ ] **Step 2: Run the goal-boundary tests and verify the missing function failure**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_23_authority.py -v
```

Expected: collection ERROR because `load_re_agent_authorities` is not defined.

- [ ] **Step 3: Implement goal-aware authority loading**

Add these imports to `authority.py`:

```python
from pathlib import Path

from harness.prosaic_prompt_loader import ProsaicPromptLoader
```

Then add:

```python
def load_re_agent_authorities(
    project_root: Path,
    *,
    goal: str,
    loader: ProsaicPromptLoader | None = None,
) -> Mapping[str, ProsaicAgentAuthorityV1]:
    if goal == "inventory":
        return MappingProxyType({})
    if goal != "baseline":
        raise Protocol23AuthorityError(f"unsupported RE v2 goal: {goal!r}")
    resolved_loader = loader or ProsaicPromptLoader(project_root)
    artifact = resolved_loader.load_subagent(RE_BASELINER_AGENT_ID)
    if artifact is None:
        raise Protocol23AuthorityError(
            "installed Prosaic agent echelon.re-baseliner is missing; run "
            "`echelon workspace migrate-to-prosaic` before starting RE"
        )
    authority = ProsaicAgentAuthorityV1.from_artifact(
        RE_BASELINER_AGENT_ID, artifact
    )
    return MappingProxyType({RE_BASELINER_AGENT_ID: authority})
```

Export `load_re_agent_authorities` from `protocol_23/__init__.py` and include it
in `__all__`.

- [ ] **Step 4: Run the complete first-increment test set**

Run:

```bash
pytest tests/unit/test_prosaic_prompt_loader.py tests/unit/test_re_v2_protocol_23_authority.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Verify protocol-2.2 isolation and the dirty-worktree boundary**

Run:

```bash
pytest tests/unit/test_re_v2_protocol_compatibility.py tests/integration/test_re_v2_v1_isolation.py -v
git diff --check
git status --short
```

Expected: tests PASS; the new protocol-2.3 files and planned test changes are
the only increment changes, while the pre-existing snapshot files remain
separately modified.

- [ ] **Step 6: Commit the goal-aware boundary**

```bash
git add src/harness/re_v2/protocol_23/__init__.py src/harness/re_v2/protocol_23/authority.py tests/unit/test_re_v2_protocol_23_authority.py
git commit -m "feat(re-v2): enforce Prosaic layer authority boundary"
```

## Increment Acceptance

This increment is accepted only when:

- authority body and frontmatter are separate, canonically hashed, and immutable;
- invalid neutral execution metadata fails closed;
- inventory/L0 provably performs zero Prosaic loads;
- baseline/L1 authority provably requires exactly the baseliner through `ProsaicPromptLoader`;
- no protocol-2.2 code or manifest bytes change; and
- the unrelated workspace-snapshot edits remain preserved and uncommitted by these tasks.

The next plan, after review of this increment, will add shared-provider metadata
mapping and the `SquadCliProvider`-backed protocol-2.3 dispatch envelope. That
increment will also revise the baseliner's write prose while atomically disabling
new protocol-2.2 provider dispatch, so changing the agent bytes cannot strand an
old run between authority models. It must consume the interfaces defined here
rather than introducing another agent loader.
