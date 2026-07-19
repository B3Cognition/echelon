from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SPEC_COUNT = 100
ARTIFACTS_PER_SPEC = 20
TOTAL_MARKDOWN_BYTES = 50 * 1024 * 1024


def _write_fixture(root: Path) -> None:
    config = root / ".echelon/config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        yaml.safe_dump({"workspace": {"git_role": "primary"}}),
        encoding="utf-8",
    )
    artifact_size = TOTAL_MARKDOWN_BYTES // (SPEC_COUNT * ARTIFACTS_PER_SPEC)
    for spec_number in range(1, SPEC_COUNT + 1):
        spec_id = f"{spec_number:03d}-benchmark"
        spec_dir = root / "specs" / spec_id
        spec_dir.mkdir(parents=True)
        for artifact_number in range(ARTIFACTS_PER_SPEC):
            if artifact_number == 0:
                name = "spec.md"
                prefix = f"---\nstatus: phase_a\n---\n# {spec_id}\n\n- **FR-001** Requirement.\n"
            elif artifact_number == 1:
                name = "plan.md"
                prefix = "# Plan\n\n"
            elif artifact_number == 2:
                name = "tasks.md"
                prefix = "# Tasks\n\n- [ ] T-001 Implement.\n"
            else:
                name = f"artifact-{artifact_number:02d}.md"
                prefix = f"# Artifact {artifact_number}\n\n"
            padding = "navigation evidence\n" * (
                ((artifact_size - len(prefix.encode("utf-8"))) // 20) + 1
            )
            content = (prefix + padding).encode("utf-8")[:artifact_size]
            (spec_dir / name).write_bytes(content)


@pytest.mark.performance
def test_wiki_build_reference_workspace_within_budget(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    repository = Path(__file__).resolve().parents[2]
    script = """
import json
import resource
import sys
import time
from pathlib import Path
from echelon.wiki.service import build_wiki

started = time.perf_counter()
result = build_wiki(Path(sys.argv[1]))
elapsed = time.perf_counter() - started
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
peak_bytes = peak if sys.platform == "darwin" else peak * 1024
print(json.dumps({"elapsed": elapsed, "peak_rss_bytes": peak_bytes, "inputs": result.input_count}))
"""
    env = dict(os.environ)
    pythonpath = [str(repository / "src"), str(repository)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=repository,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    measurement = json.loads(completed.stdout)

    assert measurement["inputs"] == SPEC_COUNT * ARTIFACTS_PER_SPEC + 1
    assert measurement["elapsed"] <= 5.0, (
        f"wiki build took {measurement['elapsed']:.2f}s"
    )
    assert measurement["peak_rss_bytes"] < 512 * 1024 * 1024
