# Task 1 implementation report

Status: DONE

Implementation commit: `2303891f67d0b8628a7962306cbe1b8ccfa2a261`
(`feat(graph): project captured memory through shared transformations`).
This report is a subsequent documentation-only commit. No tests are repeated
after the implementation commit.

## Scope and outcome

Implemented the captured memory contribution and one shared receipt, drawer,
audit normalization/projection and canonical source-record transformation.
Existing graph models and the two native seven-field plan import identities
remain their original objects. The shared drawer generator accepts known IDs
and yields each node before its edge, retaining legacy incremental dictionary
updates and missing-endpoint failure behavior. Legacy source reads, native
planning, audit calls, exception handling, partial rows, source kind overrides
and projection timing remain in their original owners. Public captured values
use exact validation; legacy duck typing and list-only issue interpretation
remain compatible.

Extracted the existing scope validation verbatim into the structural module's
`_validate_scope` helper. Added documentation of the contribution limits and
the mandatory captured audit origin. No graph schema/wire, identity authority,
memory context/wing derivation, runtime, controller, source capture or live
memory planner/auditor changes were made.

The final tests cover independently specified complete records and literal
audit/source digest payloads and hashes in all three domains; report statuses
and all issue fields; empty and partial observations; root artifact rules and
endpoint fallback; strict damaged values, hashes, types and ownership;
process-control propagation and source-bearing exception removal; forbidden
external reads and replanning; real native requirement/support/evidence/RE
planning with legacy domain-helper parity and continuation; wide and legacy
labels and deterministic keys; import order; and real offline retained identity
history composition with historical evidence and unassessed legacy memory edges.

## Environment and discipline

Every pytest invocation below ran from:

`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`

The executable was always the parent checkout's absolute
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`, never a worktree
virtualenv. Standalone Python used `PYTHONPATH=src`.
Original review base: `3552e442f523de925b884998d0f98cfaab3354c5`.

Read the task brief first, the full implementer template, repository AGENTS,
TDD and writing-good-tests references, verification skill, and the systematic
debugging skill when fixture tests exposed incorrect assumptions. No
subagents/reviewers, full-unit suite, capacity/live/provider run, install or
postcommit test repeat was used. Root owns its plan and progress ledger; neither
is included in these commits. The amended brief is force-added explicitly.

## Chronology and TDD evidence

### 1. Required initial RED, before any production edits

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_captured_memory_retains_native_plan_after_input_damage -q
```

The native planner succeeded on the required FR-1000000 fixture, then the
existing helper's complete drawer properties and exact STORED_AS edge assertions
passed. Only the import of the absent new module failed. Root was notified
before production began. Exit 1; full output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_________ test_captured_memory_retains_native_plan_after_input_damage __________

    def test_captured_memory_retains_native_plan_after_input_damage():
        # Catch altered native identities/hashes and retained caller-owned records.
        content = b"# Requirements\n\nFR-1000000: Preserve the question identity.\n"
        source = "specs/demo/spec.md"
        digest = hashlib.sha256(content).hexdigest()
        rows = plan_canonical_requirement_drawers(
            content, source=source,
            artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + digest},
            wing="graph-test-wing",
        )
        assert [row.requirement_id for row in rows] == ["FR-1000000"]
        nodes = {"req:demo:FR-1000000": GraphNode("req:demo:FR-1000000", "Requirement", {})}
        edges = []
        spec_graph._add_drawer_rows(
            Path("specs/demo"), rows, SimpleNamespace(status="pass"), nodes, edges,
            source_artifact_kind={source: "requirement"},
        )
        node_id = "drawer:demo:" + rows[0].drawer_id
        expected_properties = {
            "drawer_id": rows[0].drawer_id,
            "source_path": source,
            "room": "functional-requirements",
            "artifact_kind": "requirement",
            "artifact_hash": "sha256:" + digest,
            "content_hash": hashlib.sha256(b"FR-1000000: Preserve the question identity.").hexdigest(),
            "presence": "present",
            "reconciliation_status": "pass",
            "issue_codes": [],
        }
        expected_edge = GraphEdge(
            "req:demo:FR-1000000", "STORED_AS", node_id,
            {"presence": "present", "reconciliation_status": "pass"},
        )
        assert edges == [expected_edge]
        assert nodes[node_id].properties == expected_properties
>       module = importlib.import_module("echelon.spec_graph_memory")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/unit/test_spec_graph_memory.py:48:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
../../../../../.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/lib/python3.11/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
<frozen importlib._bootstrap>:1204: in _gcd_import
    ???
<frozen importlib._bootstrap>:1176: in _find_and_load
    ???
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

name = 'echelon.spec_graph_memory'
import_ = <function _gcd_import at 0x1009a3d80>

>   ???
E   ModuleNotFoundError: No module named 'echelon.spec_graph_memory'

<frozen importlib._bootstrap>:1140: ModuleNotFoundError
=========================== short test summary info ============================
FAILED tests/unit/test_spec_graph_memory.py::test_captured_memory_retains_native_plan_after_input_damage
1 failed in 0.57s
```

### 2. Required initial GREEN

After implementing shared transformations and strict captured construction:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_captured_memory_retains_native_plan_after_input_damage -q
```

```text
.                                                                        [100%]
1 passed in 0.55s
```

Exit 0.

### 3. Expanded focused checkpoints

Added independent domain records/digests, status/projection and artifact rules:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py -q
```

```text
.....................................                                    [100%]
37 passed in 0.57s
```


Added exact-type/path/hash/damaged-record validation, ownership and pure tripwires:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py -q
```

```text
........................................................................ [ 33%]
........................................................................ [ 67%]
....................................................................     [100%]
212 passed in 0.66s
```


### 4. Native helper parity fixtures and fixture correction

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py -q
```

Exit 1. This newly expanded run reported `6 failed, 221 passed in 0.80s`.
All six failures were parameterizations of
`test_real_canonical_helper_preserves_native_rows_and_exception_continuation`
at its complete rendered-record comparison:
`assert _render(actual) == _render(contribution)`.
The tool output was truncated, so the six repeated tracebacks are not represented
as a complete captured log here. No production amendment came from this failure.

Diagnosis: the fixture supplied lifecycle `build` but had no real legacy build
marker. The existing `infer_lifecycle_stage` on the actual fixture returned
`phase_a`; the difference was the root tasks required flag. Added a real
fixture `run-history.json` marker, which is not a supporting memory artifact.

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_real_canonical_helper_preserves_native_rows_and_exception_continuation -q
```

```text
......                                                                   [100%]
6 passed in 0.59s
```


### 5. Native identities/imports/history fixtures and corrected expectations

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_native_drawer_keys_and_old_body_hashes_survive_later_source_change tests/unit/test_spec_graph_memory.py::test_structure_memory_and_retained_history_compose_without_reassessing_old_evidence tests/unit/test_spec_graph_memory.py::test_import_orders_keep_existing_model_and_plan_identities -q
```

Exit 1: `1 failed, 4 passed in 1.02s`. The identity composition completed; my
test incorrectly expected `verified.properties["spec_input_hash"]`, which the
existing graph transformation does not emit (`KeyError: 'spec_input_hash'`).
Inspection confirmed the actual preserved graph provenance fields. Removed that
unsupported assertion and asserted preserved verification status instead.

Also added exact-byte content mutation/source-hash mismatch coverage:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_structure_memory_and_retained_history_compose_without_reassessing_old_evidence tests/unit/test_spec_graph_memory.py::test_source_values_are_validated_before_transformation -q
```

Exit 1: `1 failed, 26 passed in 0.75s`. My added status expectation used
lowercase `implemented`; the existing ledger parser normalizes it to
`IMPLEMENTED`. The failure showed
`AssertionError: assert 'IMPLEMENTED' == 'implemented'`.
Inspected that parser's `.upper()` normalization and corrected the expectation.
These two corrections changed tests only, not production behavior.

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_structure_memory_and_retained_history_compose_without_reassessing_old_evidence -q
```

```text
.                                                                        [100%]
1 passed in 0.70s
```


### 6. Root-authorized acquisition-origin amendment and second RED

The original brief did not carry whether an unavailable RE audit was returned
or synthesized by the existing exception handler. Native helper fixtures exposed
that these have different exact legacy receipts: returned unavailable reports
are projected to selected drawers, but exception fallbacks bypass projection.
Reported this to root before any attempt to change legacy behavior.

Root paused the not-yet-run covering suite, recorded its ruling, and amended the
brief with mandatory `GraphMemoryAudit.origin` as exact `returned` or
`exception`. Exception origin must have exactly the legacy fallback shape:
schema 1, wing None, unavailable status, zero counts, empty seven issue tuples,
and one nonempty exception-class error. Origin must not appear in normalized
audit or graph wire. Read the complete amended brief before proceeding.

The dedicated regression exercises both actual legacy RE branches through the
real native planner, asserts independently constructed complete contributions
and different exact audit hashes, then calls the new origin API.

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_returned_unavailable_and_exception_origin_match_real_legacy_re -q
```

Exit 1. Root was notified before the production amendment. Full output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_____ test_returned_unavailable_and_exception_origin_match_real_legacy_re ______

tmp_path = PosixPath('/private/var/folders/bg/c_4twgwx5_x1265427mk2_mw0000gn/T/pytest-of-michalbachorik/pytest-545/test_returned_unavailable_and_0')

    def test_returned_unavailable_and_exception_origin_match_real_legacy_re(tmp_path):
        from echelon.mempalace_re import ReArtifactSnapshot
        module = _api()
        path = "re/architecture.md"
        content = b"# Results\n\nOriginal observation.\n"
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        artifact = tmp_path / path
        artifact.parent.mkdir()
        artifact.write_bytes(content)
        metadata = dict(canonical=True, artifact_hash=digest, artifact_kind="re-architecture",
                        scope="reverse-engineering", room="original-room")
        snapshot = ReArtifactSnapshot(tmp_path / "re", artifact, content, path, metadata)
        source_digest = _digest([{"path": path, "hash": digest, "artifact_kind": "re-architecture", "room": "original-room"}])
        fallback_values = dict(schema_version=1, wing=None, status="unavailable", artifact_count=0,
            expected_count=0, present_current_count=0, missing=(), stale=(), wrong_wing=(), wrong_room=(),
            duplicate=(), non_canonical=(), lifecycle_excluded=(), errors=("RuntimeError",))
        observations = []
        # Exercise and check BOTH real legacy branches before using the new origin API.
        for origin in ("exception", "returned"):
            adapter = _NativeAdapter([])
            def audit():
                if origin == "exception":
                    raise RuntimeError("external acquisition failed")
                return SimpleNamespace(**{key: list(value) if type(value) is tuple else value for key, value in fallback_values.items()})
            nodes, inputs, edges, receipts = {}, {}, [], []
            spec_graph._add_artifact_memory_domain(
                root=tmp_path, spec_dir=tmp_path / "specs/demo", domain="published-re",
                virtual_path="mempalace://published-re/audit", snapshots=[snapshot],
                planner_name="plan_re_artifact_rows", adapter_factory=lambda: adapter, audit=audit,
                required=False, nodes=nodes, edges=edges, inputs=inputs, receipts=receipts, project_audit=True,
            )
            row, = adapter.rows
            expected_payload = dict(schema_version=1, wing=None, status="unavailable", artifact_count=0,
                expected_count=0 if origin == "exception" else 1,
                present_current_count=0 if origin == "exception" else 1,
                missing=[], stale=[], wrong_wing=[], wrong_room=[], duplicate=[], non_canonical=[],
                lifecycle_excluded=[], errors=["RuntimeError"] if origin == "exception" else [])
            audit_hash = _digest(expected_payload)
            expected = module.MemoryGraphContribution("demo", (
                GraphInput(path, digest, "reverse_engineering", False),
                GraphInput("mempalace://published-re/audit", audit_hash, "memory_audit_report", False, "unavailable", source_digest),
            ), (
                GraphNode("artifact:demo:" + path, "Artifact", {
                    "path": path, "hash": digest, "role": "reverse-engineering", "mining_status": "not-mined-by-policy",
                }),
                GraphNode("drawer:demo:" + row.drawer_id, "MemPalaceDrawer", {
                    "drawer_id": row.drawer_id, "source_path": path, "room": "original-room",
                    "artifact_kind": "re-architecture", "artifact_hash": digest,
                    "content_hash": hashlib.sha256(b"RE-re-architecture-md-000: Results: Original observation.").hexdigest(),
                    "presence": "unavailable", "reconciliation_status": "unavailable", "issue_codes": [],
                }),
            ), (
                GraphEdge("artifact:demo:" + path, "STORED_AS", "drawer:demo:" + row.drawer_id,
                          {"presence": "unavailable", "reconciliation_status": "unavailable"}),
            ), MemoryReceipt("published-re", source_digest, audit_hash, "unavailable"))
            legacy = module.MemoryGraphContribution("demo", tuple(inputs.values()), tuple(nodes.values()), tuple(edges), receipts[0])
            assert legacy == expected
            observations.append((origin, tuple(adapter.rows), expected))
        assert observations[0][2].receipt.audit_hash != observations[1][2].receipt.audit_hash
        for origin, rows, expected in observations:
>           audit = module.GraphMemoryAudit(origin=origin, **fallback_values)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           TypeError: GraphMemoryAudit.__init__() got an unexpected keyword argument 'origin'

tests/unit/test_spec_graph_memory.py:984: TypeError
=========================== short test summary info ============================
FAILED tests/unit/test_spec_graph_memory.py::test_returned_unavailable_and_exception_origin_match_real_legacy_re
1 failed in 0.62s
```

### 7. Origin amendment GREEN and expanded focused verification

Added the origin field, exact fallback validation, and conditional public RE
projection. Legacy helpers were not changed by this amendment. Updated all
native parity fixtures to capture the explicit exception origin, replacing the
earlier documented parity distinction with full contribution/receipt equality.

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_returned_unavailable_and_exception_origin_match_real_legacy_re tests/unit/test_spec_graph_memory.py::test_exception_origin_requires_exact_legacy_fallback_shape tests/unit/test_spec_graph_memory.py::test_missing_or_invalid_origin_is_not_inferred_from_status -q
```

```text
..................                                                       [100%]
18 passed in 0.59s
```

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py -q
```

```text
........................................................................ [ 28%]
........................................................................ [ 57%]
........................................................................ [ 86%]
...................................                                      [100%]
251 passed in 1.10s
```


### 8. Once-only eight-module covering run

Before this run, staged the exact scoped files and obtained tree
`711ef5f1a666d330a4358ecea4048161c83fac8f`.
The staged diff check also reported one new blank line at the new module's EOF.
It was left untouched until the covering run finished.

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_structure.py tests/unit/test_spec_graph_audit.py tests/unit/test_spec_graph_identity.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_re.py tests/unit/test_mempalace_spec_evidence.py -q
```

Exit 0. Full output (the command yielded once while running):

```text
........................................................................ [ 13%]
........................................................................ [ 26%]
........................................................................ [ 39%]
........................................................................ [ 53%]
........................................................................ [ 66%]
........................................................................ [ 79%]
........................................................................ [ 92%]
......................................                                   [100%]
542 passed in 8.21s
```

No warnings. This was the only run of the eight covering modules.

### 9. Last amendment, scoped verification and commit

Removed only the extra blank line at EOF flagged by staged diff-check. No
behavioral change followed the covering suite. Per the task's amendment rule,
verified the two named core regressions instead of repeating the covering suite:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_memory.py::test_captured_memory_retains_native_plan_after_input_damage tests/unit/test_spec_graph_memory.py::test_returned_unavailable_and_exception_origin_match_real_legacy_re -q
```

```text
..                                                                       [100%]
2 passed in 0.56s
```

`git diff --cached --check` then exited 0 with no output. Staged tree became
`e4467f10210ba6bd528198c69445c0c7031ba547`, exactly the tree committed by
`2303891f67d0b8628a7962306cbe1b8ccfa2a261`. No later code, test, or public
documentation amendment was made. This report is the only subsequent scoped
file addition.

## Tested tree and blob proof

| File | Covering-run blob | Final implementation blob |
| --- | --- | --- |
| src/echelon/spec_graph.py | c390608741eb614126652d001690a6b9e310c860 | same |
| src/echelon/spec_graph_structure.py | 34234b291e3cb439dc320647cc7fc5994deffa77 | same |
| src/echelon/spec_graph_memory.py | 64488f1b076963c0c42ac5665f6007e2dda6e618 | f47a80262e48d2ea1bc68ccc36d87d941e0848cd |
| tests/unit/test_spec_graph_memory.py | 6019d0c78e583cc6a6deabccb24f2c0b5b5584b5 | same |
| docs/element-identity-storage.md | 48ef0addfbb1fdce5f7a93007238943dc20b1470 | same |

The memory-module blob difference is the documented EOF-only cleanup. Its
final form was covered by the named two-test scoped verification. The root
plan and progress ledger remained dirty; their uncommitted changes were excluded
from both implementation trees and all commits. The exact amended task brief is included in the
implementation commit; this report does not assert a hash for itself.

## Files changed

- `src/echelon/spec_graph_memory.py`: new detached carriers, public validation/contribution and shared pure transformations.
- `src/echelon/spec_graph.py`: pure transformation delegation only; source acquisition and exception semantics retained.
- `src/echelon/spec_graph_structure.py`: narrow shared scope validation, no policy change.
- `tests/unit/test_spec_graph_memory.py`: 251 focused cases, real native/legacy parity, ownership/purity, and offline history composition.
- `docs/element-identity-storage.md`: captured memory contract and integration limits.
- `.superpowers/sdd/2026-09-13-captured-memory-graph-contribution/task-1-brief.md`: explicitly retained amended requirements.
- `.superpowers/sdd/2026-09-13-captured-memory-graph-contribution/task-1-report.md`: this report.

## Self-review and remaining limits

Reviewed the production diff against the original base, the shared report and
drawer transformations, all strict-public versus compatible-legacy boundaries,
and native read/planning/audit/exception order. The only design gap found was
acquisition origin; root resolved it through the explicit brief amendment and
a second regression-first cycle. The fixture failures were incorrect test
expectations, corrected against the existing lifecycle and ledger behavior.
The final staged diff check is clean.

No unresolved implementation concern is known. This remains a contribution,
not current-memory proof or a complete graph. Callers still must authenticate
captured acquisition, supply full RE/topology/evidence selection, compose all
domains in legacy order, apply retained-history projection, and complete
sealing and managed source/runtime/producer/semantic/completion/bounded-repair
integration before activation. No actual memory store was accessed and no
audit or storage observation was refreshed by the pure function.
