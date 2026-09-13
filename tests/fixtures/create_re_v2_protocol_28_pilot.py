#!/usr/bin/env python3
"""Create a disposable clean protocol-2.8 installed-provider pilot workspace."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.re_v2.canonical import content_digest  # noqa: E402
from harness.re_v2.protocol_28.executors import build_l4_executor_catalog  # noqa: E402
from harness.re_v2.protocol_28.lifecycle import (  # noqa: E402
    Protocol28CheckpointAdoptionV1,
    create_or_reuse_protocol_28_child,
)
from harness.re_v2.protocol_28.checkpoint_cache import (  # noqa: E402
    load_checkpoint_cache_v2,
)
from harness.re_v2.protocol_28.checkpoints import (  # noqa: E402
    CheckpointSelectionBundleV2,
    CheckpointSelectionEntryV2,
)
from harness.re_v2.protocol_28.context import (  # noqa: E402
    load_protocol_28_run_context,
)
from harness.re_v2.protocol_28.inputs import Protocol28CreationInputs  # noqa: E402
from harness.re_v2.ledger import ObjectStore  # noqa: E402
from harness.re_v2.protocol_28.policies import (  # noqa: E402
    build_initial_exhaustive_policy,
)
from harness.re_v2.protocol_28.preparation import (  # noqa: E402
    load_protocol_28_role_bytes,
    prepare_protocol_28_request,
)
from tests.unit.test_re_v2_protocol_28_preparation import (  # noqa: E402
    _preparation_fixture,
)


def create_pilot(parent: Path) -> tuple[Path, str]:
    parent = parent.resolve()
    if parent.exists() and any(parent.iterdir()):
        raise ValueError(f"pilot parent must be empty: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    workspace, intent, eligible_l3, options = _preparation_fixture(parent)
    config = workspace / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "  sources:\n"
        "    - id: api\n"
        "      path: sources/api\n"
        "harness:\n"
        "  provider: docker\n"
        "  llm:\n"
        "    cli: codex\n"
        "    model: gpt-5.4\n"
        "    timeout_ms: 300000\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["echelon", "workspace", "migrate-to-prosaic"],
        cwd=workspace,
        check=True,
    )
    producer, verifier = load_protocol_28_role_bytes(workspace)
    policy = build_initial_exhaustive_policy(
        producer_contract_hash=content_digest(producer),
        verifier_contract_hash=content_digest(verifier),
    )
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(
            options.inherited_executor_contract_bytes
        ),
        producer_agent_contract_hash=content_digest(producer),
        verifier_agent_contract_hash=content_digest(verifier),
    )
    intent = replace(
        intent,
        exhaustive_policy_catalog_id=policy.identity,
        executor_catalog_id=executors.identity,
    )
    options = replace(
        options,
        token_limit=100_000_000,
        active_ms_limit=600_000_000,
        producer_agent_bytes=producer,
        verifier_agent_bytes=verifier,
    )
    inputs = prepare_protocol_28_request(workspace, intent, eligible_l3, options)
    run_dir = create_or_reuse_protocol_28_child(workspace, inputs)
    metadata = {
        "workspace": str(workspace),
        "run_id": run_dir.name,
        "provider": "codex",
        "producer_model_tier": "strong",
        "producer_effort": "high",
        "verifier_model_tier": "strong",
        "verifier_effort": "high",
        "planned_slices": sum(
            len(target.entries) for target in inputs.exhaustive_plan.target_plans
        ),
    }
    (workspace / "pilot-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace / "sources" / "api",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError("pilot source is dirty after creation")
    return workspace, run_dir.name


def create_adopted_sibling(origin: Path, sibling: Path) -> str:
    """Create an exact child-local sibling from an installed pilot's V2 cache."""
    origin = origin.resolve()
    sibling = sibling.resolve()
    if sibling.exists() and any(sibling.iterdir()):
        raise ValueError(f"sibling workspace must be empty: {sibling}")
    sibling.mkdir(parents=True, exist_ok=True)
    for name in ("config.yml", "prosaic", "runtime"):
        source = origin / ".echelon" / name
        target = sibling / ".echelon" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    origin_run_id = (origin / "runs" / ".current-re").read_text(
        encoding="utf-8"
    ).strip()
    origin_run = origin / "runs" / origin_run_id
    context = load_protocol_28_run_context(origin_run)
    _index, manifests, _quarantine = load_checkpoint_cache_v2(origin)
    selected_manifests = tuple(
        sorted(manifests.values(), key=lambda item: item.identity)
    )
    origin_store = ObjectStore(origin_run / "v2" / "objects")
    authority = {
        manifest.identity: {
            object_id: origin_store.read_blob(object_id)
            for object_id in manifest.immutable_object_hashes
        }
        for manifest in selected_manifests
    }
    selection = CheckpointSelectionBundleV2(
        2,
        tuple(
            sorted(
                (
                    CheckpointSelectionEntryV2(
                        manifest.slice_spec.output_artifact_key_id,
                        manifest.identity,
                        manifest.accepted_slice.identity,
                    )
                    for manifest in selected_manifests
                ),
                key=lambda item: item.output_artifact_key_id,
            )
        ),
        (),
        (),
        (),
    )
    inputs = context.inputs
    sibling_inputs = Protocol28CreationInputs(
        manifest=replace(
            inputs.manifest,
            run_id="re-l4-adopted-sibling",
            created_at="2026-09-01T00:00:00Z",
        ),
        parent_authority_bundle=inputs.parent_authority_bundle,
        l3_projection_catalog=inputs.l3_projection_catalog,
        snapshot_evidence_catalog=inputs.snapshot_evidence_catalog,
        exhaustive_subject_catalog=inputs.exhaustive_subject_catalog,
        exhaustive_policy=inputs.exhaustive_policy,
        executor_catalog=inputs.executor_catalog,
        exhaustive_plan=inputs.exhaustive_plan,
        authority_objects=inputs.authority_objects,
    )
    run_dir = create_or_reuse_protocol_28_child(
        sibling,
        sibling_inputs,
        checkpoint_adoption=Protocol28CheckpointAdoptionV1(
            selection,
            manifests,
            authority,
        ),
    )
    return run_dir.name


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "--sibling":
        run_id = create_adopted_sibling(Path(argv[2]), Path(argv[3]))
        print(json.dumps({"workspace": str(Path(argv[3]).resolve()), "run_id": run_id}))
        return 0
    if len(argv) != 2:
        print(
            "usage: create_re_v2_protocol_28_pilot.py <empty-pilot-parent>\n"
            "   or: create_re_v2_protocol_28_pilot.py --sibling "
            "<origin-workspace> <empty-sibling-workspace>",
            file=sys.stderr,
        )
        return 2
    workspace, run_id = create_pilot(Path(argv[1]))
    print(json.dumps({"workspace": str(workspace), "run_id": run_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
