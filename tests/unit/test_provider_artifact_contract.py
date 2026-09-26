from __future__ import annotations

from pathlib import Path

import pytest

from harness.provider_output_publication import (
    ProviderArtifactContractError,
    compile_provider_artifact_contract,
    provider_artifact_contract_sha256,
    resolve_provider_artifact_contract,
)


def test_compile_publish_artifact_contract_preserves_typed_rules() -> None:
    contract = compile_provider_artifact_contract(
        {
            "mode": "publish",
            "allow_shadow_recovery": True,
            "artifacts": [
                {
                    "root": "active_spec",
                    "path": "spec.md",
                    "kind": "file",
                    "requirement": "required",
                },
                {
                    "root": "active_spec",
                    "path": "adr",
                    "kind": "directory",
                    "requirement": "optional",
                },
            ],
            "read_inputs": [
                {
                    "root": "active_spec",
                    "path": "assumptions.md",
                    "kind": "file",
                },
            ],
        },
        assignment_id="phase1-what",
    )

    assert contract.mode == "publish"
    assert contract.artifacts[0].path == "spec.md"
    assert contract.artifacts[1].requirement == "optional"
    assert contract.read_inputs[0].path == "assumptions.md"
    assert contract.allow_shadow_recovery is True
    assert len(provider_artifact_contract_sha256(contract)) == 64


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {
            "mode": "publish",
            "artifacts": [
                {
                    "root": "active_spec",
                    "path": "../spec.md",
                    "kind": "file",
                    "requirement": "required",
                }
            ],
        },
        {
            "mode": "result_only",
            "artifacts": [
                {
                    "root": "active_spec",
                    "path": "spec.md",
                    "kind": "file",
                    "requirement": "required",
                }
            ],
        },
        {
            "mode": "publish",
            "artifacts": [
                {
                    "root": "active_spec",
                    "path": "contracts",
                    "kind": "directory",
                    "requirement": "required",
                },
                {
                    "root": "active_spec",
                    "path": "contracts/http.md",
                    "kind": "file",
                    "requirement": "required",
                },
            ],
        },
        {"mode": "publish", "artifacts": [], "unexpected": True},
        {"mode": True, "artifacts": []},
    ],
)
def test_compile_artifact_contract_rejects_missing_unsafe_or_overlapping_rules(
    raw: object,
) -> None:
    with pytest.raises(ProviderArtifactContractError):
        compile_provider_artifact_contract(raw, assignment_id="phase")


def test_resolve_provider_artifact_contract_uses_named_roots(tmp_path: Path) -> None:
    contract = compile_provider_artifact_contract(
        {
            "mode": "publish",
            "artifacts": [
                {
                    "root": "squad",
                    "path": "constitution.draft.md",
                    "kind": "file",
                    "requirement": "required",
                }
            ],
            "read_inputs": [
                {"root": "project", "path": "src", "kind": "directory"}
            ],
        },
        assignment_id="phase1-constitution",
    )

    resolved = resolve_provider_artifact_contract(
        contract,
        assignment_id="phase1-constitution",
        roots={
            "active_spec": tmp_path / "spec",
            "project": tmp_path,
            "squad": tmp_path / ".echelon" / "squad",
            "context": tmp_path / ".echelon" / "context",
            "runtime": tmp_path / ".echelon" / "runtime",
            "staging": tmp_path / ".echelon" / "staging",
            "proposal": tmp_path / ".echelon" / "proposal",
        },
    )

    assert resolved.assignment_id == "phase1-constitution"
    assert resolved.write_paths == (
        (tmp_path / ".echelon" / "squad" / "constitution.draft.md").resolve(),
    )
    assert resolved.read_paths == ((tmp_path / "src").resolve(),)
    assert resolved.contract_sha256 == provider_artifact_contract_sha256(contract)


def test_resolve_provider_artifact_contract_rechecks_containment(
    tmp_path: Path,
) -> None:
    contract = compile_provider_artifact_contract(
        {
            "mode": "publish",
            "artifacts": [
                {
                    "root": "active_spec",
                    "path": "outside/spec.md",
                    "kind": "file",
                    "requirement": "required",
                }
            ],
        },
        assignment_id="phase",
    )
    spec_root = tmp_path / "spec"
    spec_root.mkdir()
    (spec_root / "outside").symlink_to(tmp_path / "outside", target_is_directory=True)

    with pytest.raises(ProviderArtifactContractError):
        resolve_provider_artifact_contract(
            contract,
            assignment_id="phase",
            roots={"active_spec": spec_root},
        )
