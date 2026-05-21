"""Phase executors for SquadController — one class per definition.yaml type."""
from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.phase_graph import PhaseGraph, PhaseNode
    from harness.squad_provider import SquadAgentResult, SquadCliProvider
    from harness.squad_state import SquadStateStore


def _routing_contract(node: "PhaseNode") -> str:
    """Build a compact echelon_result contract from the phase's transition conditions.

    Scans condition expressions to derive which state_updates fields the harness
    reads for routing, then returns a hint block to append at the end of the prompt.
    Returns empty string when no agent-written fields are needed.
    """
    condition_text = " ".join(t.get("condition", "") for t in (node.transitions or []))
    if not condition_text.strip():
        return ""

    fields: list[tuple[str, str]] = []

    if "quality_gates" in condition_text or "CRITICAL_issues" in condition_text:
        fields.append((
            "quality_scores",
            "[{pass: true}]  # true=PASS, false=FAIL",
        ))

    # phase-specific verdict fields e.g. why3-verdict, assess2-verdict
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*-verdict)\b", condition_text):
        key = m.group(1).replace("-", "_")
        if not any(f[0] == key for f in fields):
            fields.append((key, "PASS | FAIL | REJECTED"))

    if re.search(r"\balignment\s*=", condition_text):
        fields.append(("alignment", "ALIGNED | DRIFT | STOP_AND_ASK"))

    if not fields:
        return ""

    lines = [
        "\n\n---",
        "## Harness routing contract — REQUIRED",
        "The harness reads these `echelon_result.state_updates` fields to route to the",
        "next phase. Missing or absent fields prevent correct routing.",
        "",
        "```yaml",
        "echelon_result:",
        "  verdict: <DONE|FAIL|BLOCKED|COMPLETE|...>  # always required",
        "  state_updates:",
    ]
    for field, hint in fields:
        lines.append(f"    {field}: {hint}")
    lines.append("```")
    return "\n".join(lines)


class PhaseExecutor(ABC):
    def __init__(
        self,
        provider: "SquadCliProvider",
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._provider = provider
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._squad_dir = squad_dir or (project_root / ".specify/squad")

    @abstractmethod
    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        ...

    def _write_journal_entries(
        self, result: "SquadAgentResult", phase_id: str
    ) -> None:
        """Append journal_entries[] from an agent result to the reasoning journal.

        Serialized write: every caller holds the GIL or calls this after
        thread-join, so appends are never concurrent.
        """
        import json
        from datetime import datetime, timezone

        entries = (result.echelon_result or {}).get("journal_entries", [])
        if not entries:
            return

        journal_path = self._squad_dir / "reasoning-journal.jsonl"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        # Derive next id from current line count (monotonic within a session)
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
                fh.write(json.dumps(entry) + "\n")
                next_id += 1

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
        state_path = self._squad_dir / "state.json"
        if state_path.exists():
            import json
            parts.append(f"\n---\n# Current state.json\n{state_path.read_text()}")

        prompt = "\n\n".join(parts)

        # Inject squad run context so agents know where to write
        squad_dir_str = state.get("squad_dir", str(self._squad_dir))
        staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
        context_preamble = (
            f"# Squad Run Context\n"
            f"SQUAD_DIR={squad_dir_str}\n"
            f"STAGING_DIR={staging_dir_str}\n"
            f"PROJECT_ROOT={self._project_root}\n\n"
        )

        # Translate legacy .specify/squad paths so phase spec files need no edits
        prompt = prompt.replace(".specify/squad/staging/", f"{staging_dir_str}/")
        prompt = prompt.replace(".specify/squad/staging", staging_dir_str)
        prompt = prompt.replace(".specify/squad/", f"{squad_dir_str}/")
        prompt = prompt.replace(".specify/squad", squad_dir_str)

        # Append harness routing contract so agents know exactly what
        # state_updates fields the harness needs for transition evaluation.
        prompt = prompt + _routing_contract(node)

        return context_preamble + prompt

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
                    self._write_journal_entries(result, node.id)
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
        result = self._provider.exec_agent(str(self._project_root), prompt)
        self._write_journal_entries(result, node.id)
        return result


class CommanderInternalExecutor(PhaseExecutor):
    """Handles type: commander_internal phases in the harness path.

    These spec files are markdown instructions for COMMANDER (the LLM) — not
    bash scripts. Running them as bash causes a stdin hang: markdown fenced
    code blocks contain triple-backticks which bash interprets as command
    substitutions that spawn child bash processes reading from the terminal.

    In the harness path these phases are no-ops: the harness already performed
    the equivalent init work (SquadStateStore.initialize, cli.py config checks),
    and any LLM-specific steps (KB reads, speckit.constitution) only run in the
    interactive COMMANDER path.
    """

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult
        print(f"[squad]   (commander_internal — harness no-op)", flush=True)
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

        # Write stage-1 verdicts and journal entries to state (serial — after join)
        for label, result in stage1_results.items():
            self._write_journal_entries(result, node.id)
            state = state_store.load()
            state[f"{label.lower().replace(' ', '_')}_verdict"] = result.verdict
            for k, v in result.state_updates.items():
                state[k] = v
            state_store.save(state)

        # Stage 2: PLAN2 — requires implementability-report.md from ASSESS2
        impl_report_path: Optional[Path] = None
        for candidate in [
            self._project_root / "implementability-report.md",
            self._squad_dir / "staging" / "implementability-report.md",
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
            self._write_journal_entries(stage2_result, node.id)
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
                    self._write_journal_entries(result, node.id)
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
