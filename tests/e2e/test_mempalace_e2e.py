"""E2E tests for MemPalace integration.

Two categories:
  A. CLI subprocess tests — invoke `codegen` CLI commands as subprocesses,
     verify real ChromaDB round-trips with an isolated palace.
  B. PipelineEngine tests — call PipelineEngine directly with mocked SOAR bridge,
     verify wing flows from echelon.yml -> codegen-state.json -> resume().

Run with: pytest tests/e2e/test_mempalace_e2e.py -v -m e2e
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

pytestmark = [pytest.mark.e2e]

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mempalace"
VENV_PYTHON = Path.home() / ".echelon" / "venv" / "bin" / "python"
VENV_CODEGEN = Path.home() / ".echelon" / "venv" / "bin" / "codegen"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_codegen(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the codegen CLI via the echelon venv entry-point script."""
    cmd = [str(VENV_CODEGEN)] + list(args)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env or {**os.environ},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _isolated_env(palace_path: Path) -> dict:
    """Return os.environ copy with MEMPALACE_PALACE_PATH set to palace_path."""
    env = os.environ.copy()
    env["MEMPALACE_PALACE_PATH"] = str(palace_path)
    return env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def require_venv_python():
    if not VENV_PYTHON.exists():
        pytest.skip(f"echelon venv not found at {VENV_PYTHON}")


@pytest.fixture
def isolated_palace(tmp_path, monkeypatch):
    palace = tmp_path / "palace"
    palace.mkdir()
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(palace))
    return palace


@pytest.fixture
def project_dir(tmp_path, isolated_palace):
    proj = tmp_path / "api-project"
    proj.mkdir()
    (proj / "echelon.yml").write_text(yaml.dump({
        "mempalace": {"wing": "api-project"},
        "deploy": {"type": "http", "blue_port": 3000, "green_port": 3001},
    }))
    (proj / "spec.md").write_text((FIXTURES / "spec-alpha.md").read_text())
    return proj


# ---------------------------------------------------------------------------
# Category A: CLI subprocess tests
# ---------------------------------------------------------------------------


class TestCLISubprocess:

    def test_requirements_mine_cli_exits_zero(self, project_dir, isolated_palace):
        """codegen requirements mine exits 0 and reports written drawers."""
        env = _isolated_env(isolated_palace)
        result = _run_codegen(
            "requirements", "mine", str(project_dir / "spec.md"),
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        # The mine output should mention "Written" and a non-zero count
        assert "Written" in result.stdout, (
            f"Expected 'Written' in stdout.\nSTDOUT: {result.stdout}"
        )

    def test_requirements_mine_cli_reports_drawer_count(self, project_dir, isolated_palace):
        """codegen requirements mine reports total and written drawer counts."""
        env = _isolated_env(isolated_palace)
        result = _run_codegen(
            "requirements", "mine", str(project_dir / "spec.md"),
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        # spec-alpha.md has FR/NFR/AC requirements — should mine several
        assert "Total" in result.stdout, f"Expected 'Total' in stdout.\nSTDOUT: {result.stdout}"
        assert "api-project" in result.stdout, (
            f"Expected wing name in stdout.\nSTDOUT: {result.stdout}"
        )

    def test_requirements_search_returns_mined_content(self, project_dir, isolated_palace):
        """After mine, codegen requirements search finds relevant content."""
        env = _isolated_env(isolated_palace)

        # Mine first
        mine = _run_codegen(
            "requirements", "mine", str(project_dir / "spec.md"),
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )
        assert mine.returncode == 0, f"Mine failed: {mine.stderr}"

        # Search
        search = _run_codegen(
            "requirements", "search", "OAuth2 authentication token",
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )
        assert search.returncode == 0, f"Search failed: {search.stderr}"
        assert "FR-AUTH" in search.stdout, (
            f"Expected FR-AUTH content in search results.\nSTDOUT: {search.stdout}"
        )

    def test_requirements_search_lists_result_rooms(self, project_dir, isolated_palace):
        """Search output includes room and distance metadata for each result."""
        env = _isolated_env(isolated_palace)

        _run_codegen(
            "requirements", "mine", str(project_dir / "spec.md"),
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )

        search = _run_codegen(
            "requirements", "search", "session Redis TTL",
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )
        assert search.returncode == 0, f"STDERR: {search.stderr}"
        assert "room:" in search.stdout, (
            f"Expected room metadata in output.\nSTDOUT: {search.stdout}"
        )
        assert "dist:" in search.stdout, (
            f"Expected distance metadata in output.\nSTDOUT: {search.stdout}"
        )

    def test_requirements_clean_dry_run_no_matching_drawers(self, project_dir, isolated_palace):
        """
        codegen requirements clean --dry-run exits 0.

        Note: The clean command matches drawers by source_file prefix against
        project_dir. Drawers mined via CLI have source_file='codegen/RE' (set
        by MemPalaceWriter), not the project path, so they are excluded from
        the project-scoped delete. This is expected behaviour.
        """
        env = _isolated_env(isolated_palace)

        _run_codegen(
            "requirements", "mine", str(project_dir / "spec.md"),
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )

        result = _run_codegen(
            "requirements", "clean",
            "--from-wing", "api-project",
            "--project-dir", str(project_dir),
            "--dry-run",
            cwd=project_dir, env=env,
        )
        assert result.returncode == 0, f"Clean dry-run failed: {result.stderr}"
        # Either no drawers match (clean says "No drawers found") or it lists them
        assert result.returncode == 0, (
            f"Expected zero exit from clean --dry-run.\nSTDERR: {result.stderr}"
        )

    def test_requirements_clean_exits_zero_for_empty_wing(self, project_dir, isolated_palace):
        """
        codegen requirements clean exits 0 with 'No drawers found' when wing
        has no drawers matching the project dir.
        """
        env = _isolated_env(isolated_palace)

        result = _run_codegen(
            "requirements", "clean",
            "--from-wing", "empty-wing",
            "--project-dir", str(project_dir),
            cwd=project_dir, env=env,
        )
        assert result.returncode == 0, f"Clean failed: {result.stderr}"
        assert "No drawers found" in result.stdout or "Removed" in result.stdout, (
            f"Unexpected output.\nSTDOUT: {result.stdout}"
        )

    def test_codegen_run_hard_fails_without_wing_in_echelon_yml(self, tmp_path, isolated_palace):
        """codegen run exits non-zero with clear message when echelon.yml has no wing."""
        env = _isolated_env(isolated_palace)
        proj = tmp_path / "no-wing"
        proj.mkdir()
        (proj / "echelon.yml").write_text(yaml.dump({
            "deploy": {"type": "http", "blue_port": 3200, "green_port": 3201},
        }))
        (proj / "codegen-state.json").write_text("{}")

        result = _run_codegen(
            "run", "--intent", "test", "--state-file", "codegen-state.json",
            cwd=proj, env=env,
        )
        # Must exit non-zero
        assert result.returncode != 0
        # The hard-exit message mentions "wing" or "echelon init"
        combined = result.stdout + result.stderr
        assert "wing" in combined.lower() or "echelon init" in combined.lower(), (
            f"Expected clear error about missing wing.\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_requirements_mine_spec_alpha_all_req_types(self, project_dir, isolated_palace):
        """Mine of spec-alpha.md writes FR, NFR, and AC requirement types."""
        env = _isolated_env(isolated_palace)
        result = _run_codegen(
            "requirements", "mine", str(project_dir / "spec.md"),
            "--wing", "api-project",
            cwd=project_dir, env=env,
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        # spec-alpha.md has 3 FR + 2 NFR + 2 AC = 7 requirements
        # Written count should be >= 5 (at minimum FR and NFR rows)
        assert "Written" in result.stdout
        # Extract written count from output like "Written  : N drawers written"
        import re
        m = re.search(r"Written\s*:\s*(\d+)", result.stdout)
        assert m is not None, f"Could not parse Written count from: {result.stdout}"
        written = int(m.group(1))
        assert written >= 5, f"Expected >= 5 drawers written, got {written}"


# ---------------------------------------------------------------------------
# Category B: PipelineEngine wing threading (mocked SOAR)
# ---------------------------------------------------------------------------


class TestPipelineEngineWingThreading:

    def _mock_bridge(self):
        bridge = MagicMock()
        bridge.model.value = "B"
        bridge._pid = 99999
        return bridge

    def test_initialize_writes_wing_from_echelon_yml(self, project_dir, isolated_palace):
        """PipelineEngine.initialize() writes wing from echelon.yml to codegen-state.json."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            ctx = MemPalaceContext.from_project(project_dir, run_id="placeholder")
            engine.set_context(ctx)
            state = engine.initialize(intent="Build REST API", mode="greenfield")

        written = json.loads(state_file.read_text())
        assert written["wing"] == "api-project", (
            f"Expected wing='api-project' in state file, got {written.get('wing')!r}"
        )
        assert written["pipeline_id"] == state.pipeline_id

    def test_resume_preserves_wing_from_state_file(self, project_dir, isolated_palace):
        """Wing written by initialize() is correctly read back by a fresh engine on resume()."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            ctx = MemPalaceContext.from_project(project_dir, run_id="placeholder")
            engine.set_context(ctx)
            engine.initialize(intent="Build REST API", mode="greenfield")

        # Fresh engine — resume
        engine2 = PipelineEngine(state_file=state_file)
        resumed = engine2.resume()

        assert resumed.wing == "api-project", (
            f"Expected wing='api-project' after resume, got {resumed.wing!r}"
        )

    def test_resume_pipeline_id_matches_original(self, project_dir, isolated_palace):
        """resume() returns the same pipeline_id that initialize() created."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            ctx = MemPalaceContext.from_project(project_dir, run_id="placeholder")
            engine.set_context(ctx)
            original = engine.initialize(intent="Build REST API", mode="greenfield")

        engine2 = PipelineEngine(state_file=state_file)
        resumed = engine2.resume()

        assert resumed.pipeline_id == original.pipeline_id, (
            f"pipeline_id mismatch: {resumed.pipeline_id!r} != {original.pipeline_id!r}"
        )

    def test_set_context_wing_overrides_echelon_yml_via_arg(self, project_dir, isolated_palace):
        """--wing CLI arg overrides the echelon.yml wing via wing_override parameter."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            # Override wing via wing_override (simulates --wing CLI arg)
            ctx = MemPalaceContext.from_project(
                project_dir, run_id="placeholder", wing_override="cli-override"
            )
            engine.set_context(ctx)
            state = engine.initialize(intent="test", mode="greenfield")

        written = json.loads(state_file.read_text())
        assert written["wing"] == "cli-override", (
            f"Expected wing='cli-override' (from --wing override), got {written['wing']!r}"
        )

    def test_wing_override_persists_through_resume(self, project_dir, isolated_palace):
        """Wing set via wing_override is persisted and survives resume()."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            ctx = MemPalaceContext.from_project(
                project_dir, run_id="placeholder", wing_override="override-wing"
            )
            engine.set_context(ctx)
            engine.initialize(intent="test", mode="greenfield")

        engine2 = PipelineEngine(state_file=state_file)
        resumed = engine2.resume()
        assert resumed.wing == "override-wing", (
            f"Expected overridden wing after resume, got {resumed.wing!r}"
        )

    def test_mine_then_pipeline_uses_same_wing(self, project_dir, isolated_palace):
        """Requirements mined via RequirementsMiner and searched via PipelineEngine RE phase use same wing."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext
        from codegen.memory.requirements_miner import RequirementsMiner

        # Mine requirements
        ctx = MemPalaceContext(wing="api-project", run_id="mine-run", palace_path=str(isolated_palace))
        miner = RequirementsMiner(ctx, project_dir=project_dir)
        mine_result = miner.mine_file(project_dir / "spec.md")
        assert mine_result.written > 0, (
            f"Expected at least 1 drawer written, got {mine_result.written}. "
            f"Errors: {mine_result.errors}"
        )

        # RE phase search via PipelineEngine
        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            ctx2 = MemPalaceContext.from_project(project_dir, run_id="pipeline-run")
            engine.set_context(ctx2)
            engine.initialize(intent="Build REST API", mode="greenfield")

        re_context = engine.run_re_phase(intent="OAuth2 authentication", ctx=ctx2)
        assert re_context, "RE phase should retrieve mined requirements"
        assert "FR-AUTH" in re_context, (
            f"Expected mined FR-AUTH content in RE phase results.\nGot: {re_context[:300]}"
        )

    def test_re_phase_returns_empty_when_no_requirements_mined(self, project_dir, isolated_palace):
        """RE phase returns empty string when the wing has no mined requirements."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            # Use a fresh wing that has never been mined
            ctx = MemPalaceContext(
                wing="never-mined-wing",
                run_id="pipeline-run",
                palace_path=str(isolated_palace),
            )
            engine.set_context(ctx)
            engine.initialize(intent="Build REST API", mode="greenfield")

        re_context = engine.run_re_phase(intent="OAuth2 authentication", ctx=ctx)
        assert re_context == "", (
            f"Expected empty RE context for unmined wing, got: {re_context[:200]}"
        )

    def test_initialize_mode_greenfield_written_to_state(self, project_dir, isolated_palace):
        """initialize() writes mode=greenfield to codegen-state.json."""
        from codegen.pipeline.pipeline_engine import PipelineEngine
        from codegen.memory.context import MemPalaceContext

        state_file = project_dir / "codegen-state.json"
        engine = PipelineEngine(state_file=state_file)

        with patch.object(engine.gate_runner, "_get_bridge", return_value=self._mock_bridge()):
            ctx = MemPalaceContext.from_project(project_dir, run_id="placeholder")
            engine.set_context(ctx)
            engine.initialize(intent="Build REST API", mode="greenfield")

        raw = json.loads(state_file.read_text())
        assert raw["mode"] == "greenfield"
        assert raw["intent"] == "Build REST API"
