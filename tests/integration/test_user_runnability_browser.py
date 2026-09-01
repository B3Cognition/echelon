from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "runtime" / "scripts" / "user-runnability-browser.mjs"


def _node() -> str:
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node.js is unavailable")
    return executable


def _write_fake_playwright(root: Path) -> None:
    package = root / "node_modules" / "playwright"
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": "playwright", "type": "module", "exports": "./index.js"}),
        encoding="utf-8",
    )
    (package / "index.js").write_text(
        """\
const calls = [];
const locator = {
  count: async () => 1,
  isVisible: async () => true,
  textContent: async () => 'saved',
  click: async () => calls.push('click'),
  fill: async value => calls.push(`fill:${value}`),
  press: async key => calls.push(`press:${key}`),
};
const page = {
  goto: async url => calls.push(`goto:${url}`),
  locator: () => locator,
};
const context = {
  addInitScript: async (fn, values) => calls.push(`session:${Object.keys(values).join(',')}`),
  newPage: async () => page,
  close: async () => calls.push('context-close'),
};
export const chromium = {
  launch: async () => ({
    newContext: async options => { calls.push(`serviceWorkers:${options.serviceWorkers}`); return context; },
    close: async () => calls.push('browser-close'),
  }),
};
""",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_browser_helper_executes_typed_steps_and_dom_observation(tmp_path: Path) -> None:
    _write_fake_playwright(tmp_path)
    helper = tmp_path / HELPER.name
    helper.write_bytes(HELPER.read_bytes())
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "kind": "browser",
                "url": "http://127.0.0.1:4173",
                "session_storage": [["session-token", "token-value"]],
                "steps": [
                    {"action": "goto", "path": "/"},
                    {"action": "press", "key": "ArrowUp", "repeat": 2},
                    {"action": "expect", "selector": "canvas", "state": "visible"},
                ],
                "observations": [
                    {
                        "id": "checkpoint-visible",
                        "kind": "browser_dom",
                        "selector": "[data-checkpoint-state=saved]",
                        "expectation": "present",
                    }
                ],
                "observation_ids": ["checkpoint-visible"],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [_node(), str(helper), str(plan)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "status": "passed",
        "observations": {
            "checkpoint-visible": {"passed": True, "actual": "present"}
        },
    }


@pytest.mark.integration
def test_browser_helper_rejects_untyped_candidate_script_action(tmp_path: Path) -> None:
    _write_fake_playwright(tmp_path)
    helper = tmp_path / HELPER.name
    helper.write_bytes(HELPER.read_bytes())
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "kind": "browser",
                "url": "http://127.0.0.1:4173",
                "session_storage": [],
                "steps": [{"action": "evaluate", "value": "fetch('/mock')"}],
                "observations": [],
                "observation_ids": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [_node(), str(helper), str(plan)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "unsupported browser action" in result.stderr
