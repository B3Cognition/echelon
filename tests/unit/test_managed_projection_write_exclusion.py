"""Managed identity ownership excludes named legacy projection writers."""

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from echelon.workspace_graph import WorkspaceGraphError
from harness.element_identity_legacy_guard import LEGACY_IDENTITY_EXECUTION_BLOCKED
from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import inspect_project_tree


DATABASE = ".echelon/identity/registry.sqlite3"


def snapshot(root: Path):
    entries = []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        payload = None
        if path.is_symlink():
            payload = str(path.readlink())
        elif stat.S_ISREG(mode):
            payload = path.read_bytes()
        entries.append((path.relative_to(root).as_posix(), stat.S_IFMT(mode), payload))
    database = root / DATABASE
    sql = None
    if database.is_file():
        with closing(sqlite3.connect(database)) as connection:
            sql = tuple(connection.iterdump())
    return tuple(entries), sql


def enroll_managed_spec(root: Path, spec_id: str, *, run_id: str = "managed-run") -> dict:
    store = IdentityStore.initialize(root)
    selected = f"runs/{run_id}/specs/{spec_id}"
    (root / selected).mkdir(parents=True)
    with inspect_project_tree(root, selected) as tree:
        manifest = snapshot_source_manifest(trees=(tree,), files=())
    source = store.register_source_context(
        spec_id=spec_id,
        context_id="source",
        operation_id=f"source-{spec_id}",
        manifest=manifest,
    )
    return store.register_managed_identity(
        spec_id=spec_id,
        operation_id=f"managed-{spec_id}",
        request=ManagedIdentityRequest(
            source["workspace_uuid"],
            source["epoch_uuid"],
            run_id,
            "source",
            selected,
            f"source-{spec_id}",
            manifest.sha256,
        ),
    )


def canonical_spec(root: Path, spec_id: str) -> Path:
    spec_dir = root / "specs" / spec_id
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.joinpath("spec.md").write_text(f"# {spec_id}\n", encoding="utf-8")
    return spec_dir


def workspace_graph_record(root: Path):
    from echelon.spec_graph import GraphNode
    from echelon.workspace_graph import WorkspaceArtifactGraph

    return WorkspaceArtifactGraph(
        workspace_name=root.name,
        generator_version="test",
        members=(),
        inputs=(),
        nodes=(GraphNode("workspace:current", "Workspace", {"workspace_name": root.name}),),
        edges=(),
    )


def workspace_audit_record(root: Path):
    from echelon.workspace_graph_audit import WorkspaceGraphAuditReport

    return WorkspaceGraphAuditReport(
        schema_version=1,
        workspace_name=root.name,
        graph_hash=None,
        status="unavailable",
        members=(),
        findings=(),
    )


def spec_graph_record(spec_id: str):
    from echelon.spec_graph import GraphNode, SpecArtifactGraph

    return SpecArtifactGraph(
        spec_id=spec_id,
        generator_version="test",
        inputs=(),
        nodes=(GraphNode(f"spec:{spec_id}", "Spec", {"spec_id": spec_id}),),
        edges=(),
        memory_receipts=(),
    )


def spec_graph_audit_record(spec_id: str):
    from echelon.spec_graph_audit import SpecGraphAuditReport

    return SpecGraphAuditReport(1, spec_id, "sha256:graph", "pass", ())


def memory_audit_record(root: Path, spec_id: str, *, status: str = "pass", output: Path | None = None):
    from echelon.mempalace_audit import SpecMemoryAuditReport

    return SpecMemoryAuditReport(
        schema_version=1,
        spec_id=spec_id,
        spec_dir=str(output or root / "specs" / spec_id),
        wing="test-wing" if status != "unavailable" else None,
        palace_path=".mempalace" if status != "unavailable" else None,
        status=status,
        expected_count=1,
        present_current_count=1 if status != "unavailable" else 0,
    )


@pytest.mark.unit
def test_managed_workspace_refresh_rejects_before_upstream_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph_refresh as refresh

    enroll_managed_spec(tmp_path, "003-managed")
    assert not (tmp_path / "specs/003-managed").exists()
    effects = []

    def forbidden(root: Path):
        effects.append(root)
        raise AssertionError("managed workspace reached upstream RE refresh")

    monkeypatch.setattr(refresh, "_refresh_re_memory", forbidden)
    before = snapshot(tmp_path)

    with pytest.raises(WorkspaceGraphError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        refresh.refresh_workspace_graph(tmp_path, write=True)

    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_workspace_query_uses_one_query_only_transaction_and_two_bounded_indexed_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import harness.element_identity_store as store_module

    store = IdentityStore.initialize(tmp_path)
    before = snapshot(tmp_path)
    original = store_module._database
    statements: list[str] = []
    reads: list[str] = []
    allowed = {"sqlite_master", "metadata", "managed_identity_specs", "operations"}

    def authorize(action: int, table: str, *args: object) -> int:
        if action == sqlite3.SQLITE_READ:
            reads.append(table)
            if table not in allowed:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @contextmanager
    def observed(path: Path):
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            connection.set_authorizer(authorize)
            yield connection

    monkeypatch.setattr(store_module, "_database", observed)

    assert store.require_unmanaged_workspace() is None

    queries = [statement for statement in statements if statement.startswith("SELECT 1 FROM")]
    assert queries == [
        "SELECT 1 FROM managed_identity_specs LIMIT 1",
        "SELECT 1 FROM operations INDEXED BY managed_identity_operations "
        "WHERE method='managed_identity' LIMIT 1",
    ]
    assert statements.count("BEGIN") == 1
    assert statements.count("COMMIT") == 1
    assert statements.count("PRAGMA query_only=ON") == 1
    assert statements.index("PRAGMA query_only=ON") < statements.index(queries[0])
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for statement in statements)
    assert set(reads) <= allowed
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        plans = [
            " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query))
            for query in queries
        ]
    assert "managed_identity_specs" in plans[0]
    assert "managed_identity_operations" in plans[1]
    assert snapshot(tmp_path) == before


@pytest.mark.unit
@pytest.mark.parametrize("damage", ["retained", "malformed", "orphan"])
def test_workspace_query_refuses_actual_damaged_and_orphan_managed_ownership(
    tmp_path: Path,
    damage: str,
) -> None:
    store = IdentityStore.initialize(tmp_path)
    # Reuse this already-open authority by constructing the native source and genesis.
    selected = "runs/managed-run/specs/003-managed"
    (tmp_path / selected).mkdir(parents=True)
    with inspect_project_tree(tmp_path, selected) as tree:
        manifest = snapshot_source_manifest(trees=(tree,), files=())
    source = store.register_source_context(
        spec_id="003-managed",
        context_id="source",
        operation_id="source-003-managed",
        manifest=manifest,
    )
    store.register_managed_identity(
        spec_id="003-managed",
        operation_id="managed-003-managed",
        request=ManagedIdentityRequest(
            source["workspace_uuid"], source["epoch_uuid"], "managed-run", "source",
            selected, "source-003-managed", manifest.sha256,
        ),
    )
    with closing(sqlite3.connect(tmp_path / DATABASE)) as connection:
        if damage == "malformed":
            connection.execute(
                "UPDATE managed_identity_specs SET request='{}', request_sha256='bad'"
            )
        elif damage == "orphan":
            connection.execute("DELETE FROM managed_identity_specs")
        connection.commit()
    before = snapshot(tmp_path)

    for handle in (store, IdentityStore.open(tmp_path)):
        with pytest.raises(IdentityStoreError) as raised:
            handle.require_unmanaged_workspace()
        assert str(raised.value) == "invalid unmanaged workspace authority or request"
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
    assert snapshot(tmp_path) == before


@pytest.mark.unit
@pytest.mark.parametrize("history", ["empty", "reserve", "import", "source"])
def test_workspace_query_allows_unmanaged_authority_history(tmp_path: Path, history: str) -> None:
    store = IdentityStore.initialize(tmp_path)
    if history == "reserve":
        store.reserve(spec_id="legacy", kind="FR", operation_id="reserve", count=1)
    elif history == "import":
        store.import_identities(
            spec_id="legacy", operation_id="import", definitions=(("FR-old", "Legacy"),)
        )
    elif history == "source":
        selected = "runs/legacy/specs/legacy"
        (tmp_path / selected).mkdir(parents=True)
        with inspect_project_tree(tmp_path, selected) as tree:
            manifest = snapshot_source_manifest(trees=(tree,), files=())
        store.register_source_context(
            spec_id="legacy", context_id="source", operation_id="source", manifest=manifest
        )
    before = snapshot(tmp_path)
    assert store.require_unmanaged_workspace() is None
    assert snapshot(tmp_path) == before


@pytest.mark.unit
@pytest.mark.parametrize("exception", [RuntimeError("private"), KeyboardInterrupt(), GeneratorExit(), SystemExit()])
def test_workspace_query_bounds_ordinary_failures_and_propagates_process_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: BaseException,
) -> None:
    store = IdentityStore.initialize(tmp_path)

    @contextmanager
    def failing(**kwargs: object):
        raise exception
        yield

    monkeypatch.setattr(store, "_transaction", failing)
    if isinstance(exception, Exception):
        with pytest.raises(IdentityStoreError) as raised:
            store.require_unmanaged_workspace()
        assert str(raised.value) == "invalid unmanaged workspace authority or request"
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
    else:
        with pytest.raises(type(exception)):
            store.require_unmanaged_workspace()


@pytest.mark.unit
@pytest.mark.parametrize("parent_present", [False, True])
def test_workspace_guard_preserves_absent_authority_without_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_present: bool,
) -> None:
    from harness.element_identity_legacy_guard import require_legacy_identity_workspace

    if parent_present:
        (tmp_path / ".echelon").mkdir()

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("absent workspace authority must not be opened or initialized")

    monkeypatch.setattr(IdentityStore, "open", unexpected)
    monkeypatch.setattr(IdentityStore, "initialize", unexpected)
    assert require_legacy_identity_workspace(project_root=tmp_path) is None
    assert not (tmp_path / ".echelon/identity").exists()


@pytest.mark.unit
@pytest.mark.parametrize("malformed", ["parent", "leaf"])
def test_workspace_guard_refuses_malformed_present_authority(tmp_path: Path, malformed: str) -> None:
    from harness.element_identity_legacy_guard import require_legacy_identity_workspace

    if malformed == "parent":
        (tmp_path / ".echelon").write_bytes(b"not a directory")
    else:
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon/identity").write_bytes(b"not an authority directory")
    before = snapshot(tmp_path)

    with pytest.raises(IdentityStoreError) as raised:
        require_legacy_identity_workspace(project_root=tmp_path)

    assert str(raised.value) == LEGACY_IDENTITY_EXECUTION_BLOCKED
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert snapshot(tmp_path) == before


@pytest.mark.unit
@pytest.mark.parametrize("exception", [KeyboardInterrupt(), GeneratorExit(), SystemExit()])
def test_workspace_guard_and_graph_translation_propagate_process_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: BaseException,
) -> None:
    import echelon.workspace_graph as graph_module
    import harness.element_identity_legacy_guard as guard_module

    def stopped(*args: object, **kwargs: object) -> None:
        raise exception

    monkeypatch.setattr(guard_module, "_require_existing_unmanaged_authority", stopped)
    with pytest.raises(type(exception)):
        guard_module.require_legacy_identity_workspace(project_root=tmp_path)
    monkeypatch.setattr(graph_module, "require_legacy_identity_workspace", stopped)
    with pytest.raises(type(exception)):
        graph_module._require_legacy_workspace_projection(tmp_path)


@pytest.mark.unit
def test_workspace_graph_translation_bounds_only_identity_store_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph as graph_module

    def blocked(*args: object, **kwargs: object) -> None:
        raise IdentityStoreError("private authority detail")

    monkeypatch.setattr(graph_module, "require_legacy_identity_workspace", blocked)
    with pytest.raises(WorkspaceGraphError) as raised:
        graph_module._require_legacy_workspace_projection(tmp_path)
    assert str(raised.value) == LEGACY_IDENTITY_EXECUTION_BLOCKED
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None

    def unrelated(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unrelated")

    monkeypatch.setattr(graph_module, "require_legacy_identity_workspace", unrelated)
    with pytest.raises(RuntimeError, match="unrelated"):
        graph_module._require_legacy_workspace_projection(tmp_path)


@pytest.mark.unit
def test_direct_workspace_graph_writer_refuses_before_render_with_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph as graph_module

    graph = workspace_graph_record(tmp_path)
    output = tmp_path / ".echelon/runtime/graph/workspace-artifact-graph.json"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing graph\n")
    enroll_managed_spec(tmp_path, "003-managed")
    before = snapshot(tmp_path)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> bytes:
        effects.append("render")
        raise AssertionError("managed graph reached rendering")

    monkeypatch.setattr(graph_module, "render_workspace_graph", forbidden)
    with pytest.raises(WorkspaceGraphError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        graph_module.write_workspace_graph(graph, tmp_path)
    assert effects == []
    assert output.read_bytes() == b"existing graph\n"
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_direct_workspace_audit_writer_refuses_before_parent_or_temp_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph_audit as audit_module

    report = workspace_audit_record(tmp_path)
    enroll_managed_spec(tmp_path, "003-managed")
    output_parent = tmp_path / ".echelon/runtime/graph"
    assert not output_parent.exists()
    before = snapshot(tmp_path)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("prepare")
        raise AssertionError("managed audit reached output preparation")

    monkeypatch.setattr(audit_module, "_prepare_graph_output_path", forbidden)
    with pytest.raises(WorkspaceGraphError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        audit_module.write_workspace_graph_audit(report, tmp_path)
    assert effects == []
    assert not output_parent.exists()
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_managed_workspace_with_legacy_member_rejects_before_all_refresh_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph_refresh as refresh

    canonical_spec(tmp_path, "001-legacy")
    enroll_managed_spec(tmp_path, "999-managed")
    before = snapshot(tmp_path)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("upstream")
        raise AssertionError("managed aggregate reached upstream or output work")

    for name in (
        "_refresh_re_memory",
        "discover_canonical_spec_dirs",
        "build_workspace_graph",
        "write_workspace_graph",
        "audit_workspace_graph",
        "write_workspace_graph_audit",
    ):
        monkeypatch.setattr(refresh, name, forbidden)

    with pytest.raises(WorkspaceGraphError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        refresh.refresh_workspace_graph(tmp_path, write=True)
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_workspace_refresh_preview_remains_read_only_with_managed_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph_refresh as refresh
    from echelon.workspace_graph import WorkspaceGraphBuildResult

    enroll_managed_spec(tmp_path, "003-managed")
    candidate = WorkspaceGraphBuildResult(workspace_graph_record(tmp_path), ())
    report = workspace_audit_record(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        refresh, "build_workspace_graph", lambda root: calls.append("build") or candidate
    )
    monkeypatch.setattr(
        refresh,
        "audit_workspace_graph",
        lambda root, observed: calls.append("audit") or report,
    )
    before = snapshot(tmp_path)

    result = refresh.refresh_workspace_graph(tmp_path, write=False)

    assert result.candidate is candidate
    assert result.report is report
    assert result.outcomes == ()
    assert calls == ["build", "audit"]
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_workspace_cli_write_routes_report_bounded_failure_without_success_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.workspace_graph_refresh as refresh
    from echelon.cli_app import app
    from echelon.workspace_graph import WorkspaceGraphBuildResult
    from typer.testing import CliRunner

    enroll_managed_spec(tmp_path, "003-managed")
    candidate = WorkspaceGraphBuildResult(workspace_graph_record(tmp_path), ())
    report = workspace_audit_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.workspace_graph.build_workspace_graph", lambda root: candidate)
    monkeypatch.setattr("echelon.workspace_graph_audit.audit_workspace_graph", lambda root: report)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("refresh")
        raise AssertionError("managed CLI refresh reached upstream work")

    monkeypatch.setattr(refresh, "_refresh_re_memory", forbidden)
    before = snapshot(tmp_path)
    cases = (
        (["graph", "workspace", "build", "--write"], "Workspace graph built"),
        (["graph", "workspace", "audit", "--write"], "Workspace graph audit"),
        (["graph", "workspace", "refresh", "--write"], "Workspace graph refreshed"),
    )

    for arguments, success in cases:
        result = CliRunner().invoke(app, arguments)
        assert result.exit_code == 2
        assert LEGACY_IDENTITY_EXECUTION_BLOCKED in result.output
        assert success not in result.output
        assert snapshot(tmp_path) == before
    assert effects == []


@pytest.mark.unit
@pytest.mark.parametrize("command", ["build", "audit", "refresh"])
def test_spec_graph_cli_write_routes_reject_before_owned_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    from echelon.cli_app import app
    from typer.testing import CliRunner

    spec_id = "003-managed"
    enroll_managed_spec(tmp_path, spec_id)
    spec_dir = canonical_spec(tmp_path, spec_id)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_graph.build_spec_graph",
        lambda root, selector: spec_graph_record(spec_id),
    )
    monkeypatch.setattr(
        "echelon.spec_graph_audit.audit_spec_graph",
        lambda root, selector: spec_graph_audit_record(spec_id),
    )
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("OwnedOutputCommit")
        raise AssertionError("managed graph reached commit construction")

    monkeypatch.setattr("echelon.owned_output_commit.OwnedOutputCommit", forbidden)
    before = snapshot(tmp_path)

    result = CliRunner().invoke(app, ["graph", command, spec_id, "--write"])

    assert result.exit_code == 2
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED in result.output
    assert effects == []
    assert not spec_dir.joinpath("spec-artifact-graph.json").exists()
    assert not spec_dir.joinpath("spec-artifact-graph-audit.json").exists()
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_graph_commit_checks_physical_spec_name_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import _graph_output_commit

    managed = "999-managed"
    enroll_managed_spec(tmp_path, managed)
    target = tmp_path / f"runs/managed-run/specs/{managed}"
    specs = tmp_path / "specs"
    specs.mkdir()
    alias = specs / "001-legacy-alias"
    alias.symlink_to(target)
    monkeypatch.chdir(tmp_path)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("OwnedOutputCommit")
        raise AssertionError("physical managed target reached commit construction")

    monkeypatch.setattr("echelon.owned_output_commit.OwnedOutputCommit", forbidden)
    before = snapshot(tmp_path)
    with pytest.raises(Exception) as raised:
        _graph_output_commit(alias)
    assert str(raised.value) == LEGACY_IDENTITY_EXECUTION_BLOCKED
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.unit
@pytest.mark.parametrize("physical_output", [False, True])
def test_memory_audit_cli_rejects_selected_or_physical_managed_output_before_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    physical_output: bool,
) -> None:
    from echelon.cli_app import app
    from typer.testing import CliRunner

    managed = "999-managed" if physical_output else "003-managed"
    selected = "001-legacy" if physical_output else managed
    enroll_managed_spec(tmp_path, managed)
    canonical_spec(tmp_path, selected)
    output = (
        tmp_path / f"runs/managed-run/specs/{managed}"
        if physical_output
        else tmp_path / "specs" / selected
    )
    report = memory_audit_record(tmp_path, selected, output=output)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda root, selector, probe_retrieval=False: report,
    )
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("write_audit_reports")
        raise AssertionError("managed memory audit reached report publication")

    monkeypatch.setattr("echelon.mempalace_audit.write_audit_reports", forbidden)
    before = snapshot(tmp_path)
    result = CliRunner().invoke(
        app, ["spec", "memory", "audit", selected, "--write"]
    )
    assert result.exit_code == 2
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED in result.output
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_memory_audit_unavailable_and_earlier_error_do_not_enter_write_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from echelon.mempalace_requirements import SpecMemoryError
    from typer.testing import CliRunner

    enroll_managed_spec(tmp_path, "003-managed")
    monkeypatch.chdir(tmp_path)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("write")
        raise AssertionError("unavailable audit reached report publication")

    monkeypatch.setattr("echelon.mempalace_audit.write_audit_reports", forbidden)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda root, selector, probe_retrieval=False: memory_audit_record(
            tmp_path, "003-managed", status="unavailable"
        ),
    )
    before = snapshot(tmp_path)
    unavailable = CliRunner().invoke(
        app, ["spec", "memory", "audit", "003-managed", "--write"]
    )
    assert unavailable.exit_code == 2
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED not in unavailable.output
    assert effects == []
    assert snapshot(tmp_path) == before

    def earlier(*args: object, **kwargs: object) -> None:
        raise SpecMemoryError("native selector failure")

    monkeypatch.setattr("echelon.mempalace_audit.audit_spec_memory", earlier)
    failed = CliRunner().invoke(
        app, ["spec", "memory", "audit", "003-managed", "--write"]
    )
    assert failed.exit_code == 2
    assert "native selector failure" in failed.output
    assert LEGACY_IDENTITY_EXECUTION_BLOCKED not in failed.output
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_unrelated_managed_spec_preserves_native_legacy_graph_and_memory_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from typer.testing import CliRunner

    enroll_managed_spec(tmp_path, "999-managed")
    legacy_dir = canonical_spec(tmp_path, "001-legacy")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_graph.build_spec_graph",
        lambda root, selector: spec_graph_record("001-legacy"),
    )
    graph_result = CliRunner().invoke(
        app, ["graph", "build", "001", "--write"]
    )
    assert graph_result.exit_code == 0
    graph_payload = json.loads(
        legacy_dir.joinpath("spec-artifact-graph.json").read_text(encoding="utf-8")
    )
    assert graph_payload["spec_id"] == "001-legacy"
    assert graph_payload["schema_version"] == 1

    report = memory_audit_record(tmp_path, "001-legacy")
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda root, selector, probe_retrieval=False: report,
    )
    memory_result = CliRunner().invoke(
        app, ["spec", "memory", "audit", "001", "--write"]
    )
    assert memory_result.exit_code == 0
    audit_bytes = legacy_dir.joinpath("mempalace-audit.json").read_bytes()
    assert audit_bytes.endswith(b"\n")
    assert json.loads(audit_bytes)["spec_id"] == "001-legacy"
    assert legacy_dir.joinpath("mempalace-audit.md").is_file()


@pytest.mark.unit
def test_managed_selected_read_only_graph_and_memory_commands_remain_usable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from typer.testing import CliRunner

    spec_id = "003-managed"
    enroll_managed_spec(tmp_path, spec_id)
    canonical_spec(tmp_path, spec_id)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_graph.build_spec_graph",
        lambda root, selector: spec_graph_record(spec_id),
    )
    monkeypatch.setattr(
        "echelon.spec_graph_audit.audit_spec_graph",
        lambda root, selector: spec_graph_audit_record(spec_id),
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda root, selector, probe_retrieval=False: memory_audit_record(tmp_path, spec_id),
    )
    before = snapshot(tmp_path)
    commands = (
        ["graph", "build", spec_id],
        ["graph", "audit", spec_id],
        ["spec", "memory", "audit", spec_id],
    )
    for arguments in commands:
        result = CliRunner().invoke(app, arguments)
        assert result.exit_code == 0
        assert LEGACY_IDENTITY_EXECUTION_BLOCKED not in result.output
        assert snapshot(tmp_path) == before


@pytest.mark.unit
def test_rootless_low_level_graph_and_exact_byte_writers_remain_trusted_primitives(
    tmp_path: Path,
) -> None:
    from echelon.spec_graph import write_spec_graph
    from echelon.workspace_graph import write_workspace_graph_bytes

    spec_id = "003-managed"
    enroll_managed_spec(tmp_path, spec_id)
    spec_dir = canonical_spec(tmp_path, spec_id)

    spec_path = write_spec_graph(spec_graph_record(spec_id), spec_dir)
    exact_path = tmp_path / "explicit-output" / "workspace-export.bin"
    written = write_workspace_graph_bytes(exact_path, b"trusted exact bytes\n")

    assert json.loads(spec_path.read_bytes())["spec_id"] == spec_id
    assert written == exact_path
    assert exact_path.read_bytes() == b"trusted exact bytes\n"
