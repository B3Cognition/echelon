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
