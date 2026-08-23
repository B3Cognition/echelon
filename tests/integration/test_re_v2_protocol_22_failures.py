from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.support.re_v2_layered_workspace import (
    CapturedProviderRequest,
    build_and_commit_fixture,
)


def _request_context(request: CapturedProviderRequest) -> dict[str, object]:
    return dict(request.context)


@pytest.mark.integration
def test_permanently_invalid_domain_fails_only_its_dependency_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.protocol_22.status import protocol_22_status_document

    fixture = build_and_commit_fixture(tmp_path, "invalid-domain")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)

    with fixture.provider:
        result = CliRunner().invoke(app, ["re", "run", "--engine", "v2"])

    assert result.exit_code == 0, result.output
    assert (
        "L1 COMPACT BASELINE INCOMPLETE — TERMINAL WORK-ITEM FAILURES"
        in result.output
    )
    status = protocol_22_status_document(fixture.run_directories()[0])
    assert status["status"] == "failed"
    assert status["continuable"] is False
    assert len(status["failures"]["work_items"]) == 1
    failure = status["failures"]["work_items"][0]
    assert failure["failure_class"] == "minimum_utility"
    assert failure["reason_code"] == "minimum_utility_not_met"
    assert failure["receipt_id"].startswith("sha256:")
    assert status["plan_counts"]["blocked_dependency"] == 3
    assert status["plan_counts"]["blocked_executor"] == 0
    assert status["accepted_siblings"]
    assert {root["source_id"] for root in status["source_roots"]} == {"web"}

    contexts = [_request_context(request) for request in fixture.provider.requests]
    broken_calls = [
        context
        for context in contexts
        if any(
            excerpt["source_relative_path"].startswith("src/broken/")
            for excerpt in context["evidence"]
        )
    ]
    assert len(broken_calls) == 2
    assert len(contexts) == 5
    assert sum(
        context["target_artifact_kind"] == "source-overview"
        for context in contexts
    ) == 1


@pytest.mark.integration
def test_usage_breach_blocks_exact_executor_and_cannot_be_budget_reopened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.status import protocol_22_status_document
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.ledger import ObjectStore

    fixture = build_and_commit_fixture(tmp_path, "executor-breach")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()

    with fixture.provider:
        result = runner.invoke(app, ["re", "run", "--engine", "v2"])
        calls = len(fixture.provider.requests)
        run_dir = fixture.run_directories()[0]
        paths = ReV2Paths.for_run(run_dir)
        events_before = paths.events.read_bytes()
        continued = runner.invoke(
            app,
            ["re", "continue", "--re-token-limit", "999999999"],
        )

    assert result.exit_code == 0, result.output
    assert calls == 1
    assert len(fixture.provider.requests) == calls
    assert continued.exit_code == 2
    assert "terminal protocol-2.2 runs cannot receive budget" in continued.output
    assert paths.events.read_bytes() == events_before

    status = protocol_22_status_document(run_dir)
    assert status["status"] == "failed"
    assert status["continuable"] is False
    assert status["failures"]["work_items"] == []
    assert len(status["failures"]["executors"]) == 1
    failure = status["failures"]["executors"][0]
    assert failure["reason_code"] == "usage_exceeded_reservation"
    assert failure["receipt_id"].startswith("sha256:")
    assert status["plan_counts"]["blocked_executor"] > 0
    assert status["artifact_counts"]["by_kind"]["domain-context-bundle"][
        "accepted"
    ] > 0
    assert status["artifact_counts"]["by_kind"]["domain-baseline"][
        "accepted"
    ] == 0

    ledger = Protocol22Ledger(paths, ObjectStore(paths.objects)).replay()
    assert len(ledger.executor_failures) == 1
    breaching_candidate = next(iter(ledger.executor_failures.values())).candidate_id
    assert breaching_candidate is not None
    accepted_certifications = {
        receipt.certification_receipt_id
        for receipt in ledger.accepted_artifacts.values()
    }
    assert all(
        assessment.certification_receipt_id not in accepted_certifications
        for assessment in ledger.candidate_assessments.values()
        if assessment.candidate_id == breaching_candidate
    )
