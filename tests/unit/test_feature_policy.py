"""Canonical feature-scoped clarification policy tests."""

from __future__ import annotations

from pathlib import Path

import pytest


_MINIMAL_ANSWER = (
    "one static greeting; no auth, persistence, routing, backend, deployment, "
    "or public hosting requirement; bootstrap is in scope; do not require "
    "compliance scan, axe suite, or Playwright visual-regression work"
)


@pytest.mark.unit
def test_derives_immutable_minimal_feature_policy() -> None:
    from echelon.feature_policy import derive_feature_policy

    policy = derive_feature_policy(_MINIMAL_ANSWER, decision_id="DEC-001")

    assert policy["schema_version"] == 1
    assert policy["provenance"] == {
        "decision_id": "DEC-001",
        "source": "user_clarification",
        "immutable": True,
    }
    assert policy["scope"]["deployment"] == "descoped"
    assert policy["scope"]["backend"] == "descoped"
    assert policy["verification"] == {
        "compliance_scan": "not_required",
        "accessibility_suite": "not_required",
        "visual_regression": "not_required",
    }
    assert policy["quality"]["behavioral"] == "waived_for_feature"
    assert policy["quality"]["testability"] == "evaluate_only_if_applicable"


@pytest.mark.unit
def test_persisted_policy_is_immutable_and_rendered_for_agent_context(tmp_path: Path) -> None:
    from echelon.feature_policy import (
        derive_feature_policy,
        persist_feature_policy,
        render_feature_policy,
    )

    policy = derive_feature_policy(_MINIMAL_ANSWER, decision_id="DEC-001")
    path = persist_feature_policy(tmp_path, policy)

    assert path.name == "feature-policy.json"
    assert persist_feature_policy(tmp_path, policy) == path
    rendered = render_feature_policy(policy)
    assert "Authoritative Feature Policy" in rendered
    assert "deployment: descoped" in rendered
    assert "visual_regression: not_required" in rendered

    changed = {**policy, "scope": {**policy["scope"], "deployment": "in_scope"}}
    with pytest.raises(ValueError, match="immutable"):
        persist_feature_policy(tmp_path, changed)


@pytest.mark.unit
def test_reconciliation_retains_refuted_production_assumptions(tmp_path: Path) -> None:
    from echelon.feature_policy import derive_feature_policy, reconcile_feature_artifacts

    (tmp_path / "assumptions.md").write_text(
        "A production-grade, pipeline-proving deliverable requires deployment.\n",
        encoding="utf-8",
    )
    policy = derive_feature_policy(_MINIMAL_ANSWER, decision_id="DEC-001")

    report = reconcile_feature_artifacts(tmp_path, policy)

    assert report["requires_repair"] is True
    assert report["findings"][0]["status"] == "refuted"
    assert report["findings"][0]["artifact"] == "assumptions.md"
    assert "production-grade" in (tmp_path / "feature-policy-reconciliation.md").read_text(encoding="utf-8")


@pytest.mark.unit
def test_feature_quality_waiver_only_changes_effective_thresholds() -> None:
    from echelon.feature_policy import derive_feature_policy
    from harness.quality_scores import effective_quality_gate_thresholds

    policy = derive_feature_policy(_MINIMAL_ANSWER, decision_id="DEC-001")
    defaults = {"behavioral": 0.9, "testability": 0.8, "overall": 0.7}

    assert effective_quality_gate_thresholds(defaults, policy) == {
        "testability": 0.8,
        "overall": 0.7,
    }
    assert defaults == {"behavioral": 0.9, "testability": 0.8, "overall": 0.7}


@pytest.mark.unit
def test_policy_is_included_in_refreshed_run_context(tmp_path: Path) -> None:
    from echelon.context_builder import build_run_context
    from echelon.feature_policy import derive_feature_policy, persist_feature_policy

    run_dir = tmp_path / "runs" / "spec-1"
    persist_feature_policy(
        run_dir / "staging",
        derive_feature_policy(_MINIMAL_ANSWER, decision_id="DEC-001"),
    )

    context = build_run_context(tmp_path, run_dir)

    assert "Authoritative Feature Policy" in (context.context_dir / "current-feature-context.md").read_text(encoding="utf-8")
