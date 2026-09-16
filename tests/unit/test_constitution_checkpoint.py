"""Shared policy must be authentic both on disk and inside its checkpoint."""
import pytest

from harness.phase_checkpoints import (
    create_or_recover_completion_checkpoint, fresh_completion_checkpoint_ledger_image,
    PhaseCheckpointError,
)
from tests.unit.test_phase_checkpoints import _checkpoint_repo, _git


@pytest.mark.parametrize("damage", [None, "wrong", "missing"])
def test_checkpoint_verifies_exact_canonical_constitution_blob(tmp_path, damage):
    root, spec = _checkpoint_repo(tmp_path)
    parent = _git(root, "rev-parse", "HEAD")
    policy = root / ".echelon/constitution.md"
    policy.parent.mkdir()
    expected = b"# Constitution\nConcrete shared policy.\n"
    if damage != "missing":
        policy.write_bytes(b"Wrong policy\n" if damage == "wrong" else expected)
    common = dict(project_root=root, spec_dir=spec, phase="phase1-constitution",
        next_phase="phase1-what", run_id="spec-run", spec_id="001-demo", completion_id="a" * 32,
        checkpoint_prestate={"kind": "git_head", "head": parent})
    receipt = create_or_recover_completion_checkpoint(**common,
        additional_owned_paths=(policy,) if damage != "missing" else (), force_commit=True)
    # Correct live content must not certify a different committed image.
    policy.write_bytes(expected)
    kwargs = dict(**common, expected_receipt=receipt, allow_pending=False,
        artifact_images={(spec / "spec.md").relative_to(root).as_posix(): (0o644, b"# Demo\n")},
        additional_file_images={".echelon/constitution.md": (0o644, expected)})
    if damage:
        with pytest.raises(PhaseCheckpointError): fresh_completion_checkpoint_ledger_image(**kwargs)
    else:
        assert fresh_completion_checkpoint_ledger_image(**kwargs) is not None
