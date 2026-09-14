"""Inactive fresh-spec enrollment under caller-owned Phase A/run leases.

No provider, allocator or publication call belongs here. The caller supplies an
existing sealed, empty inspection transaction and independently selected run.
After discovery publishes, use managed-context authentication, not genesis replay.
"""
from pathlib import Path

from harness.discovery_bootstrap_state import (
    bootstrap_from_state, bootstrap_genesis, bootstrap_ids,
    validate_bootstrap_manifest, validate_selection,
)
from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_store import IdentityStore
from harness.squad_publication import load_prepared_publication
from harness.squad_source_manifest import snapshot_source_manifest


def bootstrap_discovery(project_root, state_store, *, spec_id, run_id, operation_id,
                        spec_path, capture_marker, create=False) -> dict[str, str]:
    """Persist intent, capture, register source/genesis, then attach exact receipt.

    Explicit create is only for a newly selected operation; default resume must
    find its original state metadata. Never initialize a missing identity store.
    The three state writes confirm durability before the following side effect.
    """
    try:
        return _bootstrap(project_root, state_store, spec_id=spec_id, run_id=run_id,
            operation_id=operation_id, spec_path=spec_path, capture_marker=capture_marker, create=create)
    except Exception:
        pass
    raise ValueError("managed discovery bootstrap requires reconciliation") from None


def _bootstrap(project_root, state_store, *, spec_id, run_id, operation_id, spec_path, capture_marker, create):
    if type(create) is not bool:
        raise ValueError("invalid bootstrap mode")
    root = Path(project_root)
    state = state_store.load()
    store = IdentityStore.open(root)
    retained = bootstrap_from_state(state)
    if (create and retained is not None) or (not create and retained is None):
        raise ValueError("explicit bootstrap creation/resume conflict")
    namespace = store.audit()["authority"]
    selected = validate_selection(dict(spec_id=spec_id, run_id=run_id, operation_id=operation_id,
        project_root=str(root), run_dir=str(state_store.squad_dir), spec_path=spec_path,
        capture_marker=capture_marker, workspace_uuid=namespace["workspace_uuid"], epoch_uuid=namespace["epoch_uuid"]))
    if create:
        store.require_unmanaged_execution(spec_id=spec_id, run_ids=(run_id,))
        state = state_store.prepare_discovery_bootstrap(selected)
    elif retained["selection"] != selected:
        raise ValueError("independent bootstrap selection changed")
    else:
        state = state_store.confirm_durable_state(state)

    prepared = load_prepared_publication(root, state_store.squad_dir, capture_marker)
    with prepared.inspect_sources(tree_paths=(spec_path,), file_paths=()) as sources:
        if sources.publication.operations:
            raise ValueError("bootstrap inspection must not contain publication operations")
        manifest = snapshot_source_manifest(trees=sources.trees, files=sources.files)
        validate_bootstrap_manifest(selected, manifest.payload)
        state = state_store.capture_discovery_bootstrap(selected, manifest.payload)
        expected = bootstrap_genesis(selected, manifest.payload)
        ids = bootstrap_ids(selected)
        if "managed_identity" in state:
            # A completed state receipt is not permission to reconstruct rows.
            observed = store.check_managed_context(spec_id=spec_id, run_id=run_id, record=expected)
            source = observed["source_context"]
            if source["sequence"] != "0" or source["manifest"]["payload"] != manifest.payload:
                raise ValueError("bootstrap source head has advanced")
            return observed["managed_identity"]

        source = store.register_source_context(spec_id=spec_id, context_id=ids["context_id"],
            operation_id=ids["source_registration_operation_id"], manifest=manifest)
        if (source["workspace_uuid"], source["epoch_uuid"], source["sequence"], source["manifest"]["payload"]) != (
                selected["workspace_uuid"], selected["epoch_uuid"], "0", manifest.payload):
            raise ValueError("bootstrap source registration changed")
        request = ManagedIdentityRequest(selected["workspace_uuid"], selected["epoch_uuid"], run_id,
            ids["context_id"], spec_path, ids["source_registration_operation_id"], manifest.sha256)
        genesis = store.register_managed_identity(spec_id=spec_id, operation_id=ids["operation_id"], request=request)
        if genesis != expected:
            raise ValueError("bootstrap genesis does not match the selected operation")
        store.check_managed_context(spec_id=spec_id, run_id=run_id, record=genesis)
    # Normal inspection exit includes its final descriptor/source validation.
    # Failed validation may leave idempotent DB registrations, never completion.
    # Caller execution leases still surround this state transition; it is not
    # publication authority or a claim of freshness for later provider inputs.
    state_store.complete_discovery_bootstrap(selected, genesis)
    return genesis
