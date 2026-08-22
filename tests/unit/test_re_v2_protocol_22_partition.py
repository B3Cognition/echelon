from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
from typing import Mapping

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.partition import (
    DomainPartitionDescriptorV1,
    FileRecordV1,
    ImplementationAuthorityV1,
    PartitionAuthoritiesV1,
    Protocol22PartitionError,
    SourcePartitionIdentityInputV1,
    WorkspacePartitionCatalogV1,
    build_workspace_partition_catalog,
    domain_key,
    source_partition_id,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.workspace_snapshot import capture_workspace_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        },
    ).stdout


def _write_files(root: Path, files: Mapping[str, str | bytes]) -> None:
    for relative, payload in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        else:
            target.write_text(payload, encoding="utf-8")


def _commit(repo: Path, message: str = "fixture") -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def _repo(path: Path, files: Mapping[str, str | bytes]) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    _write_files(path, files)
    _commit(path)
    return path


def _source(source_id: str, path: str) -> SourceRoot:
    return SourceRoot(id=source_id, path=path, git_present=True)


def _manifest(workspace: Path, sources: tuple[SourceRoot, ...]) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=workspace.resolve(),
            git_role="orchestration",
            git_present=False,
        ),
        sources=sources,
    )


def _authorities() -> PartitionAuthoritiesV1:
    return PartitionAuthoritiesV1(
        partitioner=ImplementationAuthorityV1(
            id="existing-domain-partitioner",
            version="5",
            implementation_digest=content_digest(b"partitioner-v5"),
        ),
        ownership_policy=ImplementationAuthorityV1(
            id="explicit-domain-ownership",
            version="1",
            implementation_digest=content_digest(b"ownership-v1"),
        ),
    )


def _api_files() -> dict[str, str | bytes]:
    return {
        "package.json": "{}\n",
        "README.md": "API\n",
        "config/runtime.yml": "port: 8080\n",
        "shared/config.yml": "region: eu\n",
        "assets/logo.bin": b"\x89PNG",
        "src/orders/handler.py": "def handle():\n    return 'ok'\n",
        "src/orders/model.py": "class Order:\n    pass\n",
        "src/users/handler.py": "def handle():\n    return 'ok'\n",
        "src/users/model.py": "class User:\n    pass\n",
    }


def _capture_catalog(
    workspace: Path,
    sources: tuple[SourceRoot, ...],
    snapshot_directory: Path,
) -> WorkspacePartitionCatalogV1:
    snapshot = capture_workspace_snapshot(workspace, sources, snapshot_directory)
    return build_workspace_partition_catalog(
        snapshot,
        _manifest(workspace, sources),
        _authorities(),
    )


def _source_descriptor(catalog: WorkspacePartitionCatalogV1, source_id: str):
    return next(source for source in catalog.sources if source.source_id == source_id)


def _domain(catalog: WorkspacePartitionCatalogV1, source_id: str, root: str):
    source = _source_descriptor(catalog, source_id)
    return next(domain for domain in source.domains if domain.source_relative_root == root)


@pytest.mark.unit
def test_domain_content_edit_does_not_change_partition_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    api = _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    before = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    (api / "src/orders/handler.py").write_text("changed = True\n", encoding="utf-8")
    _commit(api, "change orders")
    after = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    old = _domain(before, "api", "src/orders")
    new = _domain(after, "api", "src/orders")
    assert old.domain_content_id != new.domain_content_id
    assert old.domain_partition_id == new.domain_partition_id
    assert _source_descriptor(before, "api").source_content_id != _source_descriptor(
        after, "api"
    ).source_content_id
    assert _source_descriptor(before, "api").source_partition_id == _source_descriptor(
        after, "api"
    ).source_partition_id
    assert _domain(before, "api", "src/users").domain_content_id == _domain(
        after, "api", "src/users"
    ).domain_content_id


@pytest.mark.unit
def test_sibling_domain_insertion_preserves_stable_domain_key(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    api = _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    before = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    _write_files(
        api,
        {
            "src/accounts/handler.py": "def handle():\n    pass\n",
            "src/accounts/model.py": "class Account:\n    pass\n",
        },
    )
    _commit(api, "add accounts")
    after = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    old = _domain(before, "api", "src/orders")
    new = _domain(after, "api", "src/orders")
    assert old.domain_key == new.domain_key
    assert old.presentation_domain_id != new.presentation_domain_id
    assert old.domain_content_id == new.domain_content_id
    assert old.domain_partition_id == new.domain_partition_id
    assert _source_descriptor(before, "api").source_partition_id != _source_descriptor(
        after, "api"
    ).source_partition_id


@pytest.mark.unit
def test_catalog_is_deterministic_across_declared_source_order(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _repo(workspace / "sources" / "api", _api_files())
    _repo(
        workspace / "sources" / "web",
        {
            "package.json": "{}\n",
            "src/ui/a.ts": "export const a = 1;\n",
            "src/ui/b.ts": "export const b = 2;\n",
        },
    )
    ordered = (
        _source("api", "sources/api"),
        _source("web", "sources/web"),
    )
    snapshot = capture_workspace_snapshot(workspace, ordered, tmp_path / "snapshots")

    first = build_workspace_partition_catalog(
        snapshot, _manifest(workspace, ordered), _authorities()
    )
    second = build_workspace_partition_catalog(
        snapshot, _manifest(workspace, tuple(reversed(ordered))), _authorities()
    )

    assert first.to_json_dict() == second.to_json_dict()
    assert [source.source_id for source in first.sources] == ["api", "web"]
    assert load_canonical_object(
        canonical_json_bytes(first.to_json_dict()),
        WorkspacePartitionCatalogV1.from_json_dict,
    ) == first


@pytest.mark.unit
def test_catalog_reads_partition_and_content_only_from_frozen_snapshot(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    api = _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    snapshot = capture_workspace_snapshot(workspace, sources, tmp_path / "snapshots")
    expected_hash = content_digest(b"def handle():\n    return 'ok'\n")

    (api / "src/orders/handler.py").write_text(
        "dirty checkout bytes\n", encoding="utf-8"
    )
    catalog = build_workspace_partition_catalog(
        snapshot,
        _manifest(workspace, sources),
        _authorities(),
    )
    records = {
        record.source_relative_path: record
        for record in _source_descriptor(catalog, "api").files
    }

    assert records["src/orders/handler.py"].content_hash == expected_hash


@pytest.mark.unit
def test_sibling_source_edit_does_not_change_untouched_source_ids(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _repo(workspace / "sources" / "api", _api_files())
    web = _repo(
        workspace / "sources" / "web",
        {
            "package.json": "{}\n",
            "src/ui/a.ts": "export const a = 1;\n",
            "src/ui/b.ts": "export const b = 2;\n",
        },
    )
    sources = (
        _source("api", "sources/api"),
        _source("web", "sources/web"),
    )
    before = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    (web / "src/ui/a.ts").write_text("export const a = 3;\n", encoding="utf-8")
    _commit(web, "change web")
    after = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    old_api = _source_descriptor(before, "api")
    new_api = _source_descriptor(after, "api")
    assert old_api.source_content_id == new_api.source_content_id
    assert old_api.source_partition_id == new_api.source_partition_id
    assert [domain.domain_content_id for domain in old_api.domains] == [
        domain.domain_content_id for domain in new_api.domains
    ]


@pytest.mark.unit
def test_shared_support_content_edit_invalidates_domain_content_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    api = _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    before = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    (api / "shared/config.yml").write_text("region: us\n", encoding="utf-8")
    _commit(api, "change shared support")
    after = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    for root in ("src/orders", "src/users"):
        old = _domain(before, "api", root)
        new = _domain(after, "api", root)
        assert old.domain_content_id != new.domain_content_id
        assert old.domain_partition_id == new.domain_partition_id
    assert _source_descriptor(before, "api").source_partition_id == _source_descriptor(
        after, "api"
    ).source_partition_id


@pytest.mark.unit
def test_membership_and_support_path_changes_rekey_partition_identities(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    api = _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    before = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    _write_files(
        api,
        {
            "src/orders/service.py": "def run():\n    pass\n",
            "shared/contracts.yml": "version: 1\n",
        },
    )
    _commit(api, "change read-set membership")
    after = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    old_orders = _domain(before, "api", "src/orders")
    new_orders = _domain(after, "api", "src/orders")
    old_users = _domain(before, "api", "src/users")
    new_users = _domain(after, "api", "src/users")
    assert old_orders.domain_partition_id != new_orders.domain_partition_id
    assert old_users.domain_partition_id != new_users.domain_partition_id
    assert _source_descriptor(before, "api").source_partition_id != _source_descriptor(
        after, "api"
    ).source_partition_id
    assert "service.py" in new_orders.owned_domain_relative_paths
    assert "shared/contracts.yml" in new_users.supporting_source_relative_paths


@pytest.mark.unit
def test_unrelated_source_asset_does_not_enter_domain_read_sets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    api = _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    before = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    _write_files(api, {"assets/new-logo.bin": b"new"})
    _commit(api, "add source-only asset")
    after = _capture_catalog(workspace, sources, tmp_path / "snapshots")

    assert _source_descriptor(before, "api").source_partition_id != _source_descriptor(
        after, "api"
    ).source_partition_id
    assert [domain.domain_partition_id for domain in _source_descriptor(before, "api").domains] == [
        domain.domain_partition_id for domain in _source_descriptor(after, "api").domains
    ]


@pytest.mark.unit
def test_file_records_pin_raw_line_and_text_status_rules(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _repo(
        workspace / "source",
        {
            "package.json": "{}\n",
            "src/a.py": "pass\n",
            "empty.txt": b"",
            "crlf.txt": b"one\r\ntwo\r\n",
            "unterminated.txt": b"one\ntwo",
            "nul.bin": b"one\x00two",
            "invalid.bin": b"\xff\n",
            "tool.sh": "#!/bin/sh\necho ok\n",
        },
    )
    (workspace / "source" / "tool.sh").chmod(0o755)
    _commit(workspace / "source", "make executable")
    catalog = _capture_catalog(
        workspace,
        (_source("source", "source"),),
        tmp_path / "snapshots",
    )
    records = {
        record.source_relative_path: record
        for record in _source_descriptor(catalog, "source").files
    }

    assert (records["empty.txt"].line_count, records["empty.txt"].text_status) == (
        0,
        "eligible_utf8",
    )
    assert (records["crlf.txt"].line_count, records["crlf.txt"].text_status) == (
        2,
        "eligible_utf8",
    )
    assert records["unterminated.txt"].line_count == 2
    assert records["nul.bin"].text_status == "contains_nul"
    assert (records["invalid.bin"].line_count, records["invalid.bin"].text_status) == (
        1,
        "invalid_utf8",
    )
    assert (records["tool.sh"].mode, records["tool.sh"].object_kind) == (
        "100755",
        "regular",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "kind", "status"),
    (
        ("100644", "symlink", "non_regular"),
        ("100755", "gitlink", "non_regular"),
        ("120000", "regular", "eligible_utf8"),
        ("160000", "symlink", "non_regular"),
        ("120000", "symlink", "eligible_utf8"),
    ),
)
def test_file_record_rejects_invalid_mode_kind_status_pairs(
    mode: str,
    kind: str,
    status: str,
) -> None:
    with pytest.raises(Protocol22PartitionError):
        FileRecordV1(
            source_relative_path="src/file",
            mode=mode,  # type: ignore[arg-type]
            object_kind=kind,  # type: ignore[arg-type]
            content_hash=content_digest(b"payload"),
            byte_count=7,
            line_count=1,
            text_status=status,  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_nonregular_file_record_preserves_target_bytes_but_has_zero_lines() -> None:
    record = FileRecordV1(
        source_relative_path="linked",
        mode="120000",
        object_kind="symlink",
        content_hash=content_digest(b"target"),
        byte_count=6,
        line_count=0,
        text_status="non_regular",
    )

    assert record.byte_count == 6
    with pytest.raises(Protocol22PartitionError, match="zero line"):
        FileRecordV1(
            source_relative_path="linked",
            mode="120000",
            object_kind="symlink",
            content_hash=content_digest(b"target"),
            byte_count=6,
            line_count=1,
            text_status="non_regular",
        )


@pytest.mark.unit
def test_authority_changes_have_exact_partition_invalidation_boundaries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    _repo(workspace / "sources" / "api", _api_files())
    sources = (_source("api", "sources/api"),)
    snapshot = capture_workspace_snapshot(workspace, sources, tmp_path / "snapshots")
    manifest = _manifest(workspace, sources)
    authorities = _authorities()
    before = build_workspace_partition_catalog(snapshot, manifest, authorities)

    partitioner_changed = replace(
        authorities,
        partitioner=replace(
            authorities.partitioner,
            implementation_digest=content_digest(b"changed partitioner"),
        ),
    )
    ownership_changed = replace(
        authorities,
        ownership_policy=replace(
            authorities.ownership_policy,
            version="2",
            implementation_digest=content_digest(b"ownership-v2"),
        ),
    )
    after_partitioner = build_workspace_partition_catalog(
        snapshot, manifest, partitioner_changed
    )
    after_ownership = build_workspace_partition_catalog(
        snapshot, manifest, ownership_changed
    )

    old = _domain(before, "api", "src/orders")
    partitioned = _domain(after_partitioner, "api", "src/orders")
    owned = _domain(after_ownership, "api", "src/orders")
    assert old.domain_key == partitioned.domain_key
    assert old.domain_content_id == partitioned.domain_content_id
    assert old.domain_partition_id != partitioned.domain_partition_id
    assert old.domain_key != owned.domain_key
    assert old.domain_content_id != owned.domain_content_id
    assert old.domain_partition_id != owned.domain_partition_id


@pytest.mark.unit
def test_partition_models_reject_noncanonical_order_and_unknown_fields() -> None:
    authority = _authorities()
    key = domain_key("api", "src/orders", authority.ownership_policy.version)
    domain = DomainPartitionDescriptorV1(
        domain_key=key,
        presentation_domain_id="001-re-src-orders",
        source_relative_root="src/orders",
        domain_partition_id=content_digest(b"partition"),
        owned_domain_relative_paths=("handler.py",),
        supporting_source_relative_paths=("shared/config.yml",),
    )
    identity = SourcePartitionIdentityInputV1(
        source_id="api",
        partitioner=authority.partitioner,
        ownership_policy=authority.ownership_policy,
        source_supporting_paths=("shared/config.yml",),
        domains=(domain,),
    )

    assert source_partition_id(identity) == content_digest(identity.to_json_dict())
    with pytest.raises(Protocol22PartitionError, match="unknown fields"):
        FileRecordV1.from_json_dict(
            {
                "source_relative_path": "src/file.py",
                "mode": "100644",
                "object_kind": "regular",
                "content_hash": content_digest(b"pass\n"),
                "byte_count": 5,
                "line_count": 1,
                "text_status": "eligible_utf8",
                "extra": True,
            }
        )
    with pytest.raises(Protocol22PartitionError, match="sorted"):
        replace(
            identity,
            source_supporting_paths=("z.yml", "a.yml"),
        )


@pytest.mark.unit
def test_catalog_rejects_workspace_declaration_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _repo(workspace / "sources" / "api", _api_files())
    source = _source("api", "sources/api")
    snapshot = capture_workspace_snapshot(workspace, (source,), tmp_path / "snapshots")
    wrong = replace(source, path="renamed/api")

    with pytest.raises(Protocol22PartitionError, match="declared sources"):
        build_workspace_partition_catalog(
            snapshot,
            _manifest(workspace, (wrong,)),
            _authorities(),
        )
