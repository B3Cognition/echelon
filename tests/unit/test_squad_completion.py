from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codegen.memory.mempalace_writer import (
    deterministic_requirement_drawer_id,
)
from echelon.telemetry.model import PhaseTimingEvent
from echelon.telemetry.phase_timing import record_phase_start
from echelon.telemetry.store import (
    TelemetryDurabilityError,
    TelemetryStore,
)
import harness.prepared_phase_result as prepared_phase_result_module
import harness.squad_completion as completion_module
from harness.squad_completion import (
    CompletionError,
    CompletionMarker,
    load_prepared_controller_completion,
    prepare_controller_completion,
    persist_completion_effect_receipt,
)
from harness.state_transaction_namespace import (
    validate_pending_controller_completion,
)


def test_default_completion_miner_factory_uses_echelon_requirement_adapter(
    monkeypatch,
    tmp_path,
):
    from harness import squad_completion as completion_module

    calls = []
    sentinel = object()
    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: calls.append((project_root, run_id)) or sentinel,
    )

    result = completion_module._default_completion_miner_factory(tmp_path, "run-123")

    assert result is sentinel
    assert calls == [(tmp_path, "run-123")]


COMPLETION_ID = "a" * 32
VALID_COMPLETION_MARKER = {
    "schema_version": 1,
    "completion_id": COMPLETION_ID,
    "intent_sha256": "b" * 64,
    "publication_binding_sha256": "c" * 64,
    "receipts_sha256": "d" * 64,
    "origin": "routed",
    "step": "journal",
}
ROUTED_ROUTE = {
    "kind": "routed",
    "from_phase": "phase3-plan",
    "to_phase": "phase3-consensus",
    "manual_phase_run": False,
    "record_completion": True,
}
VALID_PUBLICATION_MARKER = {
    "schema_version": 1,
    "transaction_id": "e" * 32,
    "manifest_sha256": "f" * 64,
}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "extra": True},
        lambda value: {**value, "schema_version": True},
        lambda value: {**value, "completion_id": None},
        lambda value: {**value, "completion_id": "A" * 32},
        lambda value: {**value, "intent_sha256": "b" * 63},
        lambda value: {**value, "publication_binding_sha256": None},
        lambda value: {**value, "receipts_sha256": "D" * 64},
        lambda value: {**value, "origin": "provider"},
        lambda value: {**value, "step": "skipped"},
    ],
)
def test_completion_marker_is_exact(mutation) -> None:
    with pytest.raises(ValueError):
        validate_pending_controller_completion(
            mutation(VALID_COMPLETION_MARKER)
        )


def test_completion_marker_returns_an_exact_detached_record() -> None:
    marker = dict(VALID_COMPLETION_MARKER)

    validated = validate_pending_controller_completion(marker)
    marker["step"] = "complete"

    assert validated == VALID_COMPLETION_MARKER
    assert validated is not marker
    assert type(validated) is dict
    assert all(type(value) in {int, str} for value in validated.values())


@pytest.mark.parametrize("missing", sorted(VALID_COMPLETION_MARKER))
def test_completion_marker_rejects_every_missing_field(
    missing: str,
) -> None:
    marker = dict(VALID_COMPLETION_MARKER)
    marker.pop(missing)

    with pytest.raises(ValueError):
        validate_pending_controller_completion(marker)


def test_completion_marker_rejects_dict_and_string_subclasses() -> None:
    class DictSubclass(dict):
        pass

    class StringSubclass(str):
        pass

    with pytest.raises(ValueError):
        validate_pending_controller_completion(
            DictSubclass(VALID_COMPLETION_MARKER)
        )
    for field in (
        "completion_id",
        "intent_sha256",
        "publication_binding_sha256",
        "receipts_sha256",
        "origin",
        "step",
    ):
        marker = dict(VALID_COMPLETION_MARKER)
        marker[field] = StringSubclass(marker[field])
        with pytest.raises(ValueError):
            validate_pending_controller_completion(marker)


@pytest.mark.parametrize("origin", ["routed", "terminal"])
@pytest.mark.parametrize(
    "step",
    [
        "awaiting_publication",
        "journal",
        "timing",
        "checkpoint",
        "context",
        "mining",
        "complete",
    ],
)
def test_completion_marker_accepts_every_legal_origin_and_step(
    origin: str,
    step: str,
) -> None:
    marker = {
        **VALID_COMPLETION_MARKER,
        "origin": origin,
        "step": step,
    }

    assert validate_pending_controller_completion(marker) == marker


@pytest.mark.parametrize(
    "code",
    [
        "intent_invalid",
        "intent_mismatch",
        "receipts_invalid",
        "receipts_mismatch",
        "stage_corrupt",
        "stage_missing",
        "stage_io",
    ],
)
def test_completion_error_preserves_only_bounded_codes(code: str) -> None:
    error = CompletionError(code)

    assert error.code == code
    assert str(error) == code


def test_completion_error_sanitizes_unbounded_diagnostic() -> None:
    error = CompletionError("/secret/path and provider output")

    assert error.code == "stage_io"
    assert str(error) == "stage_io"


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    squad_dir = project_root / "runs" / "spec-1"
    squad_dir.mkdir(parents=True)
    return project_root, squad_dir


def _prepare_minimal(
    tmp_path: Path,
    **overrides: object,
):
    project_root, squad_dir = _roots(tmp_path)
    arguments: dict[str, object] = {
        "completion_id": COMPLETION_ID,
        "origin": "routed",
        "publication": {"kind": "none"},
        "route": ROUTED_ROUTE,
        "effect_plan": (),
        "checkpoint_prestate": {"kind": "none"},
        "context_reason": "routed phase completion",
        "mine_phase_a": False,
        "judgment_payload_sha256": (),
        "judgments": (),
    }
    arguments.update(overrides)
    return (
        project_root,
        squad_dir,
        prepare_controller_completion(
            project_root,
            squad_dir,
            **arguments,
        ),
    )


def _assert_completion_error(code: str, action) -> None:
    with pytest.raises(CompletionError) as raised:
        action()
    assert raised.value.code == code
    assert str(raised.value) == code


def test_prepare_completion_seals_exact_canonical_intent_and_empty_receipts(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    transaction_root = (
        squad_dir / ".completion-outbox" / COMPLETION_ID
    )
    intent_bytes = (transaction_root / "intent.json").read_bytes()
    receipts_bytes = (transaction_root / "receipts.json").read_bytes()
    intent = json.loads(intent_bytes)
    receipts = json.loads(receipts_bytes)

    assert intent_bytes == (
        json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    assert intent == {
        "schema_version": 1,
        "completion_id": COMPLETION_ID,
        "origin": "routed",
        "publication": {"kind": "none"},
        "route": ROUTED_ROUTE,
        "effect_plan": [],
        "checkpoint_prestate": {"kind": "none"},
        "context_reason": "routed phase completion",
        "mine_phase_a": False,
        "judgment_payload_sha256": [],
        "judgments": [],
    }
    assert receipts == {
        "schema_version": 1,
        "completion_id": COMPLETION_ID,
        "effects": {},
    }
    assert prepared.marker == CompletionMarker(
        schema_version=1,
        completion_id=COMPLETION_ID,
        intent_sha256=hashlib.sha256(intent_bytes).hexdigest(),
        publication_binding_sha256=hashlib.sha256(
            b'{"kind":"none"}\n'
        ).hexdigest(),
        receipts_sha256=hashlib.sha256(receipts_bytes).hexdigest(),
        origin="routed",
        step="complete",
    )
    assert prepared.marker.to_dict() == (
        validate_pending_controller_completion(prepared.marker.to_dict())
    )

    loaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker.to_dict(),
    )
    assert loaded.marker == prepared.marker
    assert loaded.intent == prepared.intent


@pytest.mark.parametrize(
    ("effect_plan", "checkpoint_prestate"),
    [
        ((), {"kind": "git_head", "head": "1" * 40}),
        (("checkpoint",), {"kind": "none"}),
        (("checkpoint",), {"kind": "git_head", "head": "g" * 40}),
        (
            ("checkpoint",),
            {"kind": "git_head", "head": "1" * 40, "extra": True},
        ),
    ],
)
def test_prepare_completion_binds_exact_checkpoint_prestate(
    tmp_path: Path,
    effect_plan: tuple[str, ...],
    checkpoint_prestate: dict[str, object],
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            effect_plan=effect_plan,
            checkpoint_prestate=checkpoint_prestate,
        ),
    )


def test_prepare_completion_accepts_sha1_or_sha256_checkpoint_head(
    tmp_path: Path,
) -> None:
    for index, head in enumerate(("1" * 40, "2" * 64), start=1):
        project_root = tmp_path / f"project-{index}"
        squad_dir = project_root / "runs" / "spec-1"
        squad_dir.mkdir(parents=True)

        prepared = prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=f"{index:x}" * 32,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=("checkpoint",),
            checkpoint_prestate={"kind": "git_head", "head": head},
            context_reason="checkpoint",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )

        assert prepared.intent.checkpoint_prestate == {
            "kind": "git_head",
            "head": head,
        }


def test_prepare_completion_accepts_exact_external_publication_union(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(
        tmp_path,
        publication={
            "kind": "external",
            "marker": VALID_PUBLICATION_MARKER,
        },
    )

    assert prepared.intent.publication == {
        "kind": "external",
        "marker": VALID_PUBLICATION_MARKER,
    }
    assert prepared.marker.step == "awaiting_publication"
    assert prepared.marker.publication_binding_sha256 == hashlib.sha256(
        (
            json.dumps(
                {
                    "kind": "external",
                    "marker": VALID_PUBLICATION_MARKER,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()


def test_prepare_completion_accepts_exact_terminal_route_union(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(
        tmp_path,
        origin="terminal",
        route={"kind": "terminal", "terminal_phase": "DONE"},
    )

    assert prepared.intent.route == {
        "kind": "terminal",
        "terminal_phase": "DONE",
    }
    assert prepared.marker.origin == "terminal"
    assert prepared.marker.step == "complete"


@pytest.mark.parametrize(
    "overrides",
    [
        {"publication": None},
        {
            "publication": {
                "kind": "none",
                "marker": VALID_PUBLICATION_MARKER,
            }
        },
        {"publication": {"kind": "external"}},
        {
            "publication": {
                "kind": "external",
                "marker": {
                    **VALID_PUBLICATION_MARKER,
                    "transaction_id": "unsafe",
                },
            }
        },
        {
            "publication": {
                "kind": "external",
                "marker": VALID_PUBLICATION_MARKER,
                "extra": None,
            }
        },
        {"route": None},
        {
            "route": {
                **ROUTED_ROUTE,
                "extra": None,
            }
        },
        {
            "route": {
                "kind": "terminal",
                "terminal_phase": "DONE",
                "from_phase": "phase4-document",
            },
            "origin": "terminal",
        },
        {
            "route": {
                "kind": "terminal",
                "terminal_phase": None,
            },
            "origin": "terminal",
        },
        {
            "route": {
                "kind": "terminal",
                "terminal_phase": "DONE",
            },
            "origin": "routed",
        },
        {
            "route": ROUTED_ROUTE,
            "origin": "terminal",
        },
    ],
)
def test_prepare_completion_rejects_non_exact_tagged_unions(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(tmp_path, **overrides),
    )


@pytest.mark.parametrize(
    "completion_id",
    [
        None,
        "a" * 31,
        "A" * 32,
        "g" * 32,
    ],
)
def test_prepare_completion_rejects_invalid_completion_id(
    tmp_path: Path,
    completion_id: object,
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            completion_id=completion_id,
        ),
    )


def test_prepare_completion_rejects_completion_id_string_subclass(
    tmp_path: Path,
) -> None:
    class StringSubclass(str):
        pass

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            completion_id=StringSubclass(COMPLETION_ID),
        ),
    )


@pytest.mark.parametrize(
    "route",
    [
        {**ROUTED_ROUTE, "manual_phase_run": 0},
        {**ROUTED_ROUTE, "record_completion": 1},
        {**ROUTED_ROUTE, "from_phase": ""},
        {**ROUTED_ROUTE, "to_phase": ""},
        {**ROUTED_ROUTE, "from_phase": "x" * 1_025},
        {**ROUTED_ROUTE, "to_phase": "x" * 1_025},
    ],
)
def test_prepare_completion_rejects_invalid_routed_scalars(
    tmp_path: Path,
    route: dict[str, object],
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(tmp_path, route=route),
    )


@pytest.mark.parametrize(
    "terminal_phase",
    ["", "x" * 1_025],
)
def test_prepare_completion_rejects_invalid_terminal_phase(
    tmp_path: Path,
    terminal_phase: str,
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            origin="terminal",
            route={
                "kind": "terminal",
                "terminal_phase": terminal_phase,
            },
        ),
    )


@pytest.mark.parametrize("context_reason", ["", "x" * 4_097])
def test_prepare_completion_rejects_invalid_context_reason(
    tmp_path: Path,
    context_reason: str,
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            context_reason=context_reason,
        ),
    )


def test_prepare_completion_rejects_context_string_subclass(
    tmp_path: Path,
) -> None:
    class StringSubclass(str):
        pass

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            context_reason=StringSubclass("context"),
        ),
    )


@pytest.mark.parametrize(
    "effect_plan",
    [
        ("journal", "journal"),
        ("checkpoint", "timing"),
        ("context", "checkpoint"),
        ("unknown",),
        ("journal", None),
    ],
)
def test_prepare_completion_rejects_invalid_effect_plan(
    tmp_path: Path,
    effect_plan: tuple[object, ...],
) -> None:
    checkpoint_prestate = (
        {"kind": "git_head", "head": "1" * 40}
        if "checkpoint" in effect_plan
        else {"kind": "none"}
    )

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            effect_plan=effect_plan,
            checkpoint_prestate=checkpoint_prestate,
        ),
    )


def test_terminal_completion_permits_only_mining_effect(
    tmp_path: Path,
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            origin="terminal",
            route={"kind": "terminal", "terminal_phase": "DONE"},
            effect_plan=("journal",),
        ),
    )

    _, _, prepared = _prepare_minimal(
        tmp_path / "mining",
        origin="terminal",
        route={"kind": "terminal", "terminal_phase": "DONE"},
        effect_plan=("mining",),
        mine_phase_a=True,
    )
    assert prepared.marker.step == "mining"


@pytest.mark.parametrize(
    "effect_plan",
    [
        (),
        ("journal",),
        ("checkpoint",),
        ("journal", "timing", "checkpoint"),
    ],
)
def test_commander_recovery_requires_journal_then_checkpoint(
    tmp_path: Path,
    effect_plan: tuple[str, ...],
) -> None:
    commander_route = {
        **ROUTED_ROUTE,
        "record_completion": False,
    }
    checkpoint_prestate = (
        {"kind": "git_head", "head": "1" * 40}
        if "checkpoint" in effect_plan
        else {"kind": "none"}
    )

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            route=commander_route,
            effect_plan=effect_plan,
            checkpoint_prestate=checkpoint_prestate,
        ),
    )

    _, _, prepared = _prepare_minimal(
        tmp_path / "valid",
        route=commander_route,
        effect_plan=("journal", "checkpoint"),
        checkpoint_prestate={"kind": "git_head", "head": "1" * 40},
    )
    assert prepared.intent.effect_plan == ("journal", "checkpoint")


@pytest.mark.parametrize(
    ("effect_plan", "mine_phase_a"),
    [
        ((), True),
        (("mining",), False),
    ],
)
def test_prepare_completion_binds_mining_flag_to_effect_plan(
    tmp_path: Path,
    effect_plan: tuple[str, ...],
    mine_phase_a: bool,
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            effect_plan=effect_plan,
            mine_phase_a=mine_phase_a,
        ),
    )


@pytest.mark.parametrize(
    ("publication", "effect_plan", "expected_step"),
    [
        ({"kind": "none"}, (), "complete"),
        ({"kind": "none"}, ("journal",), "journal"),
        (
            {
                "kind": "external",
                "marker": VALID_PUBLICATION_MARKER,
            },
            ("journal",),
            "awaiting_publication",
        ),
    ],
)
def test_prepare_completion_derives_exact_initial_marker_step(
    tmp_path: Path,
    publication: dict[str, object],
    effect_plan: tuple[str, ...],
    expected_step: str,
) -> None:
    _, _, prepared = _prepare_minimal(
        tmp_path,
        publication=publication,
        effect_plan=effect_plan,
    )

    assert prepared.marker.step == expected_step


def _payload_digest(payload: dict[str, object]) -> str:
    return prepared_phase_result_module._canonical_payload_sha256(payload)


def test_prepare_completion_detaches_exact_judgment_and_quarantine(
    tmp_path: Path,
) -> None:
    echelon_result = {
        "verdict": "DONE",
        "state_updates": {"next_phase": "phase4-document"},
        "journal_entries": [{"kind": "note", "details": {"items": ["x"]}}],
    }
    quarantined = {"attempted_status": "done"}
    judgment = {
        "echelon_result": echelon_result,
        "quarantined_state_updates": quarantined,
    }
    digest = _payload_digest(echelon_result)

    _, _, prepared = _prepare_minimal(
        tmp_path,
        judgment_payload_sha256=(digest,),
        judgments=(judgment,),
    )
    echelon_result["verdict"] = "MUTATED"
    quarantined["attempted_status"] = "mutated"

    assert prepared.intent.judgment_payload_sha256 == (digest,)
    assert prepared.intent.judgments == (
        {
            "echelon_result": {
                "verdict": "DONE",
                "state_updates": {
                    "next_phase": "phase4-document"
                },
                "journal_entries": [
                    {
                        "kind": "note",
                        "details": {"items": ["x"]},
                    }
                ],
            },
            "quarantined_state_updates": {
                "attempted_status": "done"
            },
        },
    )


@pytest.mark.parametrize(
    ("digests", "judgments"),
    [
        ((), ({"echelon_result": {}, "quarantined_state_updates": {}},)),
        (("0" * 64,), ()),
        (
            ("0" * 64,),
            (
                {
                    "echelon_result": {},
                    "quarantined_state_updates": {},
                },
            ),
        ),
        (
            (_payload_digest({}),),
            (
                {
                    "echelon_result": {},
                    "quarantined_state_updates": {},
                    "extra": None,
                },
            ),
        ),
        (
            (_payload_digest({}),),
            (
                {
                    "echelon_result": {},
                    "quarantined_state_updates": None,
                },
            ),
        ),
        (
            (_payload_digest({}),),
            (
                {
                    "echelon_result": None,
                    "quarantined_state_updates": {},
                },
            ),
        ),
    ],
)
def test_prepare_completion_rejects_unbound_judgment_records(
    tmp_path: Path,
    digests: tuple[str, ...],
    judgments: tuple[dict[str, object], ...],
) -> None:
    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            judgment_payload_sha256=digests,
            judgments=judgments,
        ),
    )


def test_prepare_completion_rejects_concrete_collection_subclasses(
    tmp_path: Path,
) -> None:
    class DictSubclass(dict):
        pass

    class ListSubclass(list):
        pass

    for index, (judgments, digest_payload) in enumerate(
        (
            (
                DictSubclass(
                    {
                        "echelon_result": {},
                        "quarantined_state_updates": {},
                    }
                ),
                {},
            ),
            (
                {
                    "echelon_result": {
                        "values": ListSubclass([1, 2, 3])
                    },
                    "quarantined_state_updates": {},
                },
                {"values": [1, 2, 3]},
            ),
        )
    ):
        _assert_completion_error(
            "intent_invalid",
            lambda judgments=judgments, index=index: _prepare_minimal(
                tmp_path / str(index),
                judgment_payload_sha256=(
                    _payload_digest(digest_payload),
                ),
                judgments=(judgments,),
            ),
        )


def _nested_list(depth: int) -> list[object]:
    value: list[object] = []
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize(
    "untrusted_value",
    [
        _nested_list(34),
        [None] * 10_001,
        "x" * 1_000_001,
        1 << 63,
        float("inf"),
        float("nan"),
    ],
)
def test_prepare_completion_enforces_prepared_result_detachment_limits(
    tmp_path: Path,
    untrusted_value: object,
) -> None:
    judgment = {
        "echelon_result": {},
        "quarantined_state_updates": {"value": untrusted_value},
    }

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            judgment_payload_sha256=(_payload_digest({}),),
            judgments=(judgment,),
        ),
    )


def test_prepare_completion_rejects_cyclic_judgment_payload(
    tmp_path: Path,
) -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    judgment = {
        "echelon_result": {},
        "quarantined_state_updates": {"value": cycle},
    }

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            judgment_payload_sha256=(_payload_digest({}),),
            judgments=(judgment,),
        ),
    )


def test_prepare_completion_rejects_aggregate_intent_over_four_mib(
    tmp_path: Path,
) -> None:
    judgment = {
        "echelon_result": {},
        "quarantined_state_updates": {
            f"chunk_{index}": "x" * 900_000
            for index in range(5)
        },
    }

    _assert_completion_error(
        "intent_invalid",
        lambda: _prepare_minimal(
            tmp_path,
            judgment_payload_sha256=(_payload_digest({}),),
            judgments=(judgment,),
        ),
    )
    assert not (
        tmp_path
        / "project"
        / "runs"
        / "spec-1"
        / ".completion-outbox"
        / COMPLETION_ID
    ).exists()


def test_prepare_completion_rejects_transaction_reuse_without_overwrite(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(tmp_path)
    intent_before = (
        prepared._transaction_root / "intent.json"
    ).read_bytes()

    _assert_completion_error(
        "stage_corrupt",
        lambda: prepare_controller_completion(
            tmp_path / "project",
            tmp_path / "project" / "runs" / "spec-1",
            completion_id=COMPLETION_ID,
            origin="terminal",
            publication={"kind": "none"},
            route={"kind": "terminal", "terminal_phase": "DONE"},
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="replacement",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )
    assert (
        prepared._transaction_root / "intent.json"
    ).read_bytes() == intent_before


def test_load_completion_rejects_missing_intent_or_receipts(
    tmp_path: Path,
) -> None:
    for filename in ("intent.json", "receipts.json"):
        project_root, squad_dir, prepared = _prepare_minimal(
            tmp_path / filename
        )
        (prepared._transaction_root / filename).unlink()

        _assert_completion_error(
            "stage_missing",
            lambda: load_prepared_controller_completion(
                project_root,
                squad_dir,
                prepared.marker,
            ),
        )


@pytest.mark.parametrize(
    ("filename", "marker_field", "expected_code"),
    [
        ("intent.json", "intent_sha256", "intent_invalid"),
        ("receipts.json", "receipts_sha256", "receipts_invalid"),
    ],
)
def test_load_completion_rejects_noncanonical_stage_documents(
    tmp_path: Path,
    filename: str,
    marker_field: str,
    expected_code: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    path = prepared._transaction_root / filename
    decoded = json.loads(path.read_bytes())
    noncanonical = json.dumps(decoded, indent=2).encode("utf-8")
    path.write_bytes(noncanonical)
    marker = replace(
        prepared.marker,
        **{marker_field: hashlib.sha256(noncanonical).hexdigest()},
    )

    _assert_completion_error(
        expected_code,
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )


@pytest.mark.parametrize("mutation", ["missing", "extra", "null"])
def test_load_completion_rejects_non_exact_intent_top_level(
    tmp_path: Path,
    mutation: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    path = prepared._transaction_root / "intent.json"
    intent = json.loads(path.read_bytes())
    if mutation == "missing":
        intent.pop("context_reason")
    elif mutation == "extra":
        intent["extra"] = None
    else:
        intent["context_reason"] = None
    intent_bytes = (
        json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.write_bytes(intent_bytes)
    marker = replace(
        prepared.marker,
        intent_sha256=hashlib.sha256(intent_bytes).hexdigest(),
    )

    _assert_completion_error(
        "intent_invalid",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )


@pytest.mark.parametrize(
    "untrusted_value",
    [
        1 << 80,
        _nested_list(34),
        "x" * 1_000_001,
    ],
    ids=["large_integer", "deep_value", "long_string"],
)
def test_load_completion_reapplies_intent_detachment_bounds(
    tmp_path: Path,
    untrusted_value: object,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        judgment_payload_sha256=(_payload_digest({}),),
        judgments=(
            {
                "echelon_result": {},
                "quarantined_state_updates": {},
            },
        ),
    )
    path = prepared._transaction_root / "intent.json"
    intent = json.loads(path.read_bytes())
    intent["judgments"][0]["quarantined_state_updates"] = {
        "value": untrusted_value
    }
    intent_bytes = (
        json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.write_bytes(intent_bytes)
    marker = replace(
        prepared.marker,
        intent_sha256=hashlib.sha256(intent_bytes).hexdigest(),
    )

    _assert_completion_error(
        "intent_invalid",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )


def test_load_completion_bounds_json_integer_digit_conversion(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        judgment_payload_sha256=(_payload_digest({}),),
        judgments=(
            {
                "echelon_result": {},
                "quarantined_state_updates": {},
            },
        ),
    )
    path = prepared._transaction_root / "intent.json"
    intent_bytes = path.read_bytes()
    oversized_integer = b"9" * 5_000
    mutated = intent_bytes.replace(
        b'"quarantined_state_updates":{}',
        b'"quarantined_state_updates":{"value":'
        + oversized_integer
        + b"}",
    )
    assert mutated != intent_bytes
    path.write_bytes(mutated)
    marker = replace(
        prepared.marker,
        intent_sha256=hashlib.sha256(mutated).hexdigest(),
    )

    _assert_completion_error(
        "intent_invalid",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )

@pytest.mark.parametrize(
    ("filename", "expected_code"),
    [
        ("intent.json", "intent_mismatch"),
        ("receipts.json", "receipts_mismatch"),
    ],
)
def test_load_completion_rejects_marker_document_digest_mismatch(
    tmp_path: Path,
    filename: str,
    expected_code: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    path = prepared._transaction_root / filename
    path.write_bytes(path.read_bytes() + b" ")

    _assert_completion_error(
        expected_code,
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


@pytest.mark.parametrize(
    "marker",
    [
        replace(
            CompletionMarker(
                schema_version=1,
                completion_id=COMPLETION_ID,
                intent_sha256="b" * 64,
                publication_binding_sha256="c" * 64,
                receipts_sha256="d" * 64,
                origin="routed",
                step="complete",
            ),
            publication_binding_sha256="0" * 64,
        ),
        replace(
            CompletionMarker(
                schema_version=1,
                completion_id=COMPLETION_ID,
                intent_sha256="b" * 64,
                publication_binding_sha256="c" * 64,
                receipts_sha256="d" * 64,
                origin="routed",
                step="complete",
            ),
            origin="terminal",
        ),
    ],
)
def test_load_completion_rejects_marker_intent_binding_mismatch(
    tmp_path: Path,
    marker: CompletionMarker,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    marker = replace(
        marker,
        intent_sha256=prepared.marker.intent_sha256,
        receipts_sha256=prepared.marker.receipts_sha256,
        publication_binding_sha256=(
            marker.publication_binding_sha256
            if marker.publication_binding_sha256 == "0" * 64
            else prepared.marker.publication_binding_sha256
        ),
    )

    _assert_completion_error(
        "intent_mismatch",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )


def _rewrite_receipts(
    prepared,
    receipts: dict[str, object],
    *,
    step: str | None = None,
) -> CompletionMarker:
    receipts_bytes = (
        json.dumps(receipts, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    (prepared._transaction_root / "receipts.json").write_bytes(
        receipts_bytes
    )
    return replace(
        prepared.marker,
        receipts_sha256=hashlib.sha256(receipts_bytes).hexdigest(),
        step=step or prepared.marker.step,
    )


@pytest.mark.parametrize(
    ("receipts", "step", "expected_code"),
    [
        (
            {
                "completion_id": COMPLETION_ID,
                "effects": {},
            },
            "journal",
            "receipts_invalid",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {},
                "extra": None,
            },
            "journal",
            "receipts_invalid",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": "b" * 32,
                "effects": {},
            },
            "journal",
            "receipts_invalid",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {"timing": {}},
            },
            "journal",
            "receipts_invalid",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {"unknown": {}},
            },
            "journal",
            "receipts_invalid",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {"journal": None},
            },
            "journal",
            "receipts_invalid",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {},
            },
            "timing",
            "receipts_mismatch",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {},
            },
            "awaiting_publication",
            "intent_mismatch",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {},
            },
            "complete",
            "receipts_mismatch",
        ),
        (
            {
                "schema_version": 1,
                "completion_id": COMPLETION_ID,
                "effects": {
                    "journal": {},
                    "timing": {},
                },
            },
            "journal",
            "receipts_mismatch",
        ),
    ],
)
def test_load_completion_rejects_invalid_receipt_prefix_or_marker_step(
    tmp_path: Path,
    receipts: dict[str, object],
    step: str,
    expected_code: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("journal", "timing"),
    )
    marker = _rewrite_receipts(prepared, receipts, step=step)

    _assert_completion_error(
        expected_code,
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )


def test_load_completion_accepts_exact_one_ahead_receipt_prefix(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("journal", "timing"),
    )
    receipts = {
        "schema_version": 1,
        "completion_id": COMPLETION_ID,
        "effects": {"journal": {"schema_version": 1}},
    }
    receipts_bytes = (
        json.dumps(receipts, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    (prepared._transaction_root / "receipts.json").write_bytes(
        receipts_bytes
    )

    loaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    assert loaded.marker.receipts_sha256 != hashlib.sha256(
        receipts_bytes
    ).hexdigest()
    assert loaded.receipts["effects"] == {
        "journal": {"schema_version": 1}
    }


def test_load_completion_rejects_one_ahead_receipt_with_unbound_prior_prefix(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("journal", "timing"),
    )
    receipts = {
        "schema_version": 1,
        "completion_id": COMPLETION_ID,
        "effects": {"journal": {"schema_version": 1}},
    }
    (prepared._transaction_root / "receipts.json").write_bytes(
        (
            json.dumps(
                receipts,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    unbound_marker = replace(
        prepared.marker,
        receipts_sha256="0" * 64,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            unbound_marker,
        ),
    )


@pytest.mark.parametrize(
    "untrusted_value",
    [1 << 80, _nested_list(34)],
    ids=["large_integer", "deep_value"],
)
def test_load_completion_reapplies_receipt_detachment_bounds(
    tmp_path: Path,
    untrusted_value: object,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("journal",),
    )
    receipts = {
        "schema_version": 1,
        "completion_id": COMPLETION_ID,
        "effects": {"journal": {"value": untrusted_value}},
    }
    (prepared._transaction_root / "receipts.json").write_bytes(
        (
            json.dumps(
                receipts,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )

    _assert_completion_error(
        "receipts_invalid",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )


@pytest.mark.parametrize(
    ("filename", "maximum", "marker_field", "expected_code"),
    [
        (
            "intent.json",
            4_194_304,
            "intent_sha256",
            "intent_invalid",
        ),
        (
            "receipts.json",
            1_048_576,
            "receipts_sha256",
            "receipts_invalid",
        ),
    ],
)
def test_load_completion_rejects_oversized_stage_documents_without_reading(
    tmp_path: Path,
    filename: str,
    maximum: int,
    marker_field: str,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    oversized = b"x" * (maximum + 1)
    path = prepared._transaction_root / filename
    path.write_bytes(oversized)
    marker = replace(
        prepared.marker,
        **{marker_field: hashlib.sha256(oversized).hexdigest()},
    )

    oversized_inode = path.stat().st_ino
    real_read = completion_module.os.read

    def explode_read(fd: int, length: int):
        if os.fstat(fd).st_ino == oversized_inode:
            raise AssertionError(
                "oversized stage must be rejected before read"
            )
        return real_read(fd, length)

    monkeypatch.setattr(completion_module.os, "read", explode_read)

    _assert_completion_error(
        expected_code,
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            marker,
        ),
    )


@pytest.mark.parametrize("attack_kind", ["symlink", "fifo", "directory"])
def test_load_completion_rejects_non_regular_intent_without_blocking(
    tmp_path: Path,
    attack_kind: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    intent_path = prepared._transaction_root / "intent.json"
    intent_path.unlink()
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    if attack_kind == "symlink":
        intent_path.symlink_to(outside)
    elif attack_kind == "fifo":
        os.mkfifo(intent_path)
    else:
        intent_path.mkdir()

    _assert_completion_error(
        "intent_invalid",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )
    assert outside.read_text(encoding="utf-8") == "outside"


@pytest.mark.parametrize("attack_kind", ["symlink", "fifo", "directory"])
def test_load_completion_rejects_non_regular_receipts_without_blocking(
    tmp_path: Path,
    attack_kind: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    receipts_path = prepared._transaction_root / "receipts.json"
    receipts_path.unlink()
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    if attack_kind == "symlink":
        receipts_path.symlink_to(outside)
    elif attack_kind == "fifo":
        os.mkfifo(receipts_path)
    else:
        receipts_path.mkdir()

    _assert_completion_error(
        "receipts_invalid",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )
    assert outside.read_text(encoding="utf-8") == "outside"


@pytest.mark.parametrize("attack_kind", ["symlink", "file"])
def test_load_completion_rejects_replaced_transaction_root(
    tmp_path: Path,
    attack_kind: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_minimal(tmp_path)
    transaction_root = prepared._transaction_root
    shutil.rmtree(transaction_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    if attack_kind == "symlink":
        transaction_root.symlink_to(outside, target_is_directory=True)
    else:
        transaction_root.write_text("not a directory", encoding="utf-8")

    _assert_completion_error(
        "stage_corrupt",
        lambda: load_prepared_controller_completion(
            project_root,
            squad_dir,
            prepared.marker,
        ),
    )
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_completion_views_return_detached_values(
    tmp_path: Path,
) -> None:
    echelon_result = {"verdict": "DONE"}
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        judgment_payload_sha256=(_payload_digest(echelon_result),),
        judgments=(
            {
                "echelon_result": echelon_result,
                "quarantined_state_updates": {"status": "done"},
            },
        ),
    )
    publication = prepared.intent.publication
    route = prepared.intent.route
    checkpoint = prepared.intent.checkpoint_prestate
    judgments = prepared.intent.judgments
    receipts = prepared.receipts
    publication["kind"] = "mutated"
    route["from_phase"] = "mutated"
    checkpoint["kind"] = "mutated"
    judgments[0]["echelon_result"]["verdict"] = "MUTATED"
    receipts["effects"]["forged"] = {}

    loaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    assert loaded.intent.publication == {"kind": "none"}
    assert loaded.intent.route == ROUTED_ROUTE
    assert loaded.intent.checkpoint_prestate == {"kind": "none"}
    assert loaded.intent.judgments[0]["echelon_result"] == {
        "verdict": "DONE"
    }
    assert loaded.receipts["effects"] == {}


def test_prepare_completion_rejects_symlinked_outbox(
    tmp_path: Path,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (squad_dir / ".completion-outbox").symlink_to(
        outside,
        target_is_directory=True,
    )

    _assert_completion_error(
        "stage_corrupt",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )
    assert list(outside.iterdir()) == []


def test_completion_discard_is_idempotent(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(tmp_path)

    prepared.discard()
    prepared.discard()

    assert not prepared._transaction_root.exists()


def test_completion_discard_rejects_replaced_symlink_root(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(tmp_path)
    transaction_root = prepared._transaction_root
    shutil.rmtree(transaction_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    transaction_root.symlink_to(outside, target_is_directory=True)

    _assert_completion_error("stage_corrupt", prepared.discard)
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_completion_discard_rejects_real_directory_replacement(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(tmp_path)
    transaction_root = prepared._transaction_root
    original_root = transaction_root.with_name(f"{COMPLETION_ID}-original")
    transaction_root.rename(original_root)
    transaction_root.mkdir()
    sentinel = transaction_root / "unrelated-user-data"
    sentinel.write_text("preserve", encoding="utf-8")

    _assert_completion_error("stage_corrupt", prepared.discard)

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert (original_root / "intent.json").is_file()


def test_prepare_completion_replace_failure_cleans_unreferenced_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)

    def fail_replace(*_args, **_kwargs):
        raise OSError("injected replace failure with /secret/path")

    monkeypatch.setattr(completion_module.os, "replace", fail_replace)

    _assert_completion_error(
        "stage_io",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )
    assert not (
        squad_dir / ".completion-outbox" / COMPLETION_ID
    ).exists()


def test_prepare_completion_second_replace_failure_cleans_partial_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    real_replace = completion_module.os.replace
    calls = 0

    def fail_second_replace(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(
        completion_module.os,
        "replace",
        fail_second_replace,
    )

    _assert_completion_error(
        "stage_io",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )
    assert calls == 2
    assert not (
        squad_dir / ".completion-outbox" / COMPLETION_ID
    ).exists()


def test_prepare_completion_transaction_directory_fsync_failure_cleans_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    real_fsync = completion_module.os.fsync
    calls = 0

    def fail_transaction_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(
        completion_module.os,
        "fsync",
        fail_transaction_directory_fsync,
    )

    _assert_completion_error(
        "stage_io",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )
    assert calls >= 3
    assert not (
        squad_dir / ".completion-outbox" / COMPLETION_ID
    ).exists()


def test_prepare_completion_reread_failure_cleans_unreferenced_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)

    def fail_read(*_args, **_kwargs):
        raise CompletionError("stage_corrupt")

    monkeypatch.setattr(completion_module, "_read_regular", fail_read)

    _assert_completion_error(
        "stage_corrupt",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )
    assert not (
        squad_dir / ".completion-outbox" / COMPLETION_ID
    ).exists()


def test_prepare_failure_cleanup_rejects_real_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    original_root: Path | None = None
    sentinel: Path | None = None

    def swap_root_then_fail(_project_root, loaded_squad_dir, marker):
        nonlocal original_root, sentinel
        transaction_root = (
            loaded_squad_dir
            / ".completion-outbox"
            / marker.completion_id
        )
        original_root = transaction_root.with_name(
            f"{marker.completion_id}-original"
        )
        transaction_root.rename(original_root)
        transaction_root.mkdir()
        sentinel = transaction_root / "unrelated-user-data"
        sentinel.write_text("preserve", encoding="utf-8")
        raise CompletionError("stage_corrupt")

    monkeypatch.setattr(
        completion_module,
        "load_prepared_controller_completion",
        swap_root_then_fail,
    )

    _assert_completion_error(
        "stage_corrupt",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )

    assert sentinel is not None
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert original_root is not None
    assert (original_root / "intent.json").is_file()
    assert (original_root / "receipts.json").is_file()


def test_prepare_second_document_write_rejects_transaction_root_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    real_atomic_write = completion_module._atomic_write
    calls = 0
    original_root: Path | None = None
    sentinel: Path | None = None

    def swap_before_second_write(
        directory: Path,
        name: str,
        content: bytes,
        *,
        expected_identity: tuple[int, int, int],
    ) -> None:
        nonlocal calls, original_root, sentinel
        calls += 1
        if calls == 2:
            original_root = directory.with_name(
                f"{COMPLETION_ID}-original"
            )
            directory.rename(original_root)
            directory.mkdir()
            sentinel = directory / "unrelated-user-data"
            sentinel.write_text("preserve", encoding="utf-8")
        real_atomic_write(
            directory,
            name,
            content,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        completion_module,
        "_atomic_write",
        swap_before_second_write,
    )

    _assert_completion_error(
        "stage_corrupt",
        lambda: prepare_controller_completion(
            project_root,
            squad_dir,
            completion_id=COMPLETION_ID,
            origin="routed",
            publication={"kind": "none"},
            route=ROUTED_ROUTE,
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="safe",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        ),
    )

    assert calls == 2
    assert sentinel is not None
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert original_root is not None
    assert (original_root / "intent.json").is_file()
    assert not (original_root / "receipts.json").exists()


def _prepare_journal_completion(
    tmp_path: Path,
    entries: list[object],
    *,
    quarantined: dict[str, object] | None = None,
):
    echelon_result = {
        "verdict": "DONE",
        "state_updates": {},
        "journal_entries": entries,
    }
    return _prepare_minimal(
        tmp_path,
        effect_plan=("journal",),
        judgment_payload_sha256=(
            _payload_digest(echelon_result),
        ),
        judgments=(
            {
                "echelon_result": echelon_result,
                "quarantined_state_updates": quarantined or {},
            },
        ),
    )


def _read_completion_journal(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_completion_journal_strips_spoofed_metadata_and_attests_content(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [
            {
                "id": 999,
                "timestamp": "forged",
                "phase": "forged",
                "completion_id": "forged",
                "entry_index": 77,
                "content_sha256": "0" * 64,
                "controller_completion": {
                    "completion_id": "f" * 32,
                    "entry_index": 77,
                    "content_sha256": "0" * 64,
                },
                "type": "future_signal",
                "agent": "provider",
                "data": {"fact": "sealed"},
            }
        ],
    )
    journal = squad_dir / "reasoning-journal.jsonl"

    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )
    receipt = completion_module.apply_or_verify_completion_journal(plan)

    rows = _read_completion_journal(journal)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == 1
    assert row["timestamp"] != "forged"
    datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
    assert row["phase"] == ROUTED_ROUTE["from_phase"]
    assert "completion_id" not in row
    assert "entry_index" not in row
    assert "content_sha256" not in row
    stamp = row["controller_completion"]
    assert stamp == {
        "completion_id": COMPLETION_ID,
        "entry_index": 0,
        "content_sha256": plan.content_sha256[0],
    }
    content = dict(row)
    content.pop("id")
    content.pop("timestamp")
    content.pop("controller_completion")
    assert hashlib.sha256(
        json.dumps(
            content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest() == plan.content_sha256[0]
    assert receipt == {
        "schema_version": 1,
        "completion_id": COMPLETION_ID,
        "phase": ROUTED_ROUTE["from_phase"],
        "entry_ids": [1],
        "timestamp": row["timestamp"],
        "content_sha256": list(plan.content_sha256),
    }

    persisted = persist_completion_effect_receipt(
        prepared,
        "journal",
        receipt,
    )
    reloaded = load_prepared_controller_completion(
        tmp_path,
        squad_dir,
        prepared.marker,
    )
    assert persisted == receipt
    assert reloaded.receipts["effects"]["journal"] == receipt


def test_completion_journal_preserves_unrelated_serialized_rows(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [{"type": "future_signal", "data": {"new": True}}],
    )
    journal = squad_dir / "reasoning-journal.jsonl"
    original = b' { "type" : "legacy", "data" : {"keep": true} }\n'
    journal.write_bytes(original)
    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )

    completion_module.apply_or_verify_completion_journal(plan)

    assert journal.read_bytes().startswith(original)
    assert _read_completion_journal(journal)[0] == {
        "type": "legacy",
        "data": {"keep": True},
    }


def test_completion_journal_replay_adopts_exact_atomic_batch(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [
            {"type": "future_signal", "data": {"ordinal": 0}},
            {"type": "future_signal", "data": {"ordinal": 1}},
        ],
    )
    journal = squad_dir / "reasoning-journal.jsonl"
    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )
    first_receipt = completion_module.apply_or_verify_completion_journal(
        plan
    )
    first_bytes = journal.read_bytes()

    recovered_plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )
    recovered_receipt = (
        completion_module.apply_or_verify_completion_journal(
            recovered_plan
        )
    )

    assert recovered_receipt == first_receipt
    assert journal.read_bytes() == first_bytes


@pytest.mark.parametrize(
    "mutation",
    [
        "partial",
        "duplicate_ordinal",
        "missing_ordinal",
        "unexpected_row",
        "same_id_content_drift",
        "physical_reorder",
        "interleaved_unrelated",
    ],
)
def test_completion_journal_rejects_partial_duplicate_missing_or_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [
            {"type": "future_signal", "data": {"ordinal": 0}},
            {"type": "future_signal", "data": {"ordinal": 1}},
        ],
    )
    journal = squad_dir / "reasoning-journal.jsonl"
    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )
    completion_module.apply_or_verify_completion_journal(plan)
    rows = _read_completion_journal(journal)
    if mutation == "partial":
        rows.pop()
    elif mutation == "duplicate_ordinal":
        rows[1]["controller_completion"]["entry_index"] = 0
    elif mutation == "missing_ordinal":
        rows[1]["controller_completion"]["entry_index"] = 2
    elif mutation == "unexpected_row":
        extra = json.loads(json.dumps(rows[1]))
        extra["id"] = 3
        extra["controller_completion"]["entry_index"] = 2
        rows.append(extra)
    elif mutation == "physical_reorder":
        rows.reverse()
    elif mutation == "interleaved_unrelated":
        rows.insert(1, {"type": "unrelated", "data": {"keep": True}})
    else:
        rows[0]["data"]["ordinal"] = "drifted"
    journal.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    before = journal.read_bytes()

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_journal(
            plan
        ),
    )

    assert journal.read_bytes() == before


def test_completion_journal_rejects_malformed_unrelated_json_without_write(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [{"type": "future_signal", "data": {}}],
    )
    journal = squad_dir / "reasoning-journal.jsonl"
    journal.write_bytes(b'{"valid":true}\nnot-json\n')
    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )
    before = journal.read_bytes()

    _assert_completion_error(
        "receipts_invalid",
        lambda: completion_module.apply_or_verify_completion_journal(
            plan
        ),
    )

    assert journal.read_bytes() == before


def _completion_timing_store(squad_dir: Path) -> TelemetryStore:
    store = TelemetryStore(
        squad_dir,
        workflow="spec",
        run_id=squad_dir.name,
        profile={"name": "banzai"},
        trace_id="1" * 32,
    )
    store.ensure_manifest()
    return store


def _git_for_completion_checkpoint(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _prepare_completion_checkpoint(
    tmp_path: Path,
) -> tuple[Path, Path, object]:
    project_root, squad_dir = _roots(tmp_path)
    _git_for_completion_checkpoint(project_root, "init", "-b", "main")
    _git_for_completion_checkpoint(
        project_root,
        "config",
        "user.email",
        "test@example.com",
    )
    _git_for_completion_checkpoint(
        project_root,
        "config",
        "user.name",
        "Test User",
    )
    spec_dir = squad_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    (project_root / "README.md").write_text(
        "# Repository\n",
        encoding="utf-8",
    )
    _git_for_completion_checkpoint(project_root, "add", "-A")
    _git_for_completion_checkpoint(project_root, "commit", "-m", "base")
    head = _git_for_completion_checkpoint(
        project_root,
        "rev-parse",
        "HEAD",
    )
    prepared = prepare_controller_completion(
        project_root,
        squad_dir,
        completion_id=COMPLETION_ID,
        origin="routed",
        publication={"kind": "none"},
        route=ROUTED_ROUTE,
        effect_plan=("checkpoint",),
        checkpoint_prestate={"kind": "git_head", "head": head},
        context_reason="routed phase completion",
        mine_phase_a=False,
        judgment_payload_sha256=(),
        judgments=(),
    )
    return project_root, spec_dir, prepared


def _apply_completion_checkpoint(
    project_root: Path,
    spec_dir: Path | None,
    prepared: object,
    *,
    expected_receipt: object | None = None,
    fault_hook=None,
) -> dict[str, object]:
    return completion_module.create_or_recover_completion_checkpoint(
        prepared.intent,
        project_root=project_root,
        spec_dir=spec_dir,
        run_id="spec-1",
        spec_id="001-demo" if spec_dir is not None else "",
        expected_receipt=expected_receipt,
        fault_hook=fault_hook,
    )


def test_completion_checkpoint_wrapper_binds_intent_and_one_ahead_receipt(
    tmp_path: Path,
) -> None:
    project_root, spec_dir, prepared = _prepare_completion_checkpoint(
        tmp_path
    )
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    receipt = _apply_completion_checkpoint(
        project_root,
        spec_dir,
        prepared,
    )
    count_after = _git_for_completion_checkpoint(
        project_root,
        "rev-list",
        "--count",
        "--all",
    )
    replayed = _apply_completion_checkpoint(
        project_root,
        spec_dir,
        prepared,
        expected_receipt=receipt,
    )

    assert replayed == receipt
    assert receipt["completion_id"] == COMPLETION_ID
    assert receipt["phase"] == ROUTED_ROUTE["from_phase"]
    assert receipt["next_phase"] == ROUTED_ROUTE["to_phase"]
    assert _git_for_completion_checkpoint(
        project_root,
        "rev-list",
        "--count",
        "--all",
    ) == count_after


def test_completion_checkpoint_rejects_malformed_or_drifted_receipts(
    tmp_path: Path,
) -> None:
    project_root, spec_dir, prepared = _prepare_completion_checkpoint(
        tmp_path
    )
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    receipt = _apply_completion_checkpoint(
        project_root,
        spec_dir,
        prepared,
    )
    ledger = spec_dir / ".echelon" / "checkpoints.json"
    postimage = ledger.read_bytes()
    count_after = _git_for_completion_checkpoint(
        project_root,
        "rev-list",
        "--count",
        "--all",
    )
    malformed = (
        {**receipt, "extra": True},
        {**receipt, "schema_version": True},
        {**receipt, "completion_id": "b" * 32},
        {**receipt, "phase": "phase4-build"},
        {**receipt, "next_phase": "done"},
        {**receipt, "commit": "f" * 40},
    )

    for candidate in malformed:
        _assert_completion_error(
            "receipts_mismatch",
            lambda candidate=candidate: _apply_completion_checkpoint(
                project_root,
                spec_dir,
                prepared,
                expected_receipt=candidate,
            ),
        )

    assert ledger.read_bytes() == postimage
    assert _git_for_completion_checkpoint(
        project_root,
        "rev-list",
        "--count",
        "--all",
    ) == count_after


def test_completion_checkpoint_rejects_bound_receipt_postimage_drift(
    tmp_path: Path,
) -> None:
    project_root, spec_dir, prepared = _prepare_completion_checkpoint(
        tmp_path
    )
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    receipt = _apply_completion_checkpoint(
        project_root,
        spec_dir,
        prepared,
    )
    ledger_path = spec_dir / ".echelon" / "checkpoints.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["checkpoints"][0]["next_phase"] = "phase4-drifted"
    ledger_path.write_text(json.dumps(ledger) + "\n", encoding="utf-8")
    postimage = ledger_path.read_bytes()

    _assert_completion_error(
        "receipts_mismatch",
        lambda: _apply_completion_checkpoint(
            project_root,
            spec_dir,
            prepared,
            expected_receipt=receipt,
        ),
    )

    assert ledger_path.read_bytes() == postimage


def test_completion_checkpoint_replays_crash_before_state_step(
    tmp_path: Path,
) -> None:
    project_root, spec_dir, prepared = _prepare_completion_checkpoint(
        tmp_path
    )
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    def crash(boundary: str) -> None:
        if boundary == "after_ledger":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _apply_completion_checkpoint(
            project_root,
            spec_dir,
            prepared,
            fault_hook=crash,
        )
    count_after = _git_for_completion_checkpoint(
        project_root,
        "rev-list",
        "--count",
        "--all",
    )

    receipt = _apply_completion_checkpoint(
        project_root,
        spec_dir,
        prepared,
    )
    adopted = _apply_completion_checkpoint(
        project_root,
        spec_dir,
        prepared,
        expected_receipt=receipt,
    )

    assert adopted == receipt
    assert _git_for_completion_checkpoint(
        project_root,
        "rev-list",
        "--count",
        "--all",
    ) == count_after


@pytest.mark.parametrize("crash_boundary", ("after_close", "after_open"))
def test_completion_timing_adopts_tagged_events_after_crash(
    tmp_path: Path,
    crash_boundary: str,
) -> None:
    _, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    store = _completion_timing_store(squad_dir)
    record_phase_start(
        store,
        phase="phase3-solution",
        budget_seconds=300,
        event_time="2026-07-23T10:00:00Z",
    )

    def crash(boundary: str) -> None:
        if boundary == crash_boundary:
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            store,
            close_phase="phase3-solution",
            close_budget_seconds=300,
            open_phase="phase4-build",
            open_budget_seconds=600,
            fault_hook=crash,
        )

    receipt = completion_module.apply_or_verify_completion_timing(
        prepared.intent,
        store,
        close_phase="phase3-solution",
        close_budget_seconds=300,
        open_phase="phase4-build",
        open_budget_seconds=600,
    )
    postimage = store.events_path.read_bytes()
    adopted = completion_module.apply_or_verify_completion_timing(
        prepared.intent,
        store,
        close_phase="phase3-solution",
        close_budget_seconds=300,
        open_phase="phase4-build",
        open_budget_seconds=600,
        expected_receipt=receipt,
    )

    events, diagnostics = store.read_phase_timings()
    tagged = [event for event in events if event.completion_id]
    assert diagnostics == ()
    assert [event.effect_id for event in tagged] == [
        f"{COMPLETION_ID}:timing:close:phase3-solution",
        f"{COMPLETION_ID}:timing:open:phase4-build",
    ]
    assert receipt == adopted
    assert store.events_path.read_bytes() == postimage


def test_completion_timing_receipt_requires_durable_exact_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    store = _completion_timing_store(squad_dir)
    receipt = completion_module.apply_or_verify_completion_timing(
        prepared.intent,
        store,
        open_phase="phase4-build",
        open_budget_seconds=600,
    )
    postimage = store.events_path.read_bytes()

    def fail_confirmation(expected: bytes) -> bytes:
        raise TelemetryDurabilityError(
            "simulated confirmation failure",
            stage="confirm",
        )

    monkeypatch.setattr(
        store,
        "confirm_phase_timing_stream",
        fail_confirmation,
    )

    _assert_completion_error(
        "receipts_invalid",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            store,
            open_phase="phase4-build",
            open_budget_seconds=600,
            expected_receipt=receipt,
        ),
    )

    assert store.events_path.read_bytes() == postimage


def test_completion_timing_rejects_same_effect_identity_drift(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    store = _completion_timing_store(squad_dir)
    completion_module.apply_or_verify_completion_timing(
        prepared.intent,
        store,
        open_phase="phase4-build",
        open_budget_seconds=600,
    )
    rows = [
        json.loads(line)
        for line in store.events_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    rows[-1]["phase"] = "phase4-drifted"
    store.events_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    before = store.events_path.read_bytes()

    _assert_completion_error(
        "receipts_invalid",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            store,
            open_phase="phase4-build",
            open_budget_seconds=600,
        ),
    )

    assert store.events_path.read_bytes() == before


def test_completion_timing_does_not_adopt_legacy_untagged_event(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    store = _completion_timing_store(squad_dir)
    record_phase_start(
        store,
        phase="phase4-build",
        budget_seconds=600,
        event_time="2026-07-23T10:00:00Z",
    )

    receipt = completion_module.apply_or_verify_completion_timing(
        prepared.intent,
        store,
        open_phase="phase4-build",
        open_budget_seconds=600,
    )

    events, diagnostics = store.read_phase_timings()
    assert diagnostics == ()
    assert len(events) == 2
    assert events[0].completion_id is None
    assert events[1].completion_id == COMPLETION_ID
    assert receipt["events"][0]["effect_id"] == (
        f"{COMPLETION_ID}:timing:open:phase4-build"
    )


def test_completion_timing_rejects_unknown_tagged_row_fields(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    store = _completion_timing_store(squad_dir)
    receipt = completion_module.apply_or_verify_completion_timing(
        prepared.intent,
        store,
        open_phase="phase4-build",
        open_budget_seconds=600,
    )
    rows = [
        json.loads(line)
        for line in store.events_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    rows[-1]["unknown"] = "drift"
    store.events_path.write_text(
        json.dumps(rows[-1], sort_keys=True) + "\n",
        encoding="utf-8",
    )
    postimage = store.events_path.read_bytes()

    _assert_completion_error(
        "receipts_invalid",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            store,
            open_phase="phase4-build",
            open_budget_seconds=600,
            expected_receipt=receipt,
        ),
    )

    assert store.events_path.read_bytes() == postimage


def test_completion_timing_receipt_rejects_close_id_on_started_event(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    completion_id = prepared.intent.completion_id
    effect_id = (
        f"{completion_id}:timing:close:phase3-solution"
    )
    event = PhaseTimingEvent.started(
        trace_id="1" * 32,
        phase="phase3-solution",
        budget_seconds=300,
        event_time="2026-07-23T10:00:00Z",
        completion_id=completion_id,
        effect_id=effect_id,
    )

    class FakeStore:
        def read_phase_timings(self):
            return (event,), ()

        read_durable_phase_timings = read_phase_timings

    receipt = {
        "schema_version": 1,
        "completion_id": completion_id,
        "events": [
            {
                "effect_id": effect_id,
                "event_sha256": (
                    completion_module._completion_timing_event_sha256(
                        event
                    )
                ),
            }
        ],
    }

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            FakeStore(),
            close_phase="phase3-solution",
            close_budget_seconds=300,
            expected_receipt=receipt,
        ),
    )


@pytest.mark.parametrize("drift", ("budget", "trace"))
def test_completion_timing_receipt_rejects_open_semantic_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    _, _, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    completion_id = prepared.intent.completion_id
    effect_id = f"{completion_id}:timing:open:phase4-build"
    expected_trace = "1" * 32
    event = PhaseTimingEvent.started(
        trace_id="2" * 32 if drift == "trace" else expected_trace,
        phase="phase4-build",
        budget_seconds=601 if drift == "budget" else 600,
        event_time="2026-07-23T10:00:00Z",
        completion_id=completion_id,
        effect_id=effect_id,
    )

    class FakeStore:
        trace_id = expected_trace

        def read_phase_timings(self):
            return (event,), ()

        read_durable_phase_timings = read_phase_timings

    receipt = {
        "schema_version": 1,
        "completion_id": completion_id,
        "events": [
            {
                "effect_id": effect_id,
                "event_sha256": (
                    completion_module._completion_timing_event_sha256(
                        event
                    )
                ),
            }
        ],
    }

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            FakeStore(),
            open_phase="phase4-build",
            open_budget_seconds=600,
            expected_receipt=receipt,
        ),
    )


def test_completion_timing_receipt_rejects_invalid_finished_semantics(
    tmp_path: Path,
) -> None:
    _, _, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    completion_id = prepared.intent.completion_id
    effect_id = (
        f"{completion_id}:timing:close:phase3-solution"
    )
    event = PhaseTimingEvent.finished(
        trace_id="1" * 32,
        phase="phase3-solution",
        budget_seconds=300,
        elapsed_seconds=-5.0,
        event_time="not-a-time",
        completion_id=completion_id,
        effect_id=effect_id,
    )

    class FakeStore:
        trace_id = "1" * 32

        def read_phase_timings(self):
            return (event,), ()

        read_durable_phase_timings = read_phase_timings

    receipt = {
        "schema_version": 1,
        "completion_id": completion_id,
        "events": [
            {
                "effect_id": effect_id,
                "event_sha256": (
                    completion_module._completion_timing_event_sha256(
                        event
                    )
                ),
            }
        ],
    }

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            FakeStore(),
            close_phase="phase3-solution",
            close_budget_seconds=300,
            expected_receipt=receipt,
        ),
    )


def test_completion_timing_close_budget_drift_fails_without_append(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        effect_plan=("timing",),
    )
    store = _completion_timing_store(squad_dir)
    record_phase_start(
        store,
        phase="phase3-solution",
        budget_seconds=250,
        event_time="2026-07-23T10:00:00Z",
    )
    preimage = store.events_path.read_bytes()

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_timing(
            prepared.intent,
            store,
            close_phase="phase3-solution",
            close_budget_seconds=300,
        ),
    )

    assert store.events_path.read_bytes() == preimage


def test_completion_journal_durable_replace_syncs_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [{"type": "future_signal", "data": {}}],
    )
    journal = squad_dir / "reasoning-journal.jsonl"
    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )
    synced: list[Path] = []
    real_sync = completion_module._fsync_directory

    def track_sync(path: Path) -> None:
        synced.append(path)
        real_sync(path)

    monkeypatch.setattr(
        completion_module,
        "_fsync_directory",
        track_sync,
    )

    completion_module.apply_or_verify_completion_journal(plan)

    assert journal.parent in synced


def test_completion_journal_includes_controller_quarantine_warning(
    tmp_path: Path,
) -> None:
    _, squad_dir, prepared = _prepare_journal_completion(
        tmp_path,
        [],
        quarantined={"status": "done", "total_tasks": 99},
    )
    journal = squad_dir / "reasoning-journal.jsonl"
    plan = completion_module.prepare_completion_journal_plan(
        prepared.intent,
        journal,
    )

    completion_module.apply_or_verify_completion_journal(plan)

    row = _read_completion_journal(journal)[0]
    assert row["type"] == "state_contract_warning"
    assert row["phase"] == ROUTED_ROUTE["from_phase"]
    assert row["data"]["dropped_keys"] == ["status", "total_tasks"]


_COMPLETION_CONTEXT_NAMES = (
    "prior-spec-context.md",
    "current-feature-context.md",
    "feature-registry.snapshot.json",
    "mempalace-reconciliation.json",
    "stale-memory-report.md",
)


def _completion_context_generator(calls: list[dict[str, object]]):
    def generate(
        project_root: Path,
        run_dir: Path,
        *,
        user_request: str,
        drawers: object,
        output_dir: Path,
    ) -> object:
        call = {
            "project_root": project_root,
            "run_dir": run_dir,
            "user_request": user_request,
            "drawers": tuple(drawers),
            "output_dir": output_dir,
        }
        calls.append(call)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in _COMPLETION_CONTEXT_NAMES:
            (output_dir / name).write_bytes(
                (
                    f"{name}|{user_request}|"
                    f"{','.join(map(str, drawers))}\n"
                ).encode("utf-8")
            )
        return SimpleNamespace(context_dir=output_dir)

    return generate


def _prepare_context_completion(tmp_path: Path):
    return _prepare_minimal(
        tmp_path,
        effect_plan=("context",),
    )


def test_completion_context_freezes_one_ahead_before_visibility_and_replays(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    calls: list[dict[str, object]] = []
    first_generator = _completion_context_generator(calls)

    receipt = completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=7,
        prepared_at="2026-07-23T10:11:12Z",
        user_request="original",
        drawers=("drawer-original",),
        generator=first_generator,
    )

    assert not (squad_dir / "context").exists()
    assert len(calls) == 1
    assert receipt["schema_version"] == 1
    assert receipt["completion_id"] == COMPLETION_ID
    assert receipt["source_state_revision"] == 7
    assert receipt["prepared_at"] == "2026-07-23T10:11:12Z"
    assert [item["name"] for item in receipt["files"]] == list(
        _COMPLETION_CONTEXT_NAMES
    )
    assert all(
        set(item) == {
            "name",
            "preimage",
            "sha256",
            "size_bytes",
        }
        for item in receipt["files"]
    )
    receipts = json.loads(
        (
            prepared._transaction_root / "receipts.json"
        ).read_text(encoding="utf-8")
    )
    assert receipts["effects"]["context"] == receipt

    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    def must_not_regenerate(*args, **kwargs):
        raise AssertionError("frozen context was regenerated")

    replayed = completion_module.prepare_or_load_completion_context(
        reloaded,
        project_root=project_root,
        source_state_revision=99,
        prepared_at="2030-01-01T00:00:00Z",
        user_request="changed",
        drawers=("drawer-changed",),
        generator=must_not_regenerate,
    )
    installed = completion_module.install_or_verify_completion_context(
        reloaded
    )

    assert replayed == receipt
    assert installed == receipt
    for item in receipt["files"]:
        expected = (
            prepared._transaction_root
            / "context"
            / "files"
            / item["name"]
        ).read_bytes()
        assert (squad_dir / "context" / item["name"]).read_bytes() == (
            expected
        )
    assert (
        completion_module.install_or_verify_completion_context(reloaded)
        == receipt
    )


def test_completion_context_recovers_partial_visible_install(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipt = completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z",
        generator=_completion_context_generator([]),
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )
    installed: list[str] = []

    def crash_after_first(stage: str) -> None:
        installed.append(stage)
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        completion_module.install_or_verify_completion_context(
            reloaded,
            fault_hook=crash_after_first,
        )

    assert len(installed) == 1
    assert len(list((squad_dir / "context").iterdir())) == 1

    assert (
        completion_module.install_or_verify_completion_context(reloaded)
        == receipt
    )
    assert {
        path.name for path in (squad_dir / "context").iterdir()
    } == set(_COMPLETION_CONTEXT_NAMES)


def test_completion_context_crash_before_receipt_allows_private_regeneration(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )

    def crash(stage: str) -> None:
        assert stage == "after_generation"
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            user_request="first",
            generator=_completion_context_generator([]),
            fault_hook=crash,
        )

    assert not (squad_dir / "context").exists()
    assert not (
        prepared._transaction_root / "context"
    ).exists()
    receipts = json.loads(
        (
            prepared._transaction_root / "receipts.json"
        ).read_text(encoding="utf-8")
    )
    assert receipts["effects"] == {}

    receipt = completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=2,
        prepared_at="2026-07-23T11:12:13Z",
        user_request="second",
        generator=_completion_context_generator([]),
    )

    assert receipt["source_state_revision"] == 2
    staged = (
        prepared._transaction_root
        / "context"
        / "files"
        / "prior-spec-context.md"
    )
    assert b"|second|" in staged.read_bytes()


def test_completion_context_target_drift_fails_before_any_install(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z",
        generator=_completion_context_generator([]),
    )
    visible = squad_dir / "context"
    visible.mkdir()
    drifted = visible / "stale-memory-report.md"
    drifted.write_bytes(b"unbound drift\n")
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.install_or_verify_completion_context(
            reloaded
        ),
    )

    assert list(visible.iterdir()) == [drifted]
    assert drifted.read_bytes() == b"unbound drift\n"


def test_completion_context_final_replace_rechecks_bound_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z",
        generator=_completion_context_generator([]),
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )
    real_replace = completion_module._durably_replace_file
    injected = False

    def inject_drift(path: Path, content: bytes, **kwargs) -> None:
        nonlocal injected
        if path.parent == squad_dir / "context" and not injected:
            injected = True
            path.write_bytes(b"racing drift\n")
        real_replace(path, content, **kwargs)

    monkeypatch.setattr(
        completion_module,
        "_durably_replace_file",
        inject_drift,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.install_or_verify_completion_context(
            reloaded
        ),
    )

    assert injected
    assert (
        squad_dir / "context" / "prior-spec-context.md"
    ).read_bytes() == b"racing drift\n"
    assert not (
        squad_dir / "context" / "current-feature-context.md"
    ).exists()


def test_completion_context_receipt_replace_rechecks_bound_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    real_replace = completion_module._durably_replace_file
    injected = False

    def inject_drift(path: Path, content: bytes, **kwargs) -> None:
        nonlocal injected
        if path == receipts_path and not injected:
            injected = True
            path.write_bytes(b"unbound receipt drift\n")
        real_replace(path, content, **kwargs)

    monkeypatch.setattr(
        completion_module,
        "_durably_replace_file",
        inject_drift,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert injected
    assert receipts_path.read_bytes() == b"unbound receipt drift\n"
    assert not (squad_dir / "context").exists()


def test_completion_context_receipt_exchange_restores_last_moment_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    real_exchange = completion_module._atomic_exchange_files
    injected = False

    def inject_inside_exchange(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal injected
        if second_name == "receipts.json" and not injected:
            injected = True
            receipts_path.write_bytes(b"last-moment drift\n")
        real_exchange(directory_fd, first_name, second_name)

    monkeypatch.setattr(
        completion_module,
        "_atomic_exchange_files",
        inject_inside_exchange,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert injected
    assert receipts_path.read_bytes() == b"last-moment drift\n"
    assert not (squad_dir / "context").exists()


def test_completion_context_receipt_exchange_preserves_post_exchange_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    real_exchange = completion_module._atomic_exchange_files
    injected = False

    def inject_after_exchange(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal injected
        real_exchange(directory_fd, first_name, second_name)
        if second_name == "receipts.json" and not injected:
            injected = True
            receipts_path.write_bytes(b"post-exchange drift\n")

    monkeypatch.setattr(
        completion_module,
        "_atomic_exchange_files",
        inject_after_exchange,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert injected
    assert receipts_path.read_bytes() == b"post-exchange drift\n"
    assert not (squad_dir / "context").exists()


def test_completion_context_receipt_exchange_preserves_newest_racing_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    real_exchange = completion_module._atomic_exchange_files
    injected = False

    def inject_around_exchange(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal injected
        if second_name == "receipts.json" and not injected:
            receipts_path.write_bytes(b"pre-exchange drift\n")
            real_exchange(directory_fd, first_name, second_name)
            receipts_path.write_bytes(b"newer post-exchange drift\n")
            injected = True
            return
        real_exchange(directory_fd, first_name, second_name)

    monkeypatch.setattr(
        completion_module,
        "_atomic_exchange_files",
        inject_around_exchange,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert injected
    assert (
        receipts_path.read_bytes()
        == b"newer post-exchange drift\n"
    )
    assert not (squad_dir / "context").exists()


def test_completion_context_receipt_rollback_preserves_exchange_boundary_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    real_exchange = completion_module._atomic_exchange_files
    exchange_count = 0

    def inject_before_each_exchange(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal exchange_count
        if second_name == "receipts.json":
            exchange_count += 1
            if exchange_count == 1:
                receipts_path.write_bytes(b"pre-exchange drift\n")
            elif exchange_count == 2:
                receipts_path.write_bytes(
                    b"rollback-boundary drift\n"
                )
        real_exchange(directory_fd, first_name, second_name)

    monkeypatch.setattr(
        completion_module,
        "_atomic_exchange_files",
        inject_before_each_exchange,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert exchange_count == 3
    assert (
        receipts_path.read_bytes()
        == b"rollback-boundary drift\n"
    )
    assert not (squad_dir / "context").exists()


def test_completion_context_receipt_rollback_restores_oversized_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    real_exchange = completion_module._atomic_exchange_files
    oversized = b"x" * (
        completion_module._MAX_CONTEXT_FILE_BYTES + 1
    )
    injected = False

    def inject_oversized_drift(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal injected
        if second_name == "receipts.json" and not injected:
            receipts_path.write_bytes(oversized)
            injected = True
        real_exchange(directory_fd, first_name, second_name)

    monkeypatch.setattr(
        completion_module,
        "_atomic_exchange_files",
        inject_oversized_drift,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert injected
    assert receipts_path.read_bytes() == oversized
    assert not list(
        receipts_path.parent.glob(".receipts.json-*.tmp")
    )
    assert not (squad_dir / "context").exists()


def test_completion_context_receipt_exchange_hashes_stat_preserving_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    original = receipts_path.read_bytes()
    original_stat = receipts_path.stat()
    same_stat_drift = b"x" * len(original)
    real_exchange = completion_module._atomic_exchange_files
    injected = False

    def inject_same_stat_drift(
        directory_fd: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal injected
        if second_name == "receipts.json" and not injected:
            receipts_path.write_bytes(same_stat_drift)
            os.utime(
                receipts_path,
                ns=(
                    original_stat.st_atime_ns,
                    original_stat.st_mtime_ns,
                ),
            )
            injected = True
        real_exchange(directory_fd, first_name, second_name)

    monkeypatch.setattr(
        completion_module,
        "_atomic_exchange_files",
        inject_same_stat_drift,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.prepare_or_load_completion_context(
            prepared,
            project_root=project_root,
            source_state_revision=1,
            prepared_at="2026-07-23T10:11:12Z",
            generator=_completion_context_generator([]),
        ),
    )

    assert injected
    assert receipts_path.read_bytes() == same_stat_drift
    assert not (squad_dir / "context").exists()


def test_completion_context_rejects_symlinked_visible_root_before_child_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z",
        generator=_completion_context_generator([]),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    for name in _COMPLETION_CONTEXT_NAMES:
        (outside / name).write_bytes(b"outside\n")
    (squad_dir / "context").symlink_to(
        outside,
        target_is_directory=True,
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )
    original_read = completion_module._read_regular
    reads: list[Path] = []

    def track_read(path: Path, **kwargs):
        reads.append(path)
        return original_read(path, **kwargs)

    monkeypatch.setattr(
        completion_module,
        "_read_regular",
        track_read,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.install_or_verify_completion_context(
            reloaded
        ),
    )

    assert not any(outside in path.parents for path in reads)
    assert all(
        (outside / name).read_bytes() == b"outside\n"
        for name in _COMPLETION_CONTEXT_NAMES
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing", "stage_missing"),
        ("corrupt", "stage_corrupt"),
    ],
)
def test_completion_context_rejects_missing_or_corrupt_frozen_substage(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z",
        generator=_completion_context_generator([]),
    )
    staged = (
        prepared._transaction_root
        / "context"
        / "files"
        / "prior-spec-context.md"
    )
    if mutation == "missing":
        staged.unlink()
    else:
        staged.write_bytes(b"changed after receipt\n")
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    _assert_completion_error(
        expected_code,
        lambda: completion_module.install_or_verify_completion_context(
            reloaded
        ),
    )

    assert not (squad_dir / "context").exists()


def test_completion_context_rejects_non_fixed_receipt_path(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared = _prepare_context_completion(
        tmp_path
    )
    completion_module.prepare_or_load_completion_context(
        prepared,
        project_root=project_root,
        source_state_revision=1,
        prepared_at="2026-07-23T10:11:12Z",
        generator=_completion_context_generator([]),
    )
    receipts_path = prepared._transaction_root / "receipts.json"
    receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
    receipts["effects"]["context"]["files"][0]["name"] = "../escape"
    receipts_path.write_bytes(
        (
            json.dumps(receipts, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.install_or_verify_completion_context(
            reloaded
        ),
    )
    assert not (squad_dir / "context").exists()


_MINING_SPEC_BYTES = b"FR-001: Deterministic mining.\n"
_MINING_DRAWER_ID = deterministic_requirement_drawer_id(
    wing="demo",
    room="functional-requirements",
    spec_sha256=hashlib.sha256(_MINING_SPEC_BYTES).hexdigest(),
    requirement_id="FR-001",
    content="FR-001: Deterministic mining.",
)


def _prepare_mining_completion(
    tmp_path: Path,
    *,
    with_spec: bool = True,
):
    project_root, squad_dir, prepared = _prepare_minimal(
        tmp_path,
        origin="terminal",
        route={"kind": "terminal", "terminal_phase": "DONE"},
        effect_plan=("mining",),
        mine_phase_a=True,
    )
    config = (
        project_root
        / ".specify"
        / "extensions"
        / "echelon"
        / "echelon-config.yml"
    )
    config.parent.mkdir(parents=True)
    config.write_text(
        "mempalace:\n  wing: demo\n",
        encoding="utf-8",
    )
    spec_file = None
    if with_spec:
        spec_dir = project_root / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        spec_file = spec_dir / "spec.md"
        spec_file.write_bytes(_MINING_SPEC_BYTES)
    return project_root, squad_dir, prepared, spec_file


class _CompletionMiner:
    def __init__(
        self,
        *,
        outcome: str,
        mutate_spec: Path | None = None,
    ) -> None:
        self.outcome = outcome
        self.mutate_spec = mutate_spec
        self.mine_calls = 0
        self.verify_calls = 0

    def plan_canonical_bytes(self, *args, **kwargs):
        return [_MINING_DRAWER_ID]

    def mine_canonical_bytes(self, *args, **kwargs):
        self.mine_calls += 1
        if self.mutate_spec is not None:
            self.mutate_spec.write_text(
                "FR-001: Drifted during mining.\n",
                encoding="utf-8",
            )
        if self.outcome == "written":
            return SimpleNamespace(
                total=1,
                written=1,
                already_present=0,
                unavailable=0,
                failed=0,
                skipped=0,
                drawer_ids=[_MINING_DRAWER_ID],
                expected_drawer_ids=[_MINING_DRAWER_ID],
            )
        if self.outcome == "already_present":
            return SimpleNamespace(
                total=1,
                written=0,
                already_present=1,
                unavailable=0,
                failed=0,
                skipped=1,
                drawer_ids=[_MINING_DRAWER_ID],
                expected_drawer_ids=[_MINING_DRAWER_ID],
            )
        return SimpleNamespace(
            total=1,
            written=0,
            already_present=0,
            unavailable=0,
            failed=1,
            skipped=0,
            drawer_ids=[],
            expected_drawer_ids=[_MINING_DRAWER_ID],
        )

    def verify_canonical_bytes(self, *args, **kwargs):
        self.verify_calls += 1
        return True


@pytest.mark.parametrize(
    ("requested", "expected", "with_spec"),
    [
        ("written", "written", True),
        ("already_present", "already_present", True),
        ("failed", "failed", True),
        ("unavailable", "unavailable", True),
        ("not_applicable", "not_applicable", False),
    ],
)
def test_completion_mining_returns_and_persists_every_bounded_outcome(
    tmp_path: Path,
    requested: str,
    expected: str,
    with_spec: bool,
) -> None:
    project_root, _, prepared, spec_file = (
        _prepare_mining_completion(
            tmp_path,
            with_spec=with_spec,
        )
    )
    miner = _CompletionMiner(outcome=requested)

    def factory():
        if requested == "unavailable":
            raise ImportError("mempalace unavailable")
        return miner

    outcome = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="run-test",
        miner_factory=factory,
    )

    assert outcome.outcome == expected
    assert outcome.completion_id == COMPLETION_ID
    if expected == "not_applicable":
        assert outcome.spec_sha256 is None
        assert outcome.drawer_ids == ()
    else:
        assert len(outcome.spec_sha256) == 64
    receipts = json.loads(
        (
            prepared._transaction_root / "receipts.json"
        ).read_text(encoding="utf-8")
    )
    assert receipts["effects"]["mining"] == outcome.to_dict()


def test_completion_mining_crash_after_drawers_replays_as_exact_existing(
    tmp_path: Path,
) -> None:
    project_root, _, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    first = _CompletionMiner(outcome="written")

    def crash(stage: str) -> None:
        assert stage == "after_mining"
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        completion_module.apply_or_verify_completion_mining(
            prepared,
            project_root=project_root,
            spec_file=spec_file,
            run_id="run-test",
            miner_factory=lambda: first,
            fault_hook=crash,
        )

    receipts = json.loads(
        (
            prepared._transaction_root / "receipts.json"
        ).read_text(encoding="utf-8")
    )
    assert receipts["effects"] == {}
    replay = _CompletionMiner(outcome="already_present")
    outcome = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="changed-run",
        miner_factory=lambda: replay,
    )

    assert first.mine_calls == 1
    assert replay.mine_calls == 1
    assert outcome.outcome == "already_present"
    assert outcome.drawer_ids == (_MINING_DRAWER_ID,)


@pytest.mark.parametrize("outcome_name", ["unavailable", "failed"])
def test_completion_mining_receipted_best_effort_outcome_never_retries(
    tmp_path: Path,
    outcome_name: str,
) -> None:
    project_root, squad_dir, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    if outcome_name == "unavailable":
        factory = lambda: (_ for _ in ()).throw(ImportError("offline"))
    else:
        factory = lambda: _CompletionMiner(outcome="failed")
    first = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="run-test",
        miner_factory=factory,
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    def must_not_retry():
        raise AssertionError("receipted best-effort outcome retried")

    replay = completion_module.apply_or_verify_completion_mining(
        reloaded,
        project_root=project_root,
        spec_file=spec_file,
        run_id="changed-run",
        miner_factory=must_not_retry,
    )

    assert replay == first
    assert replay.outcome == outcome_name


def test_completion_mining_receipted_partial_failure_never_retries_backend(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    assert spec_file is not None
    partial_spec = (
        b"FR-001: Deterministic mining.\n"
        b"FR-002: Partial failure.\n"
    )
    spec_file.write_bytes(partial_spec)
    partial_digest = hashlib.sha256(partial_spec).hexdigest()
    first_id = deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=partial_digest,
        requirement_id="FR-001",
        content="FR-001: Deterministic mining.",
    )
    second_id = deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=partial_digest,
        requirement_id="FR-002",
        content="FR-002: Partial failure.",
    )
    miner = _CompletionMiner(outcome="failed")

    def plan(*args, **kwargs):
        return [first_id, second_id]

    def partial_failure(*args, **kwargs):
        return SimpleNamespace(
            total=2,
            written=1,
            already_present=0,
            unavailable=0,
            failed=1,
            skipped=0,
            drawer_ids=[first_id],
            expected_drawer_ids=[first_id, second_id],
        )

    miner.plan_canonical_bytes = plan
    miner.mine_canonical_bytes = partial_failure
    first = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="run-test",
        miner_factory=lambda: miner,
    )
    assert first.outcome == "failed"
    assert first.drawer_ids == (first_id,)
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    def unavailable():
        raise ImportError("backend later unavailable")

    replay = completion_module.apply_or_verify_completion_mining(
        reloaded,
        project_root=project_root,
        spec_file=spec_file,
        run_id="changed-run",
        miner_factory=unavailable,
    )

    assert replay == first


def test_completion_mining_rejects_forged_partial_failed_receipt_offline(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    assert spec_file is not None
    forged_id = (
        "drawer_demo_functional-requirements_" + ("f" * 64)
    )
    assert forged_id != _MINING_DRAWER_ID
    completion_module._persist_current_completion_receipt(
        prepared,
        "mining",
        {
            "schema_version": 1,
            "completion_id": prepared.intent.completion_id,
            "outcome": "failed",
            "spec_sha256": hashlib.sha256(
                spec_file.read_bytes()
            ).hexdigest(),
            "drawer_ids": [forged_id],
        },
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    def must_not_call():
        raise AssertionError("forged receipt reached mining backend")

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_mining(
            reloaded,
            project_root=project_root,
            spec_file=spec_file,
            run_id="backend-offline",
            miner_factory=must_not_call,
        ),
    )


def test_completion_mining_replays_empty_failed_receipt_after_local_plan_error(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    assert spec_file is not None
    spec_file.write_bytes(b"\xff")

    def must_not_call():
        raise AssertionError("local plan failure reached mining backend")

    first = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="backend-offline",
        miner_factory=must_not_call,
    )
    assert first.outcome == "failed"
    assert first.drawer_ids == ()
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )

    replay = completion_module.apply_or_verify_completion_mining(
        reloaded,
        project_root=project_root,
        spec_file=spec_file,
        run_id="changed-run",
        miner_factory=must_not_call,
    )

    assert replay == first


def test_completion_mining_one_ahead_written_receipt_verifies_without_mining(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    first_miner = _CompletionMiner(outcome="written")
    first = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="run-test",
        miner_factory=lambda: first_miner,
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )
    verifier = _CompletionMiner(outcome="written")

    replay = completion_module.apply_or_verify_completion_mining(
        reloaded,
        project_root=project_root,
        spec_file=spec_file,
        run_id="changed-run",
        miner_factory=lambda: verifier,
        expected_receipt=first.to_dict(),
    )

    assert replay == first
    assert verifier.verify_calls == 1
    assert verifier.mine_calls == 0


def test_completion_mining_rejects_canonical_spec_drift(
    tmp_path: Path,
) -> None:
    project_root, squad_dir, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    first = completion_module.apply_or_verify_completion_mining(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
        run_id="run-test",
        miner_factory=lambda: _CompletionMiner(outcome="written"),
    )
    reloaded = load_prepared_controller_completion(
        project_root,
        squad_dir,
        prepared.marker,
    )
    assert spec_file is not None
    spec_file.write_text(
        "FR-001: Changed after receipt.\n",
        encoding="utf-8",
    )

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_mining(
            reloaded,
            project_root=project_root,
            spec_file=spec_file,
            run_id="run-test",
            miner_factory=lambda: _CompletionMiner(outcome="written"),
            expected_receipt=first.to_dict(),
        ),
    )


def test_completion_mining_rejects_drift_during_producer_without_receipt(
    tmp_path: Path,
) -> None:
    project_root, _, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    assert spec_file is not None

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_mining(
            prepared,
            project_root=project_root,
            spec_file=spec_file,
            run_id="run-test",
            miner_factory=lambda: _CompletionMiner(
                outcome="written",
                mutate_spec=spec_file,
            ),
        ),
    )
    receipts = json.loads(
        (
            prepared._transaction_root / "receipts.json"
        ).read_text(encoding="utf-8")
    )
    assert receipts["effects"] == {}


def test_completion_mining_rejects_non_deterministic_drawer_id(
    tmp_path: Path,
) -> None:
    project_root, _, prepared, spec_file = (
        _prepare_mining_completion(tmp_path)
    )
    miner = _CompletionMiner(outcome="written")
    original_mine = miner.mine_canonical_bytes

    def malformed_result(*args, **kwargs):
        result = original_mine(*args, **kwargs)
        result.drawer_ids = ["drawer_malformed"]
        return result

    miner.mine_canonical_bytes = malformed_result

    _assert_completion_error(
        "receipts_mismatch",
        lambda: completion_module.apply_or_verify_completion_mining(
            prepared,
            project_root=project_root,
            spec_file=spec_file,
            run_id="run-test",
            miner_factory=lambda: miner,
        ),
    )
