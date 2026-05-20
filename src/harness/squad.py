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
WHY_PHASES = frozenset({"phase1-why1", "phase1-why2"})

_HR = "=" * 44


def _blocked_banner(phase: str, reason: str, question: str) -> None:
    print(f"\n{_HR}", flush=True)
    print("  ✗  SQUAD RUN BLOCKED — human input required", flush=True)
    print(_HR, flush=True)
    print(f"\n  Phase:    {phase}", flush=True)
    print(f"  Reason:   {reason}", flush=True)
    print(f"\n  Question:", flush=True)
    for line in question.strip().splitlines():
        print(f"    {line}", flush=True)
    print(
        f"\n  Answer with:  echelon resume \"<your answer>\"\n"
        f"  Discard with: echelon run --reset \"<new task>\"",
        flush=True,
    )
    print(f"\n{_HR}\n", flush=True)


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
        max_iterations: int = 5,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._provider = provider
        self._state_store = state_store
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._token_budget = token_budget
        self._max_iterations = max_iterations
        self._squad_dir = squad_dir or state_store.squad_dir
        self._evaluator = ConditionEvaluator()
        self._executors: dict[str, PhaseExecutor] = {
            "agent": AgentExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "commander_internal": CommanderInternalExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "staged_parallel": StagedParallelExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "conditional_sequential": ConditionalSequentialExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "human_gate": HumanGateExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
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
                    f"    analysis:\n"
                    f"      token_budget_k: <increase this value>\n"
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

        # ── Escalation block ──────────────────────────────────────────────
        elif existing_status == "blocked" and existing.get("escalation_question"):
            q = existing.get("escalation_question", "")
            mode_at_block = existing.get("mode", mode)

            if mode_at_block == "banzai":
                print(
                    f"\n[squad] escalation detected — banzai mode, "
                    f"dispatching COMMANDER judgment\n"
                    f"  Questions: {q[:120]}",
                    flush=True,
                )
                # Clear the block so run() proceeds after judgment
                s = self._state_store.load()
                s["status"] = "running"
                s["blocked_reason"] = None
                self._state_store.save(s)
                existing_status = "running"
                self._judgment_dispatch_escalation(
                    escalation_question=q,
                    blocked_phase=existing.get("phase", "unknown"),
                )
                force_resume = True
            else:
                # semi / guided: stop and require echelon resume
                _blocked_banner(
                    phase=existing.get("phase", "?"),
                    reason=existing.get("blocked_reason", ""),
                    question=q,
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # (keep all recovery blocks exactly as-is above this point)

        # Fresh start if no state or not resumable
        # The correct squad dir was already selected by _cmd_run before creating this controller.
        if not existing or existing_status not in ("running", "in_progress"):
            run_id = f"squad-{int(time.time())}"
            self._state_store.initialize(
                run_id=run_id,
                mode=mode,
                user_message=user_message,
                token_budget=self._token_budget,
                entry_phase=self._graph.entry_phase(),
                max_iterations=self._max_iterations,
            )
        else:
            print(f"[squad] resuming from phase: {self._state_store.current_phase()}", flush=True)
            state = self._state_store.load()
            if state.get("cancel_requested"):
                state["cancel_requested"] = False
                self._state_store.save(state)

        while True:
            phase = self._state_store.current_phase()

            if phase in TERMINAL_PHASES:
                state = self._state_store.load()
                # Preserve "blocked" status set by guards (e.g. consecutive-fail).
                # Only write "done" when not already in a terminal-blocked state.
                if state.get("status") != "blocked":
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

            # Inline escalation check — fires when _evaluate_transitions detected
            # escalation_question in state_updates and returned the current phase.
            # Handles it in the same run() invocation rather than requiring a
            # re-invocation to reach the top-of-loop escalation block.
            state_now = self._state_store.load()
            if state_now.get("status") == "blocked" and state_now.get("escalation_question") and not state_now.get("escalation_resolved"):
                q = state_now["escalation_question"]
                run_mode = state_now.get("mode", mode)
                if run_mode == "banzai":
                    print(
                        f"[squad] ~ {node.id}  escalation — banzai COMMANDER judgment",
                        flush=True,
                    )
                    # Clear blocked status before dispatch (mirrors top-of-loop handler)
                    s = self._state_store.load()
                    s["status"] = "running"
                    s["blocked_reason"] = None
                    self._state_store.save(s)
                    self._judgment_dispatch_escalation(q, phase)
                    continue  # re-dispatch the same phase (e.g. phase1-why1) next iteration
                else:
                    _blocked_banner(
                        phase=phase,
                        reason=state_now.get("blocked_reason", ""),
                        question=q,
                    )
                    return SquadResult(
                        status="blocked",
                        phase=phase,
                        run_id=state_now.get("run_id", ""),
                    )
            else:
                print(f"[squad] ✓ {node.id}  → {next_phase}", flush=True)

    def _evaluate_transitions(
        self, node: PhaseNode, result: SquadAgentResult
    ) -> str:
        state = self._state_store.load()

        # ── WHY fail tracking + consecutive-fail safety net ──────────────────
        if node.id in WHY_PHASES:
            # Early escalation detection: agent explicitly signalled user-gated
            # CRITICAL issues via escalation_question in state_updates.  Handle
            # here before condition evaluation so empty quality_scores don't cause
            # COMMANDER to be dispatched as a routing judge instead.
            escalation_q = (result.state_updates or {}).get("escalation_question")
            if escalation_q:
                s = self._state_store.load()
                s["escalation_question"] = escalation_q
                s["blocked_reason"] = (result.state_updates or {}).get(
                    "blocked_reason", "WHY phase: agent escalation"
                )
                s["status"] = "blocked"
                self._state_store.save(s)
                return node.id  # stay at current phase; inline loop check handles escalation

            # Merge result.state_updates into a local copy so quality_gates.fail
            # can see the freshly-written quality_scores before advance() runs.
            eval_state = {**state, **result.state_updates}
            is_fail = self._evaluator.evaluate("quality_gates.fail", eval_state, result) is True
            if is_fail:
                fail_count = self._state_store.increment_why_fail_count()
                if fail_count >= 2 and not state.get("escalation_question"):
                    last_ts = (state.get("last_dispatch") or {}).get("completed_at")
                    if not self._staging_changed_since(last_ts):
                        print(
                            f"[squad] ✗ consecutive-fail guard: {fail_count} {node.id} FAILs "
                            f"with no staging progress — forcing escalation",
                            flush=True,
                        )
                        s = self._state_store.load()
                        s["escalation_question"] = (
                            f"Auto-detected: {fail_count} consecutive {node.id} FAILs "
                            f"with no staging progress. User input or banzai COMMANDER "
                            f"judgment required before continuing."
                        )
                        s["blocked_reason"] = "consecutive_why_fails"
                        s["status"] = "blocked"
                        self._state_store.save(s)
                        return "terminal-blocked"
            else:
                self._state_store.reset_why_fail_count()
        # ── end WHY tracking ─────────────────────────────────────────────────

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

    def _judgment_dispatch_escalation(
        self,
        escalation_question: str,
        blocked_phase: str,
    ) -> SquadAgentResult:
        """Dispatch COMMANDER to resolve a user-gated escalation in banzai mode.

        COMMANDER produces staging/user-clarifications.md with BANZAI-AUTO-RESOLVED
        answers and returns state_updates that clear the block.
        """
        commander_path = self._ext_dir / "agents/control/commander.md"
        state = self._state_store.load()

        staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
        staging_context = ""
        for f in sorted(staging_dir.glob("*.md"))[:8]:
            try:
                staging_context += f"\n---\n# {f.name}\n{f.read_text()[:3000]}\n"
            except Exception:
                pass

        context = (
            f"# COMMANDER BANZAI ESCALATION JUDGMENT\n\n"
            f"**Mode:** banzai — produce best-judgment answers and continue. "
            f"Do NOT stop the run.\n\n"
            f"**Phase blocked:** {blocked_phase}\n\n"
            f"**Blocking questions:**\n{escalation_question}\n\n"
            f"**Your task:**\n"
            f"1. For each blocking question, produce a best-judgment answer.\n"
            f"2. Write `{staging_dir}/user-clarifications.md` using the "
            f"BANZAI-AUTO-RESOLVED format from commander.md §Banzai Escalation.\n"
            f"3. Return echelon_result state_updates that clear the block:\n"
            f"   escalation_question: null\n"
            f"   escalation_resolved: true\n"
            f"   escalation_resolver: COMMANDER-banzai\n"
            f"   blocked_reason: null\n\n"
            f"**Staging context:**\n{staging_context}"
        )
        if commander_path.exists():
            context = commander_path.read_text() + "\n\n" + context
        else:
            print(
                f"[squad] warning: commander.md not found at {commander_path} — "
                f"dispatching COMMANDER without preamble",
                flush=True,
            )

        result = self._provider.exec_agent(str(self._project_root), context)
        self._write_journal_entries(result, blocked_phase)

        if result.state_updates:
            s = self._state_store.load()
            for k, v in result.state_updates.items():
                if v is None:
                    s.pop(k, None)   # null → remove key entirely
                else:
                    s[k] = v
            self._state_store.save(s)

        return result

    def _write_journal_entries(self, result: SquadAgentResult, phase_id: str) -> None:
        """Mirror of PhaseExecutor._write_journal_entries for SquadController use."""
        import json as _json
        from datetime import datetime, timezone

        entries = (result.echelon_result or {}).get("journal_entries", [])
        if not entries:
            return

        journal_path = self._squad_dir / "reasoning-journal.jsonl"
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

    def _staging_changed_since(self, iso_timestamp: Optional[str]) -> bool:
        """Return True if any staging .md file is newer than iso_timestamp.

        Returns True (progress detected) when timestamp is None or when
        any .md in staging_dir has mtime newer than the given UTC timestamp.
        """
        if iso_timestamp is None:
            return True
        try:
            from datetime import datetime, timezone
            cutoff = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            state = self._state_store.load()
            staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
            for f in staging_dir.glob("*.md"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime > cutoff:
                    return True
            return False
        except Exception:
            return True  # conservative: treat parse failure as progress

    def _budget_exhausted(self) -> bool:
        if self._token_budget <= 0:
            return False
        return self._state_store.token_usage() >= self._token_budget

    def _handle_sigint(self, signum, frame) -> None:
        print("\n[squad] Interrupted — finishing current phase then stopping.")
        self._cancelled = True
        self._state_store.set_cancel_requested()
