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

    def run(
        self,
        user_message: str = "",
        mode: str = "semi",
        next_phase_override: str = "",
    ) -> SquadResult:
        """Run the squad from current state or initialize fresh."""
        import os as _os
        _os.environ["ECHELON_SQUAD_ACTIVE"] = "1"

        existing = self._state_store.load()
        existing_status = existing.get("status") if existing else None
        existing_message = existing.get("user_message", "") if existing else ""
        blocked_reason = (existing.get("blocked_reason") or "") if existing else ""
        force_resume = False  # set True by recovery paths to bypass message check

        # ── Recovery: token budget bumped ─────────────────────────────────
        if existing_status == "blocked" and blocked_reason == "token_budget_exhausted":
            stored_usage = existing.get("token_usage", 0)
            if self._token_budget == 0 or self._token_budget > stored_usage:
                state = self._state_store.load()
                state["status"] = "running"
                state["blocked_reason"] = None
                state["token_budget"] = self._token_budget
                self._state_store.save(state)
                existing_status = "running"
                force_resume = True
                budget_display = f"{self._token_budget:,}" if self._token_budget else "∞"
                print(
                    f"[squad] budget bumped → resuming "
                    f"(usage={stored_usage:,}, new budget={budget_display})",
                    flush=True,
                )
            else:
                config_path = self._project_root / ".specify/extensions/echelon/echelon-config.yml"
                print(
                    f"\n[squad] ✗ Token budget still exhausted "
                    f"(usage={existing.get('token_usage', 0):,}, "
                    f"budget={self._token_budget:,}).\n"
                    f"  Edit {config_path}:\n"
                    f"    harness:\n"
                    f"      budget:\n"
                    f"        token_budget_k: <increase this value>\n"
                    f"  then re-run:  echelon run\n"
                    f"  Or discard:   echelon run --reset\n",
                    flush=True,
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # ── Recovery: invalid judgment phase (--next-phase manual override) ─
        elif existing_status == "blocked" and "invalid next_phase" in blocked_reason:
            valid_phases = self._graph.all_phase_ids()
            if next_phase_override:
                if next_phase_override not in valid_phases:
                    phases_fmt = "\n".join(f"    {p}" for p in valid_phases)
                    print(
                        f"\n[squad] ✗ --next-phase {next_phase_override!r} is not a "
                        f"valid phase ID.\n"
                        f"  Valid phase IDs:\n{phases_fmt}\n",
                        flush=True,
                    )
                    return SquadResult(
                        status="blocked",
                        phase=existing.get("phase", "unknown"),
                        run_id=existing.get("run_id", ""),
                    )
                state = self._state_store.load()
                state["status"] = "running"
                state["blocked_reason"] = None
                state["phase"] = next_phase_override
                self._state_store.save(state)
                existing_status = "running"
                force_resume = True
                print(
                    f"[squad] manual recovery → advancing to {next_phase_override!r}",
                    flush=True,
                )
            else:
                phases_fmt = "\n".join(f"    {p}" for p in valid_phases)
                print(
                    f"\n[squad] ✗ Blocked: {blocked_reason}\n"
                    f"  Recover:  echelon run --next-phase <phase-id>\n"
                    f"  Valid phase IDs:\n{phases_fmt}\n"
                    f"  Discard:  echelon run --reset\n",
                    flush=True,
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # ── Escalation block — human answer required ───────────────────────
        elif existing_status == "blocked" and existing.get("escalation_question"):
            q = existing.get("escalation_question", "")
            print(
                f"\n[squad] ✗ Run is blocked — human input required.\n"
                f"  Phase:    {existing.get('phase', '?')}\n"
                f"  Reason:   {blocked_reason}\n"
                f"  Question: {q}\n\n"
                f"  Answer with:  echelon resume \"<your answer>\"\n"
                f"  Discard with: echelon run --reset \"<new task>\"\n",
                flush=True,
            )
            return SquadResult(
                status="blocked",
                phase=existing.get("phase", "unknown"),
                run_id=existing.get("run_id", ""),
            )

        # A new run is started when:
        #   - no prior state exists, OR
        #   - the prior run reached a terminal state (done/blocked), OR
        #   - caller provides a different non-empty message (new task).
        # force_resume=True (set by recovery paths) bypasses the message check.
        new_message_provided = (
            bool(user_message and user_message != existing_message)
            and not force_resume
        )
        resumable = existing_status in ("running", "in_progress")

        if not existing or not resumable or new_message_provided:
            run_id = f"squad-{int(time.time())}"
            self._state_store.initialize(
                run_id=run_id,
                mode=mode,
                user_message=user_message,
                token_budget=self._token_budget,
                entry_phase=self._graph.entry_phase(),
            )
            if resumable and new_message_provided:
                print(
                    f"[squad] new task — starting fresh (previous run abandoned: "
                    f"{existing_message!r:.60})",
                    flush=True,
                )
        else:
            # Resuming an in-progress run — clear any cancel_requested flag left
            # by a previous SIGINT so this invocation doesn't exit immediately.
            print(f"[squad] resuming from phase: {self._state_store.current_phase()}", flush=True)
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
                # Accept either "next_phase" or "phase" as the routing key.
                next_phase = (
                    judgment.state_updates.get("next_phase")
                    or judgment.state_updates.get("phase")
                )
                # Hard-validate: next_phase must exist in the phase graph.
                # Reject hallucinated phase names rather than silently routing
                # to a non-existent phase or falling through to DONE.
                valid_phases = self._graph.all_phase_ids()
                if next_phase and next_phase not in valid_phases:
                    print(
                        f"[squad] ✗ judgment returned invalid phase {next_phase!r} "
                        f"— not in phase graph. Blocking.",
                        flush=True,
                    )
                    self._state_store.set_blocked(
                        f"judgment returned invalid next_phase {next_phase!r}"
                    )
                    return "terminal-blocked"
                # Apply judgment state_updates (e.g. iteration increment) now —
                # advance() only applies the executor result's state_updates.
                routing_keys = {"next_phase", "phase"}
                extra = {
                    k: v for k, v in judgment.state_updates.items()
                    if k not in routing_keys
                }
                if extra:
                    s = self._state_store.load()
                    s.update(extra)
                    self._state_store.save(s)
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
        valid_phases = self._graph.all_phase_ids()
        transitions_text = "\n".join(
            f"  - to: {t.get('to')}  (condition: {t.get('condition', 'always')})"
            for t in node.transitions
        ) or "  (none defined)"
        context = (
            f"# COMMANDER JUDGMENT REQUEST\n\n"
            f"**Reason:** {reason}\n\n"
            f"**Current phase:** {node.id} (type: {node.type})\n\n"
            f"**Transitions defined for this phase:**\n{transitions_text}\n\n"
            f"**VALID phase IDs** (only these may appear in next_phase):\n"
            f"{json.dumps(valid_phases, indent=2)}\n\n"
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
