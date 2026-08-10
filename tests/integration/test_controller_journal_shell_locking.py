"""Cross-process coverage for every reasoning-journal shell entry point."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness.journal_entry_validator import (
    append_indexed_reasoning_journal_entries,
)
from harness.squad_completion import reasoning_journal_lock


ROOT = Path(__file__).resolve().parents[2]
HORMONE_HOOK = ROOT / "scripts/bash/post-dispatch-hormone-update.sh"
LEGACY_APPEND = ROOT / "extension/scripts/bash/journal-append.sh"


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = (
        source_path
        + (
            os.pathsep + environment["PYTHONPATH"]
            if environment.get("PYTHONPATH")
            else ""
        )
    )
    return environment


def _prepare_legacy_append(
    workspace: Path,
) -> tuple[Path, list[str], dict[str, str], Path]:
    squad_dir = workspace / ".specify/squad"
    squad_dir.mkdir(parents=True)
    entry = json.dumps(
        {
            "id": "LEGACY-1",
            "type": "future_signal",
            "phase": "phase3-plan",
            "agent": "legacy-shell",
            "timestamp": "2026-07-23T10:00:00Z",
            "data": {"writer": "legacy"},
        }
    )
    return (
        squad_dir,
        [
            "bash",
            str(LEGACY_APPEND),
            "--entry",
            entry,
            "--journal-path",
            str(squad_dir / "reasoning-journal.jsonl"),
        ],
        _environment(),
        workspace,
    )


def _prepare_hormone_hook(
    workspace: Path,
) -> tuple[Path, list[str], dict[str, str], Path]:
    squad_dir = workspace / "runs/run-shell-lock"
    squad_dir.mkdir(parents=True)
    (workspace / "runs/.current").write_text("run-shell-lock\n", encoding="utf-8")
    (workspace / ".echelon").mkdir()
    shutil.copy(
        ROOT / "runtime/config-template.yml",
        workspace / ".echelon/config.yml",
    )
    state = squad_dir / "state.json"
    state.write_text(
        json.dumps(
            {
                "iteration": 3,
                "phase": "build-2-implement",
                "thresholds": {
                    "token_budget_k": 1000,
                    "max_squad_iterations": 10,
                },
                "token_ledger": {"total_estimated_tokens": 200000},
                "autonomy_mode": "banzai",
                "quality_scores": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    environment = _environment()
    environment["ENDOCRINE_STATE_FILE"] = str(state)
    environment["ENDOCRINE_SQUAD_DIR"] = str(squad_dir)
    environment["ENDOCRINE_CONFIG_FILE"] = str(workspace / ".echelon/config.yml")
    subprocess.run(
        ["bash", str(ROOT / "runtime/scripts/bash/endocrine.sh"), "init"],
        cwd=workspace,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    result = workspace / "result.yaml"
    result.write_text("verdict: PASS\n", encoding="utf-8")
    return (
        squad_dir,
        [
            "bash",
            str(HORMONE_HOOK),
            "--agent",
            "SAGE",
            "--dispatch-id",
            "D-SHELL-LOCK",
            "--result-file",
            str(result),
        ],
        environment,
        workspace,
    )


_SHELL_PREPARERS = {
    "hormone_hook": _prepare_hormone_hook,
    "legacy_append": _prepare_legacy_append,
}


def _start_python_writer(
    squad_dir: Path,
    environment: dict[str, str],
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path;"
                "from harness.journal_entry_validator import "
                "append_reasoning_journal_entries;"
                f"append_reasoning_journal_entries(Path({str(squad_dir)!r}),"
                "[{'type':'future_signal','data':{'writer':'python'}}],"
                "phase_id='phase3-plan')"
            ),
        ],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.integration
@pytest.mark.parametrize("writer_name", tuple(_SHELL_PREPARERS))
def test_real_shell_writer_shares_lock_with_python_writer(
    tmp_path: Path,
    writer_name: str,
) -> None:
    squad_dir, command, environment, cwd = _SHELL_PREPARERS[
        writer_name
    ](tmp_path / writer_name)
    journal = squad_dir / "reasoning-journal.jsonl"
    seed_bytes = b""
    if writer_name == "hormone_hook":
        seed_bytes = (
            b'{"id":"RJ-099","type":"seed","data":{"keep":true}}\n'
        )
        journal.write_bytes(seed_bytes)
        (squad_dir / "reasoning-journal-index.json").write_text(
            '{"last_entry_id":"RJ-099","unrelated":"preserve"}\n',
            encoding="utf-8",
        )
    shell: subprocess.Popen[str] | None = None
    python_writer: subprocess.Popen[str] | None = None
    try:
        with reasoning_journal_lock(squad_dir):
            shell = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            python_writer = _start_python_writer(
                squad_dir,
                environment,
            )
            if writer_name == "hormone_hook":
                time.sleep(1.0)
                assert shell.poll() is None
                assert journal.read_bytes() == seed_bytes
                probe = (
                    b'{"id":"RJ-100","type":"lock_probe",'
                    b'"data":{"authorized":true}}\n'
                )
                journal.write_bytes(seed_bytes + probe)
                (
                    squad_dir / "reasoning-journal-index.json"
                ).write_text(
                    '{"last_entry_id":"RJ-100",'
                    '"unrelated":"preserve"}\n',
                    encoding="utf-8",
                )
            else:
                time.sleep(1.0)
            assert shell.poll() is None
            assert python_writer.poll() is None
        shell_stdout, shell_stderr = shell.communicate(timeout=15)
        python_stdout, python_stderr = python_writer.communicate(timeout=15)
    finally:
        for process in (shell, python_writer):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert shell.returncode == 0, shell_stdout + shell_stderr
    assert python_writer.returncode == 0, python_stdout + python_stderr
    rows = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 2
    identifiers = [
        row["id"] for row in rows if type(row.get("id")) in (int, str)
    ]
    assert len(identifiers) == len(set(identifiers))
    if writer_name == "hormone_hook":
        endocrine_ids = [
            row["id"]
            for row in rows
            if row.get("type") == "endocrine_event"
        ]
        assert endocrine_ids
        assert min(int(value.removeprefix("RJ-")) for value in endocrine_ids) == 101
        index = json.loads(
            (
                squad_dir / "reasoning-journal-index.json"
            ).read_text(encoding="utf-8")
        )
        assert index["last_entry_id"] == endocrine_ids[-1]
        assert index["unrelated"] == "preserve"


@pytest.mark.integration
@pytest.mark.parametrize("writer_name", tuple(_SHELL_PREPARERS))
def test_real_shell_writer_fails_without_partial_malformed_append(
    tmp_path: Path,
    writer_name: str,
) -> None:
    squad_dir, command, environment, cwd = _SHELL_PREPARERS[
        writer_name
    ](tmp_path / f"malformed-{writer_name}")
    journal = squad_dir / "reasoning-journal.jsonl"
    journal.write_bytes(b"not-json\n")

    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode in {0, 1}
    assert len(result.stderr.encode("utf-8")) <= 512
    assert "Traceback" not in result.stderr
    assert journal.read_bytes() == b"not-json\n"


@pytest.mark.integration
@pytest.mark.parametrize("symlink_leaf", ("journal", "index"))
def test_journal_cli_rejects_final_symlink(
    tmp_path: Path,
    symlink_leaf: str,
) -> None:
    squad_dir = tmp_path / "run"
    squad_dir.mkdir()
    journal = squad_dir / "reasoning-journal.jsonl"
    index = squad_dir / "reasoning-journal-index.json"
    command = [
        sys.executable,
        "-m",
        "harness.journal_entry_validator",
        "append",
        "--journal-path",
        str(journal),
        "--phase",
        "phase3-plan",
    ]
    if symlink_leaf == "journal":
        target = squad_dir / "unrelated-target.jsonl"
        target.write_text(
            '{"id":1,"type":"seed","data":{"keep":true}}\n',
            encoding="utf-8",
        )
        journal.symlink_to(target)
    else:
        journal.write_text(
            '{"id":"RJ-001","type":"seed","data":{"keep":true}}\n',
            encoding="utf-8",
        )
        target = squad_dir / "unrelated-index.json"
        target.write_text(
            '{"last_entry_id":"RJ-001","keep":true}\n',
            encoding="utf-8",
        )
        index.symlink_to(target)
        command.extend(["--rj-index", str(index)])
    journal_before = (
        journal.read_bytes() if symlink_leaf == "index" else None
    )
    target_before = target.read_bytes()

    result = subprocess.run(
        command,
        input='{"type":"future_signal","data":{"new":true}}',
        text=True,
        capture_output=True,
        timeout=10,
        env=_environment(),
    )

    assert result.returncode == 1
    assert target.read_bytes() == target_before
    assert (
        journal_before is None or journal.read_bytes() == journal_before
    )
    assert (journal if symlink_leaf == "journal" else index).is_symlink()


@pytest.mark.integration
def test_copied_extension_writer_uses_installed_echelon_interpreter(
    tmp_path: Path,
) -> None:
    runtime_scripts = tmp_path / "runtime/extension/scripts/bash"
    runtime_scripts.mkdir(parents=True)
    for name in (
        "journal-append.sh",
        "validate-journal-entry.sh",
        "python-detect.sh",
    ):
        shutil.copy(
            ROOT / "extension/scripts/bash" / name,
            runtime_scripts / name,
        )
    runtime_workflow = tmp_path / "runtime/extension/workflow"
    runtime_workflow.mkdir(parents=True)
    shutil.copy(
        ROOT / "extension/workflow/journal-entry-types.json",
        runtime_workflow / "journal-entry-types.json",
    )
    installed_packages = tmp_path / "installed/site-packages"
    installed_packages.mkdir(parents=True)
    shutil.copytree(
        ROOT / "src/harness",
        installed_packages / "harness",
    )
    shutil.copytree(
        ROOT / "src/echelon",
        installed_packages / "echelon",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    installed_python = fake_bin / "installed-python"
    installed_python.write_text(
        "#!/bin/sh\n"
        f"PYTHONPATH={shlex.quote(str(installed_packages))} "
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    installed_python.chmod(0o755)
    installed_echelon = fake_bin / "echelon"
    installed_echelon.write_text(
        f"#!{installed_python}\n",
        encoding="utf-8",
    )
    installed_echelon.chmod(0o755)
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["HOME"] = str(empty_home)
    environment["PATH"] = (
        f"{fake_bin}{os.pathsep}/usr/bin{os.pathsep}/bin"
    )
    journal = tmp_path / "runtime-journal.jsonl"

    result = subprocess.run(
        [
            "bash",
            str(runtime_scripts / "journal-append.sh"),
            "--entry",
            (
                '{"type":"routing_decision","data":{'
                '"from_phase":"phase3-plan",'
                '"to_phase":"phase3-consensus",'
                '"reason":"runtime"}}'
            ),
            "--journal-path",
            str(journal),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )

    assert result.returncode == 0
    rows = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["type"] for row in rows] == [
        "routing_decision",
        "schema_warning",
    ]
    assert rows[1]["data"]["violating_entry_type"] == "routing_decision"


@pytest.mark.integration
def test_python_detector_uses_its_own_checkout_when_sourced(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    detector = checkout / "extension/scripts/bash/python-detect.sh"
    detector.parent.mkdir(parents=True)
    shutil.copy(
        ROOT / "extension/scripts/bash/python-detect.sh",
        detector,
    )
    fake_python = checkout / ".venv/bin/python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    caller = checkout / "scripts/bash/post-dispatch-hook.sh"
    caller.parent.mkdir(parents=True)
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    environment = dict(os.environ)
    environment.pop("PYTHON", None)
    environment["HOME"] = str(empty_home)
    environment["PATH"] = "/usr/bin:/bin"

    result = subprocess.run(
        [
            "bash",
            "-c",
            '. "$1"; printf "%s\\n" "$PYTHON"',
            str(caller),
            str(detector),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(fake_python)


@pytest.mark.integration
def test_hormone_hook_recovers_visible_dispatch_batch_without_reapplying(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "hormone-recovery"
    squad_dir, command, environment, cwd = _prepare_hormone_hook(
        workspace
    )
    append_indexed_reasoning_journal_entries(
        squad_dir,
        [
            {
                "type": "endocrine_event",
                "agent": "COMMANDER",
                "phase": "build-2-implement",
                "data": {
                    "trigger": "on_gate_pass",
                    "target": "SAGE",
                    "dispatch_id": "D-SHELL-LOCK",
                    "source_event": "on_gate_pass",
                },
            }
        ],
        phase_id="build-2-implement",
        batch_id="D-SHELL-LOCK",
    )
    state_path = squad_dir / "state.json"
    state_before = json.loads(state_path.read_text(encoding="utf-8"))
    hormones_before = state_before["endocrine_state"]["agents"]["SAGE"][
        "hormones"
    ]
    journal = squad_dir / "reasoning-journal.jsonl"
    journal_before = journal.read_bytes()

    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after["endocrine_state"]["agents"]["SAGE"][
        "hormones"
    ] == hormones_before
    assert "D-SHELL-LOCK" in state_after["endocrine_state"][
        "applied_dispatches"
    ]
    assert journal.read_bytes() == journal_before
