"""Bounded spawn-process contention and restart tests for inactive journal storage."""

import multiprocessing
from pathlib import Path

import pytest

from harness.element_identity_lifecycle import ElementCreate
from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
from harness.element_identity_request_codec import encode_request
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.integration


def request(child_id="child"):
    return PublicationIntentRequest("a" * 64, "retained recovery", (
        PublicationOperation("lifecycle", child_id, encode_request("lifecycle", (
            ElementCreate("FR-000001", "Scene", "Body", "reserve"),))),
    ))


def prepare_worker(workspace, spec_id, operation_id, child_id, ready, start, results):
    store = IdentityStore.open(Path(workspace))
    ready.put(operation_id)
    if not start.wait(20):
        raise RuntimeError("preparation race was not started")
    try:
        receipt = store.prepare_identity_publication(spec_id=spec_id, operation_id=operation_id,
                                                    request=request(child_id))
        results.put(("prepared", receipt))
    except IdentityStoreError as error:
        results.put(("rejected", str(error)))


def race(workspace, arguments):
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=prepare_worker, args=(str(workspace), *args, ready, start, results))
                 for args in arguments]
    try:
        for process in processes:
            process.start()
        assert sorted(ready.get(timeout=20) for _ in processes) == sorted(args[1] for args in arguments)
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        return outcomes
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)
        for queue in (ready, results):
            queue.close()
            queue.join_thread()


@pytest.mark.parametrize("same_request", [False, True])
def test_competing_preparations_and_exact_request_retries(tmp_path, same_request):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    arguments = [("demo", "pub", "child"),
                 ("demo", "pub" if same_request else "other-pub", "child" if same_request else "other-child")]
    outcomes = race(tmp_path, arguments)
    assert sorted(status for status, _ in outcomes) == (["prepared", "prepared"] if same_request else ["prepared", "rejected"])
    if same_request:
        assert outcomes[0][1] == outcomes[1][1]
    assert store.audit()["table_counts"]["publication_intents"] == "1"
    assert store.lookup(spec_id="demo", element_id="FR-000001") is None
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    print({"same_request": same_request, "outcomes": [status for status, _ in outcomes]})


def test_other_spec_progress_and_global_child_collision_across_processes(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    # Both specs use adoption-free empty intents except for the already reserved
    # demo creation; a cross-spec child collision fails before baseline planning.
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    outcomes = race(tmp_path, [("demo", "pub", "child"), ("demo", "pub", "child")])
    assert all(status == "prepared" for status, _ in outcomes)
    outcomes = race(tmp_path, [("other", "other-pub", "child")])
    assert outcomes[0][0] == "rejected" and "claimed" in outcomes[0][1]
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=other_spec_writer, args=(str(tmp_path), result))
    try:
        process.start()
        assert result.get(timeout=20) == ("FR-000001",)
        process.join(10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        result.close()
        result.join_thread()
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"
    print({"cross_spec_child_collision": "rejected", "other_spec_allocation": "committed"})


def other_spec_writer(workspace, result):
    result.put(IdentityStore.open(Path(workspace)).reserve(spec_id="other", kind="FR", operation_id="other-reserve", count=1))


def commit_then_wait(workspace, state, committed, stop, results):
    store = IdentityStore.open(Path(workspace))
    receipt = store.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request())
    if state == "applied":
        receipt = store.apply_identity_publication(spec_id="demo", operation_id="pub")
    results.put(receipt)
    committed.set()
    stop.wait(30)


@pytest.mark.parametrize("state", ["prepared", "applied"])
def test_process_termination_after_commit_keeps_guard_and_original_receipt(tmp_path, state):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    context = multiprocessing.get_context("spawn")
    committed, stop, results = context.Event(), context.Event(), context.Queue()
    process = context.Process(target=commit_then_wait, args=(str(tmp_path), state, committed, stop, results))
    try:
        process.start()
        assert committed.wait(20)
        receipt = results.get(timeout=20)
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        reopened = IdentityStore.open(tmp_path)
        assert reopened.pending_identity_publication(spec_id="demo")["state"] == state
        if state == "prepared":
            assert reopened.prepare_identity_publication(spec_id="demo", operation_id="pub", request=request()) == receipt
            assert reopened.lookup(spec_id="demo", element_id="FR-000001") is None
        else:
            assert reopened.apply_identity_publication(spec_id="demo", operation_id="pub") == receipt
            assert reopened.lookup(spec_id="demo", element_id="FR-000001")["revision"] == "1"
        with pytest.raises(IdentityStoreError, match="pending"):
            reopened.reserve(spec_id="demo", kind="FR", operation_id="new", count=1)
        reopened.audit()
        print({"terminated_after": state, "restart_state": state, "original_receipt": "retained"})
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        results.close()
        results.join_thread()
