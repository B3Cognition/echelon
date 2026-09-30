"""Exercise the bundled npm observers through real npm script execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from harness.stacks import load_stack_definitions, resolve_stacks
from harness.stacks.preflight import (
    required_coverage_observers_for_types,
    verification_capability_findings,
)


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


def _resolved():
    return resolve_stacks(
        ["browser-threejs-npm"],
        load_stack_definitions(extension_root=ROOT / "runtime"),
        target_archetypes={"browser_3d_game"},
    )


def test_npm_threejs_bundle_satisfies_browser_and_mixed_contract_readiness():
    resolved = _resolved()
    assert resolved.required_commands == ["npm"]
    assert resolved.capabilities["web_app.rendering"].value == "threejs"
    assert verification_capability_findings(
        resolved,
        coverage_test_types={"unit", "integration", "contract", "e2e"},
        browser_required=True,
        semantic_visual_required=True,
        visual_execution_available=True,
    ) == []
    observers = required_coverage_observers_for_types(resolved, coverage_test_types={"contract"})
    assert {item.observer.adapter for item in observers} == {"vitest-json", "playwright-json"}
    assert all(item.observer.mode == "isolated" for item in observers)


@pytest.mark.parametrize("observer_id,script_args", [
    ("vitest-core", ["unit", "--project=core"]),
    ("playwright-e2e", ["browser", "--repeat-each=5", "--project=landscape"]),
])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_observer_preserves_npm_script_options_report_file_and_failure(
    tmp_path: Path, observer_id: str, script_args: list[str], exit_code: int,
):
    if not shutil.which("npm") or not shutil.which("node"):
        pytest.skip("real npm/Node command probe requires npm and Node")
    observer = next(item.observer for item in _resolved().coverage_observers
                    if item.observer.id == observer_id)
    project = tmp_path / "project with spaces"
    project.mkdir()
    # Replace only the external test runner: npm and the bundled shell command
    # remain real. Record the argv/environment received by the project script.
    (project / "runner.cjs").write_text(
        "const fs = require('node:fs');\n"
        "const args = process.argv.slice(2);\n"
        "const output = args.find(a => a.startsWith('--outputFile='));\n"
        "const report = output ? output.slice('--outputFile='.length) "
        ": process.env.PLAYWRIGHT_JSON_OUTPUT_FILE;\n"
        "console.log('project script output is not JSON');\n"
        "fs.writeFileSync(report, JSON.stringify({args}));\n"
        "process.exit(Number(process.env.PROBE_EXIT_CODE));\n",
        encoding="utf-8",
    )
    (project / "package.json").write_text(json.dumps({"scripts": {
        "test:unit": "node runner.cjs unit --project=core",
        "test:e2e": "node runner.cjs browser --repeat-each=5 --project=landscape",
    }}), encoding="utf-8")
    report = tmp_path / "external evidence" / "nested" / "report.json"
    result = subprocess.run(
        ["sh", "-c", observer.command], cwd=project,
        env={**os.environ, "ECHELON_COVERAGE_REPORT": str(report),
             "PROBE_EXIT_CODE": str(exit_code)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == exit_code, result.stderr
    expected = [*script_args, "--reporter=json"]
    if observer_id == "vitest-core":
        expected.append(f"--outputFile={report}")
    assert json.loads(report.read_text()) == {"args": expected}
    assert "project script output is not JSON" in result.stdout
