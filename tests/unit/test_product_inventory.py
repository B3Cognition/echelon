from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from harness.product_inventory import product_evidence_fingerprint, write_product_inventory


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_product_inventory_uses_git_deliverable_boundary(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")

    (project / ".gitignore").write_text(
        "ignored.txt\n__pycache__/\n",
        encoding="utf-8",
    )
    (project / "README.md").write_text("# Product\n", encoding="utf-8")
    (project / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    (project / ".product-policy").write_text("strict\n", encoding="utf-8")
    (project / ".harness-build-status.json").write_text(
        '{"status":"done"}\n',
        encoding="utf-8",
    )
    (project / "notes.txt").write_text("untracked evidence\n", encoding="utf-8")
    (project / "ignored.txt").write_text("generated\n", encoding="utf-8")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "hello.pyc").write_bytes(b"generated")

    prosaic = project / ".echelon" / "prosaic"
    runtime = project / ".echelon" / "runtime"
    prosaic.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (prosaic / "README.md").write_text("control prose\n", encoding="utf-8")
    (runtime / "hello.py").write_text("control runtime\n", encoding="utf-8")
    (project / ".echelon" / "config.yml").write_text("provider: codex\n", encoding="utf-8")

    _git(
        project,
        "add",
        ".gitignore",
        "README.md",
        "hello.py",
        ".product-policy",
        ".harness-build-status.json",
        ".echelon",
    )

    verify_run_dir = tmp_path / "verify-run"
    result = write_product_inventory(project, verify_run_dir)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["inventory_source"] == "git-deliverable"
    assert payload["excluded_control_roots"] == [".echelon", ".git"]
    assert payload["excluded_control_paths"] == [".harness-build-status.json"]
    assert [entry["path"] for entry in payload["entries"]] == [
        ".gitignore",
        ".product-policy",
        "README.md",
        "hello.py",
        "notes.txt",
    ]
    assert payload["summary"] == {
        "entry_count": 5,
        "regular_file_count": 5,
        "symlink_count": 0,
    }
    assert payload["basename_counts"]["README.md"] == 1
    assert payload["basename_counts"]["hello.py"] == 1
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "| `README.md` | file |" in markdown
    assert "| `.echelon/" not in markdown


def test_product_inventory_falls_back_without_discarding_hidden_product_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    control = project / ".echelon" / "runtime"
    control.mkdir(parents=True)
    (control / "README.md").write_text("control\n", encoding="utf-8")

    result = write_product_inventory(project, tmp_path / "verify-run")

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["inventory_source"] == "filesystem-fallback"
    assert [entry["path"] for entry in payload["entries"]] == [
        ".env.example",
        "app.py",
    ]


def test_product_inventory_skips_tracked_file_deleted_before_inventory(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    artifact = project / "test-results" / "error-context.md"
    artifact.parent.mkdir()
    artifact.write_text("old run\n", encoding="utf-8")
    _git(project, "add", "app.py", "test-results/error-context.md")
    artifact.unlink()

    result = write_product_inventory(project, tmp_path / "verify-run")

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert [entry["path"] for entry in payload["entries"]] == ["app.py"]
    assert payload["summary"]["entry_count"] == 1


def test_product_evidence_fingerprint_ignores_control_plane_but_tracks_product(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    (project / "app.py").write_text("print('one')\n", encoding="utf-8")
    (project / ".echelon" / "runtime").mkdir(parents=True)
    (project / ".echelon" / "runtime" / "phase.md").write_text(
        "one\n", encoding="utf-8"
    )
    _git(project, "add", "app.py", ".echelon")

    original = product_evidence_fingerprint(project)
    (project / ".echelon" / "runtime" / "phase.md").write_text(
        "two\n", encoding="utf-8"
    )
    assert product_evidence_fingerprint(project) == original

    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"generated")
    assert product_evidence_fingerprint(project) == original

    (project / "app.py").write_text("print('two')\n", encoding="utf-8")
    assert product_evidence_fingerprint(project) != original


def test_product_evidence_fingerprint_ignores_verifier_output_roots(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    (project / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
    _git(project, "add", "app.ts")
    original = product_evidence_fingerprint(project)

    for relative in (
        "test-results/run/trace.zip",
        "playwright-report/index.html",
        "coverage/coverage-final.json",
    ):
        output = project / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("generated\n", encoding="utf-8")
        _git(project, "add", relative)

    assert product_evidence_fingerprint(project) == original


def test_write_product_inventory_cli_stamps_existing_verify_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _git(project, "add", "app.py")
    verify_run_dir = tmp_path / "verify-run"
    verify_run_dir.mkdir()
    (verify_run_dir / "state.json").write_text("{}\n", encoding="utf-8")

    completed = _run_harness(
        ["write-product-inventory", str(project), str(verify_run_dir)]
    )

    assert completed.returncode == 0, completed.stderr
    assert (verify_run_dir / "product-inventory.json").is_file()
    assert (verify_run_dir / "product-inventory.md").is_file()
    state = json.loads((verify_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["product_inventory"] == "ready"
    assert state["product_inventory_count"] == 1
