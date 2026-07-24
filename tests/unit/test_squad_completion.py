from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import harness.prepared_phase_result as prepared_phase_result_module
import harness.squad_completion as completion_module
from harness.squad_completion import (
    CompletionError,
    CompletionMarker,
    load_prepared_controller_completion,
    prepare_controller_completion,
)
from harness.state_transaction_namespace import (
    validate_pending_controller_completion,
)


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
