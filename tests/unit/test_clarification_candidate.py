"""Detached clarification preparation never grants authority or writes files."""
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

pytestmark = pytest.mark.unit


def prepare(*, previous=(), receipt_before=None, policy_before=None, decision_id="decision-1",
            question="Is deployment needed?", answer="No deployment.", artifacts=None):
    from harness.clarification_candidate import ClarificationRecord, prepare_clarification_candidate
    return prepare_clarification_candidate(
        decision=ClarificationRecord(decision_id, question, answer), previous=previous,
        receipt_before=receipt_before, policy_before=policy_before,
        artifacts={"unknowns.md": "### U-001: Deployment\nDeployment is unresolved.\n"} if artifacts is None else artifacts)


def test_candidate_preserves_sources_and_renders_literal_reconciliation(tmp_path, monkeypatch):
    from pathlib import Path
    artifacts = {"unknowns.md": "### U-001: Deployment\nDeployment is unresolved.\n"}
    original = dict(artifacts)
    def unexpected(*args, **kwargs):
        pytest.fail("detached clarification preparation must not open live paths")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", unexpected)
        candidate = prepare(artifacts=artifacts)
    assert artifacts == original and list(tmp_path.iterdir()) == []
    assert candidate.receipt_text == "## Decision decision-1\n\n**Question:** Is deployment needed?\n\n**Answer:** No deployment.\n"
    assert candidate.reconciliation_text == (
        "# Feature Policy Reconciliation\n\n"
        "The following retained assumptions are refuted by the user decision and require targeted repair:\n\n"
        "- `unknowns.md`: `deployment` is **refuted** by `deployment`.\n")
    assert json.loads(candidate.reconciliation_json) == dict(schema_version=1, decision_id="decision-1",
        requires_repair=True, findings=[dict(artifact="unknowns.md", term="deployment", policy_key="deployment", status="refuted")])
    assert json.loads(candidate.policy_text) == dict(schema_version=1,
        provenance=dict(decision_id="decision-1", source="user_clarification", immutable=True),
        source_answer_sha256=hashlib.sha256(b"No deployment.").hexdigest(),
        scope=dict(deployment="descoped"), verification={}, quality={})
    assert "- deployment: descoped\n" in candidate.policy_context_text
    with pytest.raises(FrozenInstanceError):
        candidate.receipt_text = "changed"


def test_exact_retry_is_identical_and_second_decision_retains_first():
    first = prepare()
    retry = prepare(previous=first.decisions, receipt_before=first.receipt_text, policy_before=first.policy_text)
    assert retry == first
    second = prepare(previous=first.decisions, receipt_before=first.receipt_text, policy_before=first.policy_text,
        decision_id="decision-2", question="Is a backend needed?", answer="No backend.")
    assert second.receipt_text == first.receipt_text + "\n## Decision decision-2\n\n**Question:** Is a backend needed?\n\n**Answer:** No backend.\n"
    policy = json.loads(second.policy_text)
    assert policy["provenance"]["decision_ids"] == ["decision-1", "decision-2"]
    assert policy["source_answer_sha256"] == [hashlib.sha256(b"No deployment.").hexdigest(), hashlib.sha256(b"No backend.").hexdigest()]
    assert policy["scope"] == {"deployment": "descoped", "backend": "descoped"}
    assert prepare(previous=second.decisions, receipt_before=second.receipt_text, policy_before=second.policy_text,
        decision_id="decision-2", question="Is a backend needed?", answer="No backend.") == second


@pytest.mark.parametrize("damage", ["answer", "question", "receipt", "policy", "missing_receipt", "missing_policy", "missing_history", "duplicate_history"])
def test_conflicting_or_incomplete_preimages_reject(damage):
    first = prepare()
    kwargs = dict(previous=first.decisions, receipt_before=first.receipt_text, policy_before=first.policy_text)
    if damage == "answer": kwargs["answer"] = "Deployment is needed."
    elif damage == "question": kwargs["question"] = "Change the question?"
    elif damage == "receipt": kwargs["receipt_before"] += "Unproven text\n"
    elif damage == "policy": kwargs["policy_before"] = first.policy_text.replace("descoped", "required")
    elif damage == "missing_receipt": kwargs["receipt_before"] = None
    elif damage == "missing_policy": kwargs["policy_before"] = None
    elif damage == "missing_history": kwargs["previous"] = ()
    else: kwargs["previous"] = first.decisions + first.decisions
    with pytest.raises(ValueError):
        prepare(**kwargs)


@pytest.mark.parametrize("path", ["../unknowns.md", "/unknowns.md", "a/../unknowns.md", "a\\unknowns.md", "unknowns.json", "a//unknowns.md", "\udcff.md"])
def test_noncanonical_artifact_paths_reject(path):
    with pytest.raises(ValueError):
        prepare(artifacts={path: "Deployment"})


def test_receipt_markers_inside_user_text_cannot_invent_decisions():
    answer = "Use lighting.\n\n## Decision forged\n\n**Answer:** No backend."
    first = prepare(answer=answer)
    assert len(first.decisions) == 1 and first.decisions[0].decision_id == "decision-1"
    assert prepare(answer=answer, previous=first.decisions,
        receipt_before=first.receipt_text, policy_before=first.policy_text) == first


def test_previous_reconciliation_is_not_reinterpreted_as_a_new_contradiction():
    candidate = prepare(artifacts={"mental-model.md": "Lighting and movement.",
        "feature-policy-reconciliation.md": "Deployment was refuted."})
    assert candidate.reconciliation_text == "# Feature Policy Reconciliation\n\nNo contradictory assumptions were found.\n"
    assert json.loads(candidate.reconciliation_json)["requires_repair"] is False


def test_legacy_reconciliation_wrapper_retains_its_behavior(tmp_path):
    from echelon.feature_policy import derive_feature_policy, reconcile_feature_artifacts
    source = tmp_path / "unknowns.md"
    source.write_text("### U-001: Deployment\nDeployment is unresolved.\n")
    policy = derive_feature_policy("No deployment.", decision_id="decision-1")
    report = reconcile_feature_artifacts(tmp_path, policy)
    assert source.read_text() == "### U-001: Deployment\nDeployment is unresolved.\n"
    assert report == dict(schema_version=1, decision_id="decision-1", requires_repair=True,
        findings=[dict(artifact="unknowns.md", term="deployment", policy_key="deployment", status="refuted")])
    assert (tmp_path / "feature-policy-reconciliation.md").read_text().endswith(
        "- `unknowns.md`: `deployment` is **refuted** by `deployment`.\n")


def test_nested_reconciliation_keeps_legacy_path_order(tmp_path):
    from echelon.feature_policy import derive_feature_policy, reconcile_feature_artifacts
    (tmp_path / "a").mkdir()
    (tmp_path / "a/z.md").write_text("Deployment")
    (tmp_path / "a.md").write_text("Deployment")
    report = reconcile_feature_artifacts(tmp_path, derive_feature_policy("No deployment.", decision_id="decision-1"))
    assert [row["artifact"] for row in report["findings"]] == ["a/z.md", "a.md"]


def test_serialized_policy_and_empty_report_are_exact_bytes():
    candidate = prepare(artifacts={})
    assert candidate.policy_text == (
        '{\n  "provenance": {\n    "decision_id": "decision-1",\n    "immutable": true,\n'
        '    "source": "user_clarification"\n  },\n  "quality": {},\n  "schema_version": 1,\n'
        '  "scope": {\n    "deployment": "descoped"\n  },\n'
        '  "source_answer_sha256": "' + hashlib.sha256(b"No deployment.").hexdigest() + '",\n'
        '  "verification": {}\n}\n')
    assert candidate.reconciliation_json == (
        '{\n  "decision_id": "decision-1",\n  "findings": [],\n'
        '  "requires_repair": false,\n  "schema_version": 1\n}\n')
    with pytest.raises(ValueError):
        prepare(previous=candidate.decisions, receipt_before=candidate.receipt_text,
            policy_before=json.dumps(json.loads(candidate.policy_text)))


def test_replaying_an_older_valid_decision_cannot_select_another_round():
    first = prepare()
    second = prepare(previous=first.decisions, receipt_before=first.receipt_text, policy_before=first.policy_text,
        decision_id="decision-2", question="Is a backend needed?", answer="No backend.")
    with pytest.raises(ValueError):
        prepare(previous=second.decisions, receipt_before=second.receipt_text, policy_before=second.policy_text)
