"""Phase executors for SquadController — one class per definition.yaml type."""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.phase_graph import PhaseGraph, PhaseNode
    from harness.squad_provider import SquadAgentResult, SquadCliProvider
    from harness.squad_state import SquadStateStore


class PhaseExecutor(ABC):
    def __init__(
        self,
        provider: "SquadCliProvider",
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
    ) -> None:
        self._provider = provider
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root

    @abstractmethod
    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        ...

    def _assemble_prompt(self, node: "PhaseNode", state: dict) -> str:
        parts: list[str] = []

        # 1. Agent file (role + instructions)
        if node.agent:
            rel = self._graph.agent_file(node.agent)
            if rel:
                agent_path = self._ext_dir / rel
                if agent_path.exists():
                    parts.append(agent_path.read_text())

        # 2. Phase spec file (context pack assembly instructions + echelon_result schema)
        if node.spec_file:
            spec_path = self._ext_dir / node.spec_file
            if spec_path.exists():
                parts.append(spec_path.read_text())

        # 3. Context pack files (read each that exists on disk)
        for item in node.context_pack:
            # Items may have inline comments: ".specify/echelon/re/state.json — current run state"
            file_ref = item.split(" ")[0].split("(")[0].rstrip()
            if not file_ref or file_ref.startswith("#"):
                continue
            candidate = self._project_root / file_ref
            if candidate.exists():
                parts.append(f"\n---\n# {file_ref}\n{candidate.read_text()}")

        # 4. Current state.json for context
        state_path = self._project_root / ".specify/squad/state.json"
        if state_path.exists():
            import json
            parts.append(f"\n---\n# Current state.json\n{state_path.read_text()}")

        return "\n\n".join(parts)

    def _run_pre_dispatch(
        self, node: "PhaseNode", state: dict, state_store: "SquadStateStore"
    ) -> None:
        """Execute conditional pre_dispatch entries before the main agent."""
        from harness.condition_evaluator import ConditionEvaluator
        ev = ConditionEvaluator()
        for entry in node.pre_dispatch:
            condition = entry.get("condition", "always")
            if ev.evaluate(condition, state) is not True:
                continue
            pre_agent = entry.get("agent", "").split(" ")[0]
            if not pre_agent:
                continue
            rel = self._graph.agent_file(pre_agent)
            if rel:
                pre_path = self._ext_dir / rel
                if pre_path.exists():
                    result = self._provider.exec_agent(
                        str(self._project_root), pre_path.read_text()
                    )
                    for k, v in result.state_updates.items():
                        s = state_store.load()
                        s[k] = v
                        state_store.save(s)


class AgentExecutor(PhaseExecutor):
    """Handles type: agent phases — the common case."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        state = state_store.load()
        self._run_pre_dispatch(node, state, state_store)
        state = state_store.load()  # re-load after pre_dispatch
        prompt = self._assemble_prompt(node, state)
        return self._provider.exec_agent(str(self._project_root), prompt)


class CommanderInternalExecutor(PhaseExecutor):
    """Handles type: commander_internal — run spec_file instructions via Bash."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult, _extract_echelon_result
        if node.spec_file:
            spec_path = self._ext_dir / node.spec_file
            if spec_path.exists():
                result = subprocess.run(
                    ["bash", "-c", spec_path.read_text()],
                    cwd=str(self._project_root),
                    capture_output=True,
                    text=True,
                )
                raw = result.stdout + result.stderr
                print(raw, flush=True)
                parsed = _extract_echelon_result(raw)
                return SquadAgentResult(
                    exit_code=result.returncode,
                    echelon_result=parsed or {"verdict": "DONE", "state_updates": {}},
                    raw_output=raw,
                    duration_ms=0,
                    timed_out=False,
                )
        from harness.squad_provider import SquadAgentResult
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class StagedParallelExecutor(PhaseExecutor):
    """Handles type: staged_parallel — phase3-consensus (WHY3+ASSESS2 then PLAN2).

    This is the phase that was previously skipped via EVOI fabrication.
    Python threading enforces both stage-1 agents run; there is no code path
    that bypasses Stage 1.
    """

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult

        stage1_agents = [a for a in node.agents if a.get("stage", 1) == 1]
        stage2_agents = [a for a in node.agents if a.get("stage", 1) == 2]

        stage1_results: dict[str, SquadAgentResult] = {}

        # Stage 1: run in parallel
        with ThreadPoolExecutor(max_workers=max(len(stage1_agents), 1)) as pool:
            futures: dict = {}
            for agent_entry in stage1_agents:
                agent_id = str(
                    agent_entry.get("id") or agent_entry.get("agent", "")
                ).split(" ")[0]
                mode_label = str(agent_entry.get("mode", agent_id))
                rel = self._graph.agent_file(agent_id)
                prompt = ""
                if rel:
                    path = self._ext_dir / rel
                    if path.exists():
                        prompt = path.read_text()
                if node.spec_file:
                    spec_path = self._ext_dir / node.spec_file
                    if spec_path.exists():
                        prompt += "\n\n" + spec_path.read_text()
                futures[pool.submit(
                    self._provider.exec_agent, str(self._project_root), prompt
                )] = mode_label

            for future in as_completed(futures):
                label = futures[future]
                stage1_results[label] = future.result()

        # Write stage-1 verdicts to state
        for label, result in stage1_results.items():
            state = state_store.load()
            state[f"{label.lower().replace(' ', '_')}_verdict"] = result.verdict
            for k, v in result.state_updates.items():
                state[k] = v
            state_store.save(state)

        # Stage 2: PLAN2 — requires implementability-report.md from ASSESS2
        impl_report_path: Optional[Path] = None
        for candidate in [
            self._project_root / "implementability-report.md",
            self._project_root / ".specify/squad/staging/implementability-report.md",
        ]:
            if candidate.exists():
                impl_report_path = candidate
                break

        for agent_entry in stage2_agents:
            agent_id = str(
                agent_entry.get("id") or agent_entry.get("agent", "")
            ).split(" ")[0]
            rel = self._graph.agent_file(agent_id)
            prompt = ""
            if rel:
                path = self._ext_dir / rel
                if path.exists():
                    prompt = path.read_text()
            if impl_report_path:
                prompt += f"\n\n---\n# implementability-report.md\n{impl_report_path.read_text()}"
            stage2_result = self._provider.exec_agent(str(self._project_root), prompt)
            state = state_store.load()
            for k, v in stage2_result.state_updates.items():
                state[k] = v
            state_store.save(state)

        all_pass = all(
            r.verdict in ("PASS", "DONE") for r in stage1_results.values()
        )
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS" if all_pass else "FAIL",
                "state_updates": {},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class ConditionalSequentialExecutor(PhaseExecutor):
    """Handles type: conditional_sequential — dispatches agents based on state conditions."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.condition_evaluator import ConditionEvaluator
        from harness.squad_provider import SquadAgentResult
        ev = ConditionEvaluator()
        state = state_store.load()

        for agent_entry in node.agents:
            condition = agent_entry.get("condition", "always")
            if ev.evaluate(condition, state) is not True:
                continue
            agent_id = str(
                agent_entry.get("id") or agent_entry.get("agent", "")
            ).split(" ")[0]
            rel = self._graph.agent_file(agent_id)
            if rel:
                path = self._ext_dir / rel
                if path.exists():
                    result = self._provider.exec_agent(
                        str(self._project_root), path.read_text()
                    )
                    state = state_store.load()
                    for k, v in result.state_updates.items():
                        state[k] = v
                    state_store.save(state)

        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class HumanGateExecutor(PhaseExecutor):
    """Handles type: human_gate — auto-proceed in semi/banzai; prompt in guided."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult
        state = state_store.load()
        autonomy = state.get("autonomy_mode", "semi")

        if autonomy in ("semi", "banzai"):
            print(f"[checkpoint] {node.label} — auto-proceeding ({autonomy} mode)")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "APPROVED",
                    "state_updates": {"gate_result": "auto_approved"},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        # guided: prompt user
        print(f"\n{'='*60}")
        print(f"CHECKPOINT: {node.label}")
        spec_dir = state.get("spec_dir", "specs/")
        print(f"Review artifacts in {spec_dir} then type 'approve' or 'reject':")
        print(f"{'='*60}")
        try:
            answer = input("> ").strip().lower()
        except EOFError:
            answer = "approve"

        approved = answer in ("approve", "yes", "y")
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "APPROVED" if approved else "REJECTED",
                "state_updates": {
                    "gate_result": "human_approved" if approved else "human_rejected"
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
