from __future__ import annotations

import json
from pathlib import Path

from harness.re_cache import ReCacheRecord, cache_source_dir, write_cache_record
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.squad import SquadController
from harness.squad_state import SquadStateStore


class _TerminalGraph:
    def entry_phase(self) -> str:
        return "DONE"

    def all_phase_ids(self) -> set[str]:
        return {"DONE"}


def _write_source(root: Path, source_id: str) -> None:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    (source / "package.json").write_text(f'{{"name":"{source_id}"}}\n', encoding="utf-8")
    (source / "index.ts").write_text(f"export const id = '{source_id}';\n", encoding="utf-8")


def _cache_source(root: Path, cache_root: Path, source_id: str, profile: ReFingerprintProfile) -> None:
    source = root / "sources" / source_id
    fingerprint = fingerprint_source(source, profile)
    output = root / "tmp-output" / source_id
    output.mkdir(parents=True)
    (output / "analysis.json").write_text(
        json.dumps({"repo_name": source_id, "metadata": {"total_files": 1}}) + "\n",
        encoding="utf-8",
    )
    (output / "re-context.md").write_text(f"# {source_id} context\n", encoding="utf-8")
    write_cache_record(
        output,
        cache_source_dir(cache_root, source_id, fingerprint),
        ReCacheRecord(
            source_id=source_id,
            source_path=f"sources/{source_id}",
            fingerprint=fingerprint,
            profile={"profile": profile.profile, "depth": profile.depth},
        ),
    )


def test_squad_initialization_materializes_re_plan_and_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "prosaic"):
        _write_source(root, source_id)
    cache_root = root / ".echelon" / "cache" / "re"
    profile = ReFingerprintProfile()
    _cache_source(root, cache_root, "original-a", profile)

    squad_dir = root / "runs" / "run-1"
    store = SquadStateStore(squad_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=_TerminalGraph(),
        ext_dir=root / "ext",
        project_root=root,
        squad_dir=squad_dir,
        target_source="prosaic",
    )

    result = controller.run(user_message="add prosaic feature")

    assert result.status == "done"
    state = store.load()
    assert state["re_policy"] == "target-changed"
    assert state["requested_re_policy"] == ""
    assert state["target_source"] == "prosaic"
    assert state["re_refresh_sources"] == ["prosaic"]
    assert state["re_missing_sources"] == []
    assert state["re_artifacts"]["manifest"] == str(squad_dir / "re" / "workspace-manifest.json")
    assert state["re_artifacts"]["per_repo"] == [str(squad_dir / "re" / "original-a")]
    assert state["re_artifacts"]["re_contexts"] == [
        str(squad_dir / "re" / "original-a" / "re-context.md")
    ]
    assert (squad_dir / "re" / "original-a" / "analysis.json").is_file()
    assert not (squad_dir / "re" / "prosaic").exists()

    source_index = json.loads((squad_dir / "re" / "re-source-index.json").read_text())
    assert {source["id"]: source["action"] for source in source_index["sources"]} == {
        "original-a": "reuse",
        "prosaic": "refresh",
    }
