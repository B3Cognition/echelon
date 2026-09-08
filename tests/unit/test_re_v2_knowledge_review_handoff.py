"""Offline discovery dispatch to passive review admission; no review execution claim."""
import importlib
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from tests.unit.test_re_v2_knowledge_dispatch import _controller


@pytest.mark.unit
def test_captured_proposal_handoff_keeps_feedback_without_repeating_discovery(tmp_path):
    controller, account, phase, calls = _controller(tmp_path)
    proposal = controller.step()
    assert proposal.state == "proposal_ready"
    usage = account.status()
    binding = phase.status().binding_id
    admission = json.loads(phase.objects.read_blob(proposal.receipt_id))
    context = json.loads(phase.boundary.provider_bytes(binding))
    evidence = context["evidence"][0]["projection_id"]
    review = {
        "schema_version": 1, "kind": "discovery_review",
        "proposal_id": admission["proposal_id"], "verdict": "revise",
        "domains": [{"key": "execution", "verdict": "supported",
                     "rationale": "The entry point executes a command.", "evidence_ids": [evidence]}],
        "subjects": [{"key": "runner", "verdict": "supported",
                      "rationale": "The supplied entry point supports this subject.", "evidence_ids": [evidence]}],
        "inventory": [
            {"path": "app.py", "owner": "runner", "disposition": "owned",
             "rationale": "The entry point is supplied.", "evidence_ids": [evidence]},
            {"path": "worker.py", "owner": None, "disposition": "needs-assignment",
             "rationale": "Worker behavior has not yet been assigned.", "evidence_ids": []},
        ],
        "overlaps": [],
        "findings": [{"target": "source", "reason_class": "ownership",
                      "rationale": "Inspect and assign worker.py before planning.", "evidence_ids": []}],
    }
    module = importlib.import_module("harness.re_v2.knowledge_discovery_review")
    boundary = module.DiscoveryReviewBoundary(phase.boundary)
    receipt_id = boundary.admit(binding, proposal.receipt_id, canonical_json_bytes(review))
    replay = module.DiscoveryReviewBoundary(phase.boundary).read_review(
        binding, proposal.receipt_id, receipt_id)
    assert replay["outcome"] == "revision_required"
    assert replay["execution_certification_required"] is True
    assert replay["analysis_certified"] is False
    # A passive review cannot spend, start a repair, or reset the stopped discovery.
    assert account.status() == usage
    assert controller.step() == proposal
    assert len(calls) == 1
    assert phase.status().binding_id == binding
