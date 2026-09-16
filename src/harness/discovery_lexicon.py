"""Closed managed derivation contract; the native gate owns certification."""
import hashlib

LEXICON_OUTPUT = "requirements.lexicon.md"


def source_metadata(source_text):
    """Model-facing metadata from the already authenticated captured source."""
    return dict(source_name="spec.md", source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest())


def validate_lexicon_routing(value):
    if (type(value) is not dict or set(value) != {"verdict", "state_updates"}
            or type(value["verdict"]) is not str or value["verdict"] not in {"DONE", "FAIL"}
            or type(value["state_updates"]) is not dict or value["state_updates"]):
        raise ValueError("derivation cannot supply gate authority or state updates")


def validate_lexicon_artifacts(artifacts):
    if (type(artifacts) is not dict or set(artifacts) != {LEXICON_OUTPUT}
            or type(artifacts[LEXICON_OUTPUT]) is not str
            or not artifacts[LEXICON_OUTPUT].strip() or "\x00" in artifacts[LEXICON_OUTPUT]):
        raise ValueError("derivation requires its single nonblank text artifact")
    artifacts[LEXICON_OUTPUT].encode("utf-8")


def require_lexicon_parent(root, run, state, source):
    """Authenticate the completed review before selecting any derivation work."""
    from harness.discovery_completion import _retained_input_projection, _require
    from harness.element_identity_store import IdentityStore
    from harness.phase1_quality import has_current_phase1_quality_certificate
    binding, _, _ = _retained_input_projection(root, run, state, IdentityStore.open(root),
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=False, required_route=("phase1-why2", "phase1-lexicon-derive"))
    _require(binding.producer == "why2" and not binding.resolution_publication
        and binding.candidate["routing"]["verdict"] == "PASS"
        and has_current_phase1_quality_certificate(state, project_root=root))
    return binding
