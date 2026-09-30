"""Browser baseline proposals are task-bound data, never passing visual receipts."""

import json

import pytest

from harness.verify_result import VerifyResult
from harness.visual_ralph import BrowserBaselineCapture


def _capture():
    return BrowserBaselineCapture(
        candidate_fingerprint="candidate-a",
        verification=VerifyResult(passed=False),
        images={"tests/e2e/checkpoints.spec.ts-snapshots/establishing-chromium.png": b"image-a"},
    )


def test_historical_validation_authenticates_bytes_but_exposes_no_current_proposal(tmp_path):
    from harness.browser_baseline_evidence import (
        BrowserBaselineEvidenceError, read_browser_baseline_observation,
        validate_historical_browser_baseline, write_browser_baseline_receipt,
    )
    args = dict(operation_id="operation-1", task_id="T-010", input_fingerprint="inputs-a")
    ref = write_browser_baseline_receipt(evidence_root=tmp_path, capture=_capture(), **args)
    assert validate_historical_browser_baseline(ref, **args) is None
    for candidate in (None, "candidate-b"):
        with pytest.raises(BrowserBaselineEvidenceError):
            read_browser_baseline_observation(ref, candidate_fingerprint=candidate, **args)
    image = ref.path.parent / "artifacts/0001.png"
    image.write_bytes(b"tampered")
    with pytest.raises(BrowserBaselineEvidenceError, match="artifact digest"):
        validate_historical_browser_baseline(ref, **args)


def test_baseline_proposal_retains_path_and_bytes_without_claiming_pass(tmp_path):
    from harness.browser_baseline_evidence import (
        read_browser_baseline_receipt, write_browser_baseline_receipt,
    )

    ref = write_browser_baseline_receipt(
        evidence_root=tmp_path / "evidence", operation_id="operation-1",
        task_id="T-010", input_fingerprint="inputs-a", capture=_capture(),
    )
    retained = read_browser_baseline_receipt(
        ref, operation_id="operation-1", task_id="T-010",
        candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
    )

    assert list(retained) == ["tests/e2e/checkpoints.spec.ts-snapshots/establishing-chromium.png"]
    assert next(iter(retained.values())).read_bytes() == b"image-a"
    receipt = json.loads(ref.path.read_text(encoding="utf-8"))
    assert receipt["authority"] == "browser-baseline-proposal"
    assert receipt["verification_passed"] is False
    assert receipt["task_id"] == "T-010"


def test_baseline_proposal_round_trips_thirty_three_checkpoint_images(tmp_path):
    from harness.browser_baseline_evidence import (
        read_browser_baseline_receipt, write_browser_baseline_receipt,
    )

    paths = [f"tests/e2e/checkpoints.spec.ts-snapshots/checkpoint-{i:02d}.png" for i in range(33)]
    capture = BrowserBaselineCapture(
        candidate_fingerprint="candidate-a", verification=VerifyResult(passed=True),
        images={path: f"image-{i}".encode() for i, path in enumerate(paths)},
    )
    ref = write_browser_baseline_receipt(
        evidence_root=tmp_path / "evidence", operation_id="operation-1",
        task_id="T-010", input_fingerprint="inputs-a", capture=capture,
    )

    retained = read_browser_baseline_receipt(
        ref, operation_id="operation-1", task_id="T-010",
        candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
    )
    assert list(retained) == paths
    assert retained[paths[-1]].read_bytes() == b"image-32"


def test_baseline_proposal_rejects_aggregate_image_bytes_on_write_and_read(tmp_path, monkeypatch):
    import harness.browser_baseline_evidence as evidence

    capture = BrowserBaselineCapture(
        candidate_fingerprint="candidate-a", verification=VerifyResult(passed=True),
        images={
            f"tests/e2e/checkpoints.spec.ts-snapshots/checkpoint-{i}.png": b"1234"
            for i in range(3)
        },
    )
    args = dict(evidence_root=tmp_path / "evidence", operation_id="operation-1",
                task_id="T-010", input_fingerprint="inputs-a")
    ref = evidence.write_browser_baseline_receipt(**args, capture=capture)
    monkeypatch.setattr(evidence, "MAX_BROWSER_BASELINE_TOTAL_BYTES", 10, raising=False)

    with pytest.raises(evidence.BrowserBaselineEvidenceError, match="image"):
        evidence.write_browser_baseline_receipt(**args, capture=capture)
    with pytest.raises(evidence.BrowserBaselineEvidenceError, match="artifact"):
        evidence.read_browser_baseline_receipt(
            ref, operation_id="operation-1", task_id="T-010",
            candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
        )


def test_browser_run_without_snapshots_retains_pass_or_failure_observation(tmp_path):
    from harness.browser_baseline_evidence import (
        BrowserBaselineEvidenceError, read_browser_baseline_receipt, write_browser_baseline_receipt,
    )

    args = dict(evidence_root=tmp_path / "evidence", operation_id="operation-1",
                task_id="T-010", input_fingerprint="inputs-a")
    empty = BrowserBaselineCapture(
        candidate_fingerprint="candidate-a", verification=VerifyResult(passed=True), images={},
    )
    ref = write_browser_baseline_receipt(**args, capture=empty)
    assert read_browser_baseline_receipt(
        ref, operation_id="operation-1", task_id="T-010",
        candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
    ) == {}
    receipt = json.loads(ref.path.read_text(encoding="utf-8"))
    assert receipt["authority"] == "browser-baseline-proposal"
    assert receipt["verification_passed"] is True
    assert receipt["artifacts"] == []
    failed = write_browser_baseline_receipt(
        **args, capture=BrowserBaselineCapture(
            candidate_fingerprint="candidate-a", verification=VerifyResult(passed=False),
            images={}, diagnostic="playwright_skipped::critical journey",
        ),
    )
    assert read_browser_baseline_receipt(
        failed, operation_id="operation-1", task_id="T-010",
        candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
    ) == {}
    failure_receipt = json.loads(failed.path.read_text(encoding="utf-8"))
    assert failure_receipt["verification_passed"] is False
    assert failure_receipt["verification_diagnostic"] == "playwright_skipped::critical journey"


@pytest.mark.parametrize("changed", ["task_id", "candidate_fingerprint", "input_fingerprint", "operation_id", "artifact"])
def test_baseline_proposal_rejects_wrong_binding_or_changed_bytes(tmp_path, changed):
    from harness.browser_baseline_evidence import (
        BrowserBaselineEvidenceError, read_browser_baseline_receipt,
        write_browser_baseline_receipt,
    )

    ref = write_browser_baseline_receipt(
        evidence_root=tmp_path / "evidence", operation_id="operation-1",
        task_id="T-010", input_fingerprint="inputs-a", capture=_capture(),
    )
    expected = dict(operation_id="operation-1", task_id="T-010",
                    candidate_fingerprint="candidate-a", input_fingerprint="inputs-a")
    if changed == "artifact":
        receipt = json.loads(ref.path.read_text(encoding="utf-8"))
        (ref.path.parent / receipt["artifacts"][0]["path"]).write_bytes(b"changed")
    else:
        expected[changed] = "different"

    with pytest.raises(BrowserBaselineEvidenceError):
        read_browser_baseline_receipt(ref, **expected)


def test_baseline_proposal_rejects_redirected_artifact_directory(tmp_path):
    from harness.browser_baseline_evidence import (
        BrowserBaselineEvidenceError, read_browser_baseline_receipt,
        write_browser_baseline_receipt,
    )

    ref = write_browser_baseline_receipt(
        evidence_root=tmp_path / "evidence", operation_id="operation-1",
        task_id="T-010", input_fingerprint="inputs-a", capture=_capture(),
    )
    artifacts = ref.path.parent / "artifacts"
    outside = tmp_path / "outside"
    artifacts.rename(outside)
    artifacts.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BrowserBaselineEvidenceError):
        read_browser_baseline_receipt(
            ref, operation_id="operation-1", task_id="T-010",
            candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
        )


def test_baseline_proposal_rejects_redirected_receipt_directory(tmp_path):
    from harness.browser_baseline_evidence import (
        BrowserBaselineEvidenceError, read_browser_baseline_receipt,
        write_browser_baseline_receipt,
    )

    ref = write_browser_baseline_receipt(
        evidence_root=tmp_path / "evidence", operation_id="operation-1",
        task_id="T-010", input_fingerprint="inputs-a", capture=_capture(),
    )
    original = ref.path.parent
    outside = tmp_path / "outside"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BrowserBaselineEvidenceError):
        read_browser_baseline_receipt(
            ref, operation_id="operation-1", task_id="T-010",
            candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
        )


def test_unjournaled_capture_can_retry_without_replacing_prior_evidence(tmp_path):
    from harness.browser_baseline_evidence import (
        read_browser_baseline_receipt, write_browser_baseline_receipt,
    )

    args = dict(
        evidence_root=tmp_path / "evidence", operation_id="operation-1",
        task_id="T-010", input_fingerprint="inputs-a",
    )
    first = write_browser_baseline_receipt(**args, capture=_capture())
    second = write_browser_baseline_receipt(**args, capture=_capture())

    assert first.path != second.path
    for ref in (first, second):
        retained = read_browser_baseline_receipt(
            ref, operation_id="operation-1", task_id="T-010",
            candidate_fingerprint="candidate-a", input_fingerprint="inputs-a",
        )
        assert next(iter(retained.values())).read_bytes() == b"image-a"
