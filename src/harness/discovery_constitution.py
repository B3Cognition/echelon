"""Closed CHIEF shared-file contract; no storage or publication authority."""
import re

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.element_artifacts import parse_identity_artifact
from harness.phase_a_readiness import unresolved_constitution_template_markers


CONSTITUTION_PATH = ".echelon/constitution.md"
SOURCE_KEY = "managed_constitution_source"


def constitution_source(state):
    from harness.discovery_producer import SOURCE_FIELDS
    if SOURCE_KEY not in state:
        return None
    source = state[SOURCE_KEY]
    if (type(source) is not dict or set(source) != set(SOURCE_FIELDS)
            or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value) is None
                for key, value in source.items())
            or bootstrap_from_state(state) is None or "managed_identity" not in state):
        raise ValueError("invalid Constitution source")
    return dict(source)


def validate_constitution_candidate(text, before):
    if (type(text) is not str or not text.strip() or "\x00" in text
            or unresolved_constitution_template_markers(text)):
        raise ValueError("invalid Constitution draft")
    parsed = parse_identity_artifact(path="constitution.md", role="references", text=text)
    if parsed.references or parsed.diagnostics:
        raise ValueError("shared Constitution cannot bind spec-scoped identities")
    if before is not None and text != before:
        raise ValueError("Constitution creation cannot amend existing shared policy")


def constitution_input_source(state, operation_id=None):
    """Select current input without moving the retained original source."""
    from harness.discovery_producer import producer_operation_id, tracker_round
    selected = producer_operation_id(state, "constitution", operation_id)
    if selected.startswith("constitution-refresh-"):
        return dict(tracker_round(state, selected, producer="constitution")["source"])
    return constitution_source(state)


def publication_target(producer, spec_path, name):
    if producer == "constitution":
        if name != "constitution.md":
            raise ValueError("Constitution has one canonical target")
        return CONSTITUTION_PATH
    return spec_path + "/" + name


def require_constitution_parent(root, run, state, source):
    """Authenticate the released native WHY1 → Constitution route."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    binding, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-why1", "phase1-constitution"))
    _require(binding.producer == "why1" and not binding.clarification)
    original = constitution_source(state)
    if original is not None and source != original:
        require_refreshed_why1(root, run, state, binding, IdentityStore.open(root))


def tracker_predecessor(state, binding):
    from harness.discovery_producer import tracker_round
    return tracker_round(state, binding.recovery["operation"]["binding"]["operation_id"], producer="why1")["predecessor"]


def require_refreshed_why1(root, run, state, binding, store):
    """A refresh may ask questions; prove each exact native answer successor."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.discovery_spec import clarification_source
    seen = set()
    while True:
        _require(binding.producer == "why1" and not binding.clarification)
        if binding.recovery["version"] == 11:
            return
        _require(binding.recovery["version"] == 6 and binding.recovery.get("resolution") is not None)
        operation = binding.recovery["operation"]["binding"]["operation_id"]
        _require(operation not in seen)
        seen.add(operation)
        association = binding.recovery["resolution"]
        source = clarification_source(association["completion"])
        _require(binding.recovery["source_completion"] == source)
        predecessor = tracker_predecessor(state, binding)
        answer, _, _ = _retained_input_projection(root, run, state, store,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source,
            require_checkpoint=False, required_origin="resolution", required_route=("phase1-why1", "phase1-why1"))
        _require(answer.producer == "why1" and answer.clarification
            and answer.recovery["resolution"] == association["decision"]
            and answer.recovery["operation"]["binding"]["operation_id"] == predecessor)
        source = answer.recovery["source_completion"]
        binding, _, _ = _retained_input_projection(root, run, state, store,
            operation_id="discovery-completion-" + source["dispatch_id"], source=source,
            require_checkpoint=False, required_route=("phase1-why1", "phase1-why1"))
        _require(binding.recovery["operation"]["binding"]["operation_id"] == predecessor)
