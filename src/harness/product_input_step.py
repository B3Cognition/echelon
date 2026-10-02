"""Product-input mutations use the same sealed step and recovery loop as Phase A."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from echelon.product_input_transaction import (
    authenticate_pending_product_input_mutation,
    require_product_input_mutation_postimage,
)
from harness.spec_step import PreparedSpecStep, prepare_spec_step, load_prepared_spec_step
from harness.spec_step_effects import PhaseASpecStepEffects
from harness.spec_step_kernel import drain_pending_spec_step
from harness.squad_publication import load_prepared_publication
from harness.state_transaction_namespace import (
    PENDING_SPEC_STEP_KEY, PRODUCT_INPUT_MUTATION_KEY,
    SPEC_STEP_PUBLICATION_PLAN_KEY,
    require_product_input_mutation_publication_binding,
)

if TYPE_CHECKING:
    from harness.squad_state import RoutingStateSnapshot, SquadStateStore


def controller_product_input_provenance(
    project_root: Path, final_state: dict[str, object], marker: Mapping[str, object] | None,
) -> dict[str, object]:
    """Move a controller's transient mutation proof into sealed provenance."""
    raw = final_state.pop(PRODUCT_INPUT_MUTATION_KEY, None)
    if raw is None:
        return {}
    mutation = require_product_input_mutation_publication_binding(raw, marker)
    inputs = final_state.get("product_inputs")
    if (
        mutation["kind"] != "controller_update"
        or not isinstance(inputs, dict)
        or inputs.get("inputs_dir") != mutation["inputs_dir"]
        or inputs.get("tree_hash") != mutation["new_tree_hash"]
    ):
        raise ValueError("controller product input postimage is invalid")
    return {"controller_product_input_mutation": {
        "project_root": str(Path(project_root).resolve()), "mutation": mutation,
    }}


def controller_product_input_step_view(
    prepared: PreparedSpecStep, project_root: Path, state: Mapping[str, object],
) -> dict[str, object] | None:
    """Authenticate a detached controller publication view, never durable aliases."""
    final = prepared.intent.final_state
    proof = prepared.intent.provenance.get("controller_product_input_mutation")
    if PRODUCT_INPUT_MUTATION_KEY in final:
        raise ValueError("controller product input step retains retired authority")
    if proof is None:
        if final.get("product_inputs") != state.get("product_inputs"):
            raise ValueError("controller product input update has no sealed proof")
        return None
    root = Path(project_root).resolve()
    publication = prepared.intent.publication
    if (
        prepared.intent.origin not in {"routed", "terminal"}
        or prepared.intent.route.get("kind") != prepared.intent.origin
        or not isinstance(proof, dict)
        or set(proof) != {"project_root", "mutation"}
        or proof["project_root"] != str(root)
        or not prepared._squad_dir.resolve().is_relative_to(root)
        or not isinstance(publication, dict)
        or publication.get("kind") not in {"external", "both"}
        or "publication" not in prepared.intent.effects
        or any(key in final for key in (PENDING_SPEC_STEP_KEY, SPEC_STEP_PUBLICATION_PLAN_KEY))
    ):
        raise ValueError("controller product input step binding is invalid")
    marker = publication.get("marker") if publication["kind"] == "external" else publication.get("external")
    mutation = require_product_input_mutation_publication_binding(proof["mutation"], marker)
    inputs_path = (root / str(mutation["inputs_dir"])).resolve()
    inputs = final.get("product_inputs")
    previous_inputs = state.get("product_inputs")
    if (
        mutation["kind"] != "controller_update"
        or inputs_path not in {
            (prepared._squad_dir / "inputs").resolve(),
            (prepared._squad_dir / "staging/inputs").resolve(),
        }
        or marker["transaction_id"] != prepared.marker.step_id
        or not isinstance(inputs, dict)
        or inputs.get("inputs_dir") != mutation["inputs_dir"]
        or inputs.get("tree_hash") != mutation["new_tree_hash"]
        or not isinstance(previous_inputs, dict)
        or previous_inputs.get("inputs_dir") != mutation["inputs_dir"]
        or previous_inputs.get("tree_hash") != mutation["old_tree_hash"]
    ):
        raise ValueError("controller product input step postimage is invalid")
    view = deepcopy(final)
    view[PRODUCT_INPUT_MUTATION_KEY] = mutation
    view[SPEC_STEP_PUBLICATION_PLAN_KEY] = marker
    return view


def prepare_product_input_step(
    squad_dir: Path, project_root: Path, snapshot: RoutingStateSnapshot,
    marker: dict[str, object], mutation: dict[str, object], final_state: dict[str, object],
) -> PreparedSpecStep:
    root = Path(project_root).resolve()
    if Path(squad_dir).resolve().parent != root / "runs":
        raise ValueError("product input run is not owned by the project")
    return prepare_spec_step(
        squad_dir, step_id=marker["transaction_id"], origin="resolution",
        expected_state_revision=snapshot.state_revision,
        expected_previous_dispatch_sha256=snapshot.previous_dispatch_sha256,
        route={"kind": "product_input_mutation", "from_phase": snapshot.phase,
               "to_phase": final_state["phase"]},
        effects=("publication",), publication={"kind": "external", "marker": marker},
        final_state=final_state,
        provenance={"project_root": str(root), "product_input_mutation": mutation},
    )


def product_input_step_view(prepared: PreparedSpecStep, project_root: Path) -> dict[str, object]:
    """Construct the authenticated effect view; never persist a second authority."""
    publication = prepared.intent.publication
    provenance = prepared.intent.provenance
    route = prepared.intent.route
    root = Path(project_root).resolve()
    if (
        prepared.intent.origin != "resolution"
        or set(route) != {"kind", "from_phase", "to_phase"}
        or route.get("kind") != "product_input_mutation"
        or prepared.intent.effects != ("publication",)
        or not isinstance(publication, dict) or publication.get("kind") != "external"
        or set(provenance) != {"project_root", "product_input_mutation"}
        or provenance["project_root"] != str(root)
        or prepared._squad_dir.resolve().parent != root / "runs"
    ):
        raise ValueError("product input step binding is invalid")
    marker = publication["marker"]
    mutation = require_product_input_mutation_publication_binding(
        provenance["product_input_mutation"], marker,
    )
    allowed_routes = {
        "add_input": ("phase1-investigate", "phase1-investigate"),
        "traceability_repair": (route.get("from_phase"), "phase4-document"),
    }
    view = deepcopy(prepared.intent.final_state)
    inputs = view.get("product_inputs")
    if (
        mutation["kind"] not in allowed_routes
        or (route.get("from_phase"), route.get("to_phase")) != allowed_routes[mutation["kind"]]
        or not route.get("from_phase")
        or view.get("phase") != route.get("to_phase")
        or view.get("status") != "running"
        or not isinstance(inputs, dict)
        or inputs.get("tree_hash") != mutation["new_tree_hash"]
        or inputs.get("inputs_dir") != mutation["inputs_dir"]
        or any(key in view for key in (
            PENDING_SPEC_STEP_KEY, PRODUCT_INPUT_MUTATION_KEY, SPEC_STEP_PUBLICATION_PLAN_KEY,
        ))
    ):
        raise ValueError("product input step postimage is invalid")
    view[PRODUCT_INPUT_MUTATION_KEY] = mutation
    view[SPEC_STEP_PUBLICATION_PLAN_KEY] = marker
    return view


def apply_product_input_publication(prepared: PreparedSpecStep, project_root: Path) -> dict[str, object]:
    view = product_input_step_view(prepared, project_root)
    marker = view[SPEC_STEP_PUBLICATION_PLAN_KEY]
    staged = load_prepared_publication(project_root, prepared._squad_dir, marker)
    authenticate_pending_product_input_mutation(
        project_root, view, marker, staged._manifest["operations"],
        staged_inputs=staged._transaction_root / "work/product-inputs",
    )
    staged.publish()
    verified = require_product_input_mutation_postimage(project_root, view, marker)
    return {"schema_version": 1, "marker": marker, "product_input_tree_hash": verified}


def recover_product_input_step(project_root: Path, store: SquadStateStore) -> dict[str, object] | None:
    state = store.load()
    marker = state.get(PENDING_SPEC_STEP_KEY)
    if marker is None:
        return None
    prepared = load_prepared_spec_step(store.squad_dir, marker)
    if prepared.intent.route.get("kind") != "product_input_mutation":
        raise ValueError("another spec step is pending")
    view = product_input_step_view(prepared, project_root)
    effects = PhaseASpecStepEffects(
        project_root=project_root, squad_dir=store.squad_dir,
        phase_graph=None, telemetry_store=None, context_drawer_loader=None,
        publication_effect_applier=lambda step, _state: apply_product_input_publication(step, project_root),
    )
    outcome = drain_pending_spec_step(store, store.squad_dir, effects)
    if outcome.blocked:
        raise ValueError("product input step requires reconciliation")
    store.confirm_durable_state(store.load())
    load_prepared_publication(project_root, store.squad_dir, view[SPEC_STEP_PUBLICATION_PLAN_KEY]).discard()
    prepared.discard()
    return view[PRODUCT_INPUT_MUTATION_KEY]
