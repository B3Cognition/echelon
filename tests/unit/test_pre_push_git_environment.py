"""Git hook environment must not redirect test fixtures into the pushed repo."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("entry", ["full", "selected", "shell-test", "shell-test-python"])
def test_verification_cannot_commit_into_calling_repository(tmp_path, entry):
    source = Path(__file__).resolve().parents[2]
    outer = tmp_path / "outer"
    outer.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=outer, env=env, text=True).strip()
    git("init", "-q", "-b", "main")
    git("config", "user.name", "outer owner")
    git("config", "user.email", "outer@example.test")
    git("config", "core.hooksPath", str(tmp_path / "no-hooks"))
    for directory in (".githooks", "tests/unit", "scripts"):
        (outer / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / ".githooks/pre-push", outer / ".githooks/pre-push")
    shutil.copy2(source / "tests/unit/test-pre-push-hook.sh", outer / "tests/unit/test-pre-push-hook.sh")
    # Replace only the expensive test payload. Its real Git writes deliberately
    # inherit the hook environment, reproducing the fixture escape if not cleared.
    helper = outer / "scripts/fixture-python"
    helper.write_text(f"#!{sys.executable}\n" + """
import os, pathlib, subprocess
target = pathlib.Path(os.environ['NESTED_REPO'])
target.mkdir()
for args in [('init', '-q'), ('config', 'user.name', 'fixture'),
        ('config', 'user.email', 'fixture@example.test'),
        ('-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty', '-qm', 'fixture')]:
    subprocess.run(['git', *args], cwd=target, check=True)
""")
    helper.chmod(0o755)
    (outer / "scripts/merge_verification.py").write_text("# Selected verification fixture\n")
    (outer / "tests/run-all.sh").write_text(f'#!/bin/sh\nexec "{helper}"\n')
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "candidate")
    head = git("rev-parse", "HEAD")
    before = {name: (outer / ".git" / name).read_bytes() for name in ("config", "index")}
    inherited = {**env, "GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(outer),
        "GIT_COMMON_DIR": str(outer / ".git"), "GIT_INDEX_FILE": str(outer / ".git/index"),
        "NESTED_REPO": str(tmp_path / "nested"), "PYTHON": str(helper)}
    if entry.startswith("shell-test"):
        inherited.pop("PYTHON", None)
        if entry == "shell-test-python":
            inherited["PYTHON"] = sys.executable
        command = ["bash", str(outer / "tests/unit/test-pre-push-hook.sh")]
        refs = ""
    else:
        command = ["bash", str(outer / ".githooks/pre-push"), "origin", "unused"]
        refs = f"refs/heads/main {head} refs/heads/main {base}\n" if entry == "selected" else ""
    completed = subprocess.run(command, cwd=outer, env=inherited, input=refs,
        capture_output=True, text=True, timeout=60)
    # Check the real protected repository, not merely the child's environment.
    assert git("rev-parse", "HEAD") == head, completed.stdout + completed.stderr
    assert (outer / ".git/config").read_bytes() == before["config"]
    assert (outer / ".git/index").read_bytes() == before["index"]
    assert completed.returncode == 0, completed.stdout + completed.stderr
    if not entry.startswith("shell-test"):
        assert subprocess.check_output(["git", "log", "-1", "--format=%s"],
            cwd=tmp_path / "nested", env=env, text=True).strip() == "fixture"
