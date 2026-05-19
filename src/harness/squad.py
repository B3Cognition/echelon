"""SquadController — deterministic phase routing for the pre-code squad run."""
from __future__ import annotations

import json
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.condition_evaluator import ConditionEvaluator
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.squad_executors import (
    AgentExecutor,
    CommanderInternalExecutor,
    ConditionalSequentialExecutor,
    HumanGateExecutor,
    PhaseExecutor,
    StagedParallelExecutor,
)
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_state import SquadStateStore


TERMINAL_PHASES = {"DONE", "done", "terminal-blocked"}


@dataclass
class SquadResult:
    status: str         # "done" | "blocked" | "interrupted" | "budget_exhausted"
    phase: str
    run_id: str
    summary: str = ""

    @classmethod
    def from_state(cls, state: dict) -> "SquadResult":
        return cls(
            status=state.get("status", "unknown"),
            phase=state.get("phase", "unknown"),
            run_id=state.get("run_id", ""),
        )

    @classmethod
    def interrupted(cls) -> "SquadResult":
        return cls(status="interrupted", phase="unknown", run_id="")


class SquadController:
    """Drives the squad run phase graph deterministically.

    Phase routing is pure Python (ConditionEvaluator + state.json).
    COMMANDER (LLM) is dispatched only for judgment calls.
    """

    def __init__(
        self,
        provider: SquadCliProvider,
        state_store: SquadStateStore,
        phase_graph: PhaseGraph,
        ext_dir: Path,
        project_root: Path,
        token_budget: int = 0,
    ) -> None:
        self._provider = provider
        self._state_store = state_store
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._token_budget = token_budget
        self._evaluator = ConditionEvaluator()
        self._executors: dict[str, PhaseExecutor] = {
            "agent": AgentExecutor(provider, phase_graph, ext_dir, project_root),
            "commander_internal": CommanderInternalExecutor(provider, phase_graph, ext_dir, project_root),
            "staged_parallel": StagedParallelExecutor(provider, phase_graph, ext_dir, project_root),
            "conditional_sequential": ConditionalSequentialExecutor(provider, phase_graph, ext_dir, project_root),
            "human_gate": HumanGateExecutor(provider, phase_graph, ext_dir, project_root),
        }
        self._cancelled = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def run(self, user_message: str = "", mode: str = "semi") -> SquadResult:
        """Run the squad from current state or initialize fresh."""
        import os as _os
        _os.environ["ECHELON_SQUAD_ACTIVE"] = "1"

        existing = self._state_store.load()
        if not existing or existing.get("status") not in ("running", "in_progress"):
            run_id = f"squad-{int(time.time())}"
            self._state_store.initialize(
                run_id=run_id,
                mode=mode,
                user_message=user_message,
                token_budget=self._token_budget,
                entry_phase=self._graph.entry_phase(),
            )
        else:
            # Resuming an in-progress run — clear any cancel_requested flag left
            # by a previous SIGINT so this invocation doesn't exit immediately.
            state = self._state_store.load()
            if state.get("cancel_requested"):
                state["cancel_requested"] = False
                self._state_store.save(state)

        while True:
            phase = self._state_store.current_phase()

            if phase in TERMINAL_PHASES:
                state = self._state_store.load()
                state["status"] = "done"
                self._state_store.save(state)
                return SquadResult.from_state(self._state_store.load())

            if self._cancelled:
                return SquadResult.interrupted()

            if self._budget_exhausted():
                self._state_store.set_blocked("token_budget_exhausted")
                return SquadResult(
                    status="budget_exhausted",
                    phase=phase,
                    run_id=self._state_store.load().get("run_id", ""),
                )

            node = self._graph.get(phase)
            label = node.label or node.id
            print(f"\n[squad] ▶ {node.id}  {label}", flush=True)

            executor = self._executors.get(node.type)
            if executor is None:
                result = self._judgment_dispatch(
                    f"Unknown phase type {node.type!r} for phase {phase!r}",
                    node,
                )
            else:
                result = executor.execute(node, self._state_store)

            next_phase = self._evaluate_transitions(node, result)
            self._state_store.advance(phase, next_phase, result)
            print(f"[squad] ✓ {node.id}  → {next_phase}", flush=True)

    def _evaluate_transitions(
        self, node: PhaseNode, result: SquadAgentResult
    ) -> str:
        state = self._state_store.load()
        for transition in node.transitions:
            condition = transition.get("condition", "always")
            evaluation = self._evaluator.evaluate(condition, state, result)
            if evaluation is True:
                return transition["to"]
            if evaluation is None:
                judgment = self._judgment_dispatch(
                    f"Cannot evaluate condition {condition!r} in phase {node.id!r}",
                    node,
                    result,
                )
                next_phase = judgment.state_updates.get("next_phase")
                if next_phase:
                    return next_phase
        return "DONE"

    def _judgment_dispatch(
        self,
        reason: str,
        node: PhaseNode,
        result: Optional[SquadAgentResult] = None,
    ) -> SquadAgentResult:
        """Dispatch slimmed COMMANDER for judgment calls."""
        commander_path = self._ext_dir / "agents/control/commander.md"
        state = self._state_store.load()
        context = (
            f"# COMMANDER JUDGMENT REQUEST\n\n"
            f"**Reason:** {reason}\n\n"
            f"**Current phase:** {node.id} (type: {node.type})\n\n"
            f"**State:**\n```json\n{json.dumps(state, indent=2)}\n```\n\n"
        )
        if commander_path.exists():
            context = commander_path.read_text() + "\n\n" + context
        judgment = self._provider.exec_agent(str(self._project_root), context)
        # COMMANDER writes most journal entries directly via journal-append.sh
        # during LLM execution.  This catches any entries it returns in
        # echelon_result.journal_entries[] that it didn't write itself.
        self._write_journal_entries(judgment, node.id)
        return judgment

    def _write_journal_entries(self, result: SquadAgentResult, phase_id: str) -> None:
        """Mirror of PhaseExecutor._write_journal_entries for SquadController use."""
        import json as _json
        from datetime import datetime, timezone

        entries = (result.echelon_result or {}).get("journal_entries", [])
        if not entries:
            return

        journal_path = self._project_root / ".specify/squad/reasoning-journal.jsonl"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        next_id = 1
        if journal_path.exists():
            lines = [ln for ln in journal_path.read_text().splitlines() if ln.strip()]
            next_id = len(lines) + 1

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with journal_path.open("a") as fh:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry.setdefault("id", next_id)
                entry.setdefault("timestamp", ts)
                entry.setdefault("phase", phase_id)
                fh.write(_json.dumps(entry) + "\n")
                next_id += 1

    def _budget_exhausted(self) -> bool:
        if self._token_budget <= 0:
            return False
        return self._state_store.token_usage() >= self._token_budget

    def _handle_sigint(self, signum, frame) -> None:
        print("\n[squad] Interrupted — finishing current phase then stopping.")
        self._cancelled = True
        self._state_store.set_cancel_requested()
