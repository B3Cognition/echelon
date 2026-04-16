"""
soar_bridge.py — Python SML Bridge for SOAR 9.6.4
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

ADR-008-002: Two process models.
  Model A (primary): Persistent SOAR daemon process.
    - SOAR launched once per /codegen invocation.
    - WMEs injected via subprocess stdin/stdout pipe.
    - EPMEM accumulated across the full pipeline.
    - Sub-millisecond IPC after initial SMEM load.
  Model B (fallback): Per-phase SOAR invocation.
    - SOAR launched fresh per phase transition.
    - WM state serialized to /tmp/codegen-wm-state.json between phases.
    - 2-5 second startup overhead per transition (20-50s per pipeline).
    - Activated if Model A process fails or is unavailable.

INV-001: chunk never is first directive in all .soar files.
INV-004: EPMEM records every phase transition.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOAR_BINARY_NAMES = ["soar", "soar96", "soar-cli", "JSoar"]
DEFAULT_WM_STATE_FILE = Path("/tmp/codegen-wm-state.json")


def _secure_write_wm_state(path: Path, content: str) -> None:
    """
    Write WM state content to *path* with owner-only permissions (SEC-025 FIX-2).

    Security guarantees:
    - Rejects a pre-existing symlink at *path* to prevent symlink attacks (FR-005).
    - Creates the file with permissions 0600 atomically via os.open O_CREAT|O_EXCL
      so no window exists between creation and chmod (FR-003).
    - Falls back to write+chmod when the file already exists (e.g. second write in
      the same pipeline run), still enforcing 0600 before write.

    Raises:
        RuntimeError: If *path* is a symlink (symlink attack detected).
        OSError: If the file cannot be created or written.
    """
    # FR-005: reject pre-existing symlink — never follow it
    if os.path.islink(path):
        raise RuntimeError(
            f"[SOAR Bridge] WM state path is a symlink — refusing to write: {path}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")

    if path.exists():
        # File exists (second write in same run): enforce 0600 then overwrite.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        path.write_bytes(encoded)
    else:
        # New file: create atomically with 0600 via O_EXCL (no chmod-after-create window).
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)


def _register_wm_state_cleanup(path: Path) -> None:
    """Register an atexit handler to delete the WM state temp file (FR-004)."""
    def _cleanup():
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    atexit.register(_cleanup)
DEFAULT_SOAR_CONFIG = Path(__file__).parent.parent / "soar" / "codegen.soar"
DEFAULT_SMEM_FILE = Path(__file__).parent.parent / "library" / "cq-isc-default-v1.0.0.yaml"

# Per ADR-008-002: Model B startup overhead budget
MODEL_B_STARTUP_BUDGET_SECONDS = 5
MODEL_A_IPC_TIMEOUT_SECONDS = 10

# When CODEGEN_REQUIRE_MODEL_A=1, silent downgrades to Model B are forbidden.
# Any situation that would fall back raises RuntimeError instead, so the caller
# sees the failure loudly rather than drifting onto the slower per-phase path.
REQUIRE_MODEL_A = os.environ.get("CODEGEN_REQUIRE_MODEL_A") == "1"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class SOARBridgeModel(Enum):
    A = "A"  # Persistent daemon
    B = "B"  # Per-phase invocation


@dataclass
class WMEInjectionResult:
    success: bool
    wme_id: str
    attribute: str
    value: Any
    timestamp_ms: int
    model: SOARBridgeModel
    error: Optional[str] = None


@dataclass
class OperatorSelection:
    operator_name: str
    confidence: float
    source: str  # "soar" | "model-b-default"
    cq_isc_ids_evaluated: list[str] = field(default_factory=list)
    prohibit_fired: list[str] = field(default_factory=list)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class AuditRecord:
    """INV-004: Every SOAR decision cycle must produce an EPMEM entry."""
    record_id: str
    record_type: str  # phase-transition | retry-task | escalation | delivery | smem-load
    task_id: Optional[str]
    selected_operator: str
    cq_isc_ids_evaluated: list[str]
    cq_isc_prohibit_fired: list[str]
    operator_outcome: str  # ADVANCE | RETRY | ESCALATE | DELIVER
    psi_at_decision: float
    violations_blocked: int
    timestamp_ms: int
    confidence_envelope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "task_id": self.task_id,
            "selected_operator": self.selected_operator,
            "cq_isc_ids_evaluated": self.cq_isc_ids_evaluated,
            "cq_isc_prohibit_fired": self.cq_isc_prohibit_fired,
            "operator_outcome": self.operator_outcome,
            "psi_at_decision": self.psi_at_decision,
            "violations_blocked": self.violations_blocked,
            "timestamp_ms": self.timestamp_ms,
            "confidence_envelope": self.confidence_envelope,
        }


# ---------------------------------------------------------------------------
# SOARBridge
# ---------------------------------------------------------------------------

class SOARBridge:
    """
    Python SML bridge for SOAR 9.6.4.

    Manages SOAR process lifecycle, WME injection, operator querying,
    and EPMEM export. Supports Model A (persistent) and Model B (per-phase).

    Usage (Model A):
        bridge = SOARBridge(smem_file=Path("cq-isc-default-v1.0.0.yaml"))
        bridge.start()
        result = bridge.inject_wme("function-length", 45)
        op = bridge.get_selected_operator()
        audit = bridge.export_audit_record()
        bridge.shutdown()

    Usage (Model B):
        bridge = SOARBridge(model=SOARBridgeModel.B,
                            wm_state_file=Path("/tmp/codegen-wm-state.json"))
        bridge.phase_invoke(wme={"attr": "function-length", "value": 45})
        op = bridge.get_operator_from_state_file()
    """

    def __init__(
        self,
        soar_config: Path = DEFAULT_SOAR_CONFIG,
        smem_file: Path = DEFAULT_SMEM_FILE,
        wm_state_file: Path = DEFAULT_WM_STATE_FILE,
        model: SOARBridgeModel = SOARBridgeModel.A,
        verbose: bool = False,
        memory_config=None,  # Optional[MemoryConfig] — avoids circular import
    ):
        self.soar_config = soar_config
        self.smem_file = smem_file
        self.wm_state_file = wm_state_file
        self.model = model
        self.verbose = verbose
        self.memory_config = memory_config  # ADR-001: MemoryConfig injected at construction

        self._process: Optional[subprocess.Popen] = None
        self._pid: Optional[int] = None
        self._alive: bool = False
        self._audit_records: list[AuditRecord] = []
        self._wme_log: list[WMEInjectionResult] = []
        self._pipeline_id: str = str(uuid.uuid4())
        self._soar_binary: Optional[str] = None
        self._build_id: Optional[str] = None  # Identifier for ^build sub-object (e.g. "B1")
        self._init_wme_timetags: dict[str, int] = {}  # attribute → timetag from init
        self._injected_timetags: dict[str, int] = {}  # attribute → timetag from inject_wme

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the SOAR process (Model A).
        Returns True if started successfully, False if SOAR binary not found.
        On failure, automatically downgrades to Model B.
        """
        soar_bin = self._find_soar_binary()
        if soar_bin is None:
            if REQUIRE_MODEL_A:
                raise RuntimeError(
                    "CODEGEN_REQUIRE_MODEL_A=1 but no SOAR binary found. "
                    "Install SOAR 9.6.4 and put `soar` on PATH (or at "
                    "/usr/local/bin/soar, /opt/soar/bin/soar, ~/soar/bin/soar, ~/.soar/soar)."
                )
            print(
                "[SOAR Bridge] WARNING: No SOAR binary found. "
                "Falling back to Model B (per-phase invocation).",
                file=sys.stderr,
            )
            self.model = SOARBridgeModel.B
            self._alive = False
            return False

        self._soar_binary = soar_bin

        try:
            self._process = subprocess.Popen(
                [soar_bin, "-n"],  # -n: non-interactive, read commands from stdin
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,   # bytes mode — use os.read() for non-blocking reads
                bufsize=0,    # unbuffered
            )
            self._pid = self._process.pid
            self._alive = True

            # Drain startup banner (SOAR prints several lines before accepting commands)
            self._drain_stdout(timeout=2.0)
            # Load SOAR configuration (chunk never is first directive)
            # Braces are valid Tcl quoting — safe for paths with spaces
            config_path = str(self.soar_config.resolve())
            self._send_command(f"source {{{config_path}}}")
            # Wait for source command and production loading to complete
            time.sleep(1.5)
            self._drain_stdout(timeout=1.5)

            # Configure persistent memory stores BEFORE first decision cycle (ADR-001, ADR-002)
            self._startup_configure()

            # Run TWO decision cycles so the init production fully applies:
            #   Cycle 1: codegen*top*propose*init fires → operator init-codegen selected
            #   Cycle 2: codegen*top*apply*init fires → creates (<s> ^build <b>) and populates <b>
            self._send_command("run 2 -d")
            time.sleep(1.0)
            self._drain_stdout(timeout=2.0)

            # Query S1 to find the ^build sub-object identifier (e.g. "B1")
            self._send_command("print S1")
            time.sleep(0.3)
            print_out = self._drain_stdout(timeout=2.0)
            self._build_id = self._parse_build_id(print_out)

            if self._build_id:
                # Record the timetags of the initial WMEs on <b> so we can
                # remove them when inject_wme overrides an existing attribute.
                self._send_command(f"print -i {self._build_id}")
                time.sleep(0.3)
                internal_out = self._drain_stdout(timeout=2.0)
                self._init_wme_timetags = self._parse_wme_timetags(internal_out)
                print(
                    f"[SOAR Bridge] Build sub-object: {self._build_id} "
                    f"({len(self._init_wme_timetags)} initial WMEs)",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                self._init_wme_timetags = {}
                print(
                    "[SOAR Bridge] WARNING: Could not resolve build sub-object — "
                    "falling back to S1 for WME injection.",
                    file=sys.stderr,
                    flush=True,
                )

            self._verify_alive()
            print(f"[SOAR Bridge] Model A started — PID {self._pid}", file=sys.stderr, flush=True)
            return True

        except (OSError, subprocess.SubprocessError) as exc:
            if REQUIRE_MODEL_A:
                raise RuntimeError(
                    f"CODEGEN_REQUIRE_MODEL_A=1 but SOAR process failed to start: {exc}"
                ) from exc
            print(
                f"[SOAR Bridge] WARNING: Failed to start SOAR process: {exc}. "
                "Falling back to Model B.",
                file=sys.stderr,
            )
            self.model = SOARBridgeModel.B
            self._alive = False
            return False

    def inject_wme(self, attribute: str, value: Any, task_id: Optional[str] = None) -> WMEInjectionResult:
        """
        Inject a WME into SOAR Working Memory.

        Model A: sends WME via subprocess stdin pipe.
        Model B: appends to WM state file at wm_state_file.

        Returns WMEInjectionResult with success status.
        """
        wme_id = str(uuid.uuid4())[:8]
        ts = int(time.time() * 1000)

        if self.model == SOARBridgeModel.A and self._alive:
            try:
                # SOAR 9.6.4 WME syntax: wm add <id> ^attribute |value| or numeric
                # Productions check (<b> ^attr ...) where <b> is the ^build sub-object.
                # Use _build_id if resolved, fall back to S1 (for top-level attrs).
                target_id = self._build_id if self._build_id else "S1"

                # Remove any existing WME for this attribute (init default or prior inject)
                # to avoid duplicate values confusing the production rules.
                for timetag_map in (self._init_wme_timetags, self._injected_timetags):
                    if attribute in timetag_map:
                        self._send_command(f"wm remove {timetag_map[attribute]}")
                        time.sleep(0.05)
                        self._drain_stdout(timeout=0.3)
                        del timetag_map[attribute]
                        break

                if isinstance(value, dict):
                    # SOAR identifiers cannot be created via wm add — only productions can.
                    # For structured WMEs (violations), inject a flat violation-marker on S1.
                    # The codegen*bridge*create-violation-object production then creates the
                    # proper (<s> ^code-violation <v>) (<v> ^status |confirmed-failing|) structure.
                    import re as _re
                    cq_id = value.get("cq-isc-id", wme_id)
                    marker_key = f"violation-marker:{cq_id}"
                    self._send_command(f"wm add S1 ^violation-marker |{cq_id}|")
                    time.sleep(0.05)
                    marker_out = self._drain_stdout(timeout=0.5)
                    tt_m = _re.search(r"Timetag:\s*(\d+)", marker_out)
                    if tt_m:
                        self._injected_timetags[marker_key] = int(tt_m.group(1))
                    result = WMEInjectionResult(
                        success=True,
                        wme_id=wme_id,
                        attribute=attribute,
                        value=value,
                        timestamp_ms=ts,
                        model=self.model,
                    )
                    self._wme_log.append(result)
                    return result
                elif isinstance(value, (int, float)):
                    val_str = str(value)
                else:
                    val_str = f"|{value}|"
                cmd = f"wm add {target_id} ^{attribute} {val_str}"
                self._send_command(cmd)
                # Capture timetag from output so we can remove this WME later if needed
                time.sleep(0.05)
                add_out = self._drain_stdout(timeout=0.5)
                import re as _re
                tt_m = _re.search(r"Timetag:\s*(\d+)", add_out)
                if tt_m:
                    self._injected_timetags[attribute] = int(tt_m.group(1))
                result = WMEInjectionResult(
                    success=True,
                    wme_id=wme_id,
                    attribute=attribute,
                    value=value,
                    timestamp_ms=ts,
                    model=self.model,
                )
            except Exception as exc:
                result = WMEInjectionResult(
                    success=False,
                    wme_id=wme_id,
                    attribute=attribute,
                    value=value,
                    timestamp_ms=ts,
                    model=self.model,
                    error=str(exc),
                )
        else:
            # Model B: serialize to WM state file
            result = self._inject_wme_model_b(attribute, value, wme_id, ts, task_id)

        self._wme_log.append(result)
        return result

    def get_selected_operator(self) -> OperatorSelection:
        """
        Query SOAR for the currently selected operator.

        Model A: runs one decision cycle via 'run 1 -d', reads stdout.
        Model B: reads operator from wm_state_file.
        """
        if self.model == SOARBridgeModel.A and self._alive:
            return self._get_operator_model_a()
        else:
            return self._get_operator_model_b()

    def export_audit_record(self) -> dict:
        """
        Export all EPMEM audit records as a serializable dict (INV-004).
        Called at pipeline completion or interruption.
        """
        return {
            "schema_version": "1.0.0",
            "pipeline_id": self._pipeline_id,
            "export_ts": int(time.time() * 1000),
            "soar_model": self.model.value,
            "soar_pid": self._pid,
            "total_records": len(self._audit_records),
            "records": [r.to_dict() for r in self._audit_records],
            "wme_log": [
                {
                    "wme_id": w.wme_id,
                    "attribute": w.attribute,
                    "value": str(w.value),
                    "success": w.success,
                    "ts": w.timestamp_ms,
                }
                for w in self._wme_log
            ],
        }

    def record_phase_transition(
        self,
        from_phase: str,
        to_phase: str,
        psi_score: float,
        violations_blocked: int,
        cq_isc_evaluated: list[str],
        cq_isc_fired: list[str],
        task_id: Optional[str] = None,
    ) -> AuditRecord:
        """
        Manually record a phase transition in the audit log (INV-004).
        Used by the bridge consumer (codegen skill) to record transitions
        that SOAR executed during the decision cycle.
        """
        record = AuditRecord(
            record_id=str(uuid.uuid4()),
            record_type="phase-transition",
            task_id=task_id,
            selected_operator=f"advance-phase-{from_phase}-to-{to_phase}",
            cq_isc_ids_evaluated=cq_isc_evaluated,
            cq_isc_prohibit_fired=cq_isc_fired,
            operator_outcome="ADVANCE",
            psi_at_decision=psi_score,
            violations_blocked=violations_blocked,
            timestamp_ms=int(time.time() * 1000),
            confidence_envelope={
                "source": "soar",
                "model": self.model.value,
                "world_state_snapshot": self._hash_wm_state(),
            },
        )
        self._audit_records.append(record)
        return record

    def inject_anchoring_constraint_wmes(
        self,
        constraints: "list[AnchoringConstraint]",
    ) -> "list[WMEInjectionResult]":
        """
        Inject AnchoringConstraint list as WMEs.
        Model A: sends WME commands via stdin pipe.
        Model B: stores in wm_state["anchoring_constraints"].
        AC-014-4: Model B preserves constraints between phase invocations.
        """
        results: list[WMEInjectionResult] = []
        if self.model == SOARBridgeModel.B:
            wm_state = self._load_wm_state()
            wm_state["anchoring_constraints"] = [
                {
                    "constraint_id": c.constraint_id,
                    "dimension": c.dimension,
                    "constraint_text": c.constraint_text,
                    "source_path": c.source_path,
                    "run_id": c.run_id,
                    "status": "active",
                    "matched": False,
                }
                for c in constraints
            ]
            self._save_wm_state(wm_state)
            for c in constraints:
                results.append(WMEInjectionResult(
                    success=True,
                    wme_id=c.constraint_id,
                    attribute="anchoring-constraint",
                    value=c.constraint_text,
                    timestamp_ms=int(time.time() * 1000),
                    model=self.model,
                ))
        else:
            # Model A: send via stdin pipe (one command per constraint)
            for c in constraints:
                try:
                    cmd = (
                        f"add-wme anchoring-constraint "
                        f"constraint-id {json.dumps(c.constraint_id)} "
                        f"dimension {json.dumps(c.dimension)} "
                        f"status active matched false"
                    )
                    self._send_command(cmd)
                    results.append(WMEInjectionResult(
                        success=True,
                        wme_id=c.constraint_id,
                        attribute="anchoring-constraint",
                        value=c.constraint_text,
                        timestamp_ms=int(time.time() * 1000),
                        model=self.model,
                    ))
                except Exception as exc:
                    results.append(WMEInjectionResult(
                        success=False,
                        wme_id=c.constraint_id,
                        attribute="anchoring-constraint",
                        value=c.constraint_text,
                        timestamp_ms=int(time.time() * 1000),
                        model=self.model,
                        error=str(exc),
                    ))
        return results

    def inject_smem_pattern_wmes(
        self,
        patterns: "list[SmemPattern]",
    ) -> "list[WMEInjectionResult]":
        """
        Inject SmemPattern list as advisory `best` preference WMEs.
        INV-003: ONLY best preferences. Never prohibit.

        Model B: store in wm_state["smem_patterns"]
        """
        results: list[WMEInjectionResult] = []
        if self.model == SOARBridgeModel.B:
            wm_state = self._load_wm_state()
            wm_state["smem_patterns"] = [
                {
                    "pattern_id": p.pattern_id,
                    "language": p.language,
                    "constraint_class_set": p.constraint_class_set,
                    "operator_outcome": p.operator_outcome,
                    "code_domain_hash": p.code_domain_hash,
                    "frequency_count": p.frequency_count,
                    "preference_type": "best",  # INV-003: ONLY best
                }
                for p in patterns
                if p.status == "active"
            ]
            self._save_wm_state(wm_state)
            for p in patterns:
                if p.status == "active":
                    results.append(WMEInjectionResult(
                        success=True,
                        wme_id=p.pattern_id,
                        attribute="smem-pattern",
                        value=p.operator_outcome,
                        timestamp_ms=int(time.time() * 1000),
                        model=self.model,
                    ))
        return results

    def clear_anchoring_constraint_wmes(self) -> None:
        """
        Clear all anchoring-constraint WMEs.
        Called at DELIVER and ABORT to enforce transient lifetime (AC-015-1/2/3).
        """
        if self.model == SOARBridgeModel.B:
            wm_state = self._load_wm_state()
            wm_state["anchoring_constraints"] = []
            self._save_wm_state(wm_state)
        else:
            # Model A: retract WMEs via stdin pipe
            self._send_command("remove-wme anchoring-constraint")

    def inject_tier0_gate_wme(self, result: "LspResult") -> WMEInjectionResult:
        """
        Inject LspResult as a tier0-gate WME into SOAR Working Memory.
        Spec 018 T-005: Bridge extension for F1 LSP Gate.

        WME structure (from lsp_gate.md contract):
            (tier0-gate
                ^status   "pass" | "fail" | "unavailable"
                ^violation-count  <int>
                ^language  <str>
                ^tool-name <str>)

        Note: LspResult.status uses long form ("passed"/"failed"); WME uses short form ("pass"/"fail").
        Model A: injects via SOAR stdin pipe.
        Model B: writes tier0_gate fields to wm_state dict.
        """
        status_map = {"passed": "pass", "failed": "fail", "unavailable": "unavailable"}
        wme_status = status_map.get(result.status, result.status)
        violation_count = len(result.violations)

        wme_dict = {
            "class": "tier0-gate",
            "status": wme_status,
            "violation-count": violation_count,
            "language": result.language,
            "tool-name": result.tool_name,
        }

        if self.model == SOARBridgeModel.A and self._alive:
            try:
                cmd = (
                    f"add-wme tier0-gate status {json.dumps(wme_status)} "
                    f"violation-count {violation_count} "
                    f"language {json.dumps(result.language)} "
                    f"tool-name {json.dumps(result.tool_name)}"
                )
                self._send_command(cmd)
                return WMEInjectionResult(
                    success=True,
                    wme_id=str(uuid.uuid4())[:8],
                    attribute="tier0-gate",
                    value=wme_dict,
                    timestamp_ms=int(time.time() * 1000),
                    model=self.model,
                )
            except Exception as exc:
                return WMEInjectionResult(
                    success=False,
                    wme_id=str(uuid.uuid4())[:8],
                    attribute="tier0-gate",
                    value=wme_dict,
                    timestamp_ms=int(time.time() * 1000),
                    model=self.model,
                    error=str(exc),
                )
        else:
            # Model B: write to wm_state file
            wm_state = self._load_wm_state()
            wm_state["tier0_gate"] = result.status
            wm_state["tier0_gate_violation_count"] = violation_count
            wm_state["tier0_gate_language"] = result.language
            wm_state["tier0_gate_tool_name"] = result.tool_name
            self._save_wm_state(wm_state)
            return WMEInjectionResult(
                success=True,
                wme_id=str(uuid.uuid4())[:8],
                attribute="tier0-gate",
                value=wme_dict,
                timestamp_ms=int(time.time() * 1000),
                model=self.model,
            )

    def inject_psi_diverging_wme(
        self,
        criterion_id: str,
        retry_count: int,
    ) -> WMEInjectionResult:
        """
        Inject (psi ^criterion-id <criterion_id> ^status diverging) WME.
        INV-006: Called before ImpasseHandler — SOAR must see the signal first.
        Spec 018 T-026: F7 Ψ Score Granularity + Convergence Tracking.
        """
        if self.model == SOARBridgeModel.B:
            wm_state = self._load_wm_state()
            if "psi_diverging" not in wm_state:
                wm_state["psi_diverging"] = []
            wm_state["psi_diverging"].append({
                "criterion_id": criterion_id,
                "status": "diverging",
                "retry_count": retry_count,
            })
            self._save_wm_state(wm_state)
        return WMEInjectionResult(
            success=True,
            wme_id=f"psi-diverging-{criterion_id}",
            attribute="psi",
            value="diverging",
            timestamp_ms=int(time.time() * 1000),
            model=self.model,
        )

    def phase_invoke(self, wme: dict, output_file: Optional[Path] = None) -> OperatorSelection:
        """
        Model B: Per-phase SOAR invocation.
        Load WM state from file, inject WME, run one decision cycle,
        write operator result back to state file, return OperatorSelection.
        """
        # Load existing WM state
        wm_state = self._load_wm_state()

        # Append new WME
        wm_state.setdefault("wmes", []).append({
            "id": str(uuid.uuid4())[:8],
            "attr": wme.get("attr", wme.get("attribute", "unknown")),
            "value": wme.get("value"),
            "ts": int(time.time() * 1000),
        })

        # Evaluate constraints against WM state (software simulation of SOAR)
        operator = self._evaluate_model_b(wm_state)

        # Write updated state
        wm_state["last_operator"] = operator.operator_name
        wm_state["last_operator_ts"] = operator.timestamp_ms
        self._save_wm_state(wm_state)

        if output_file:
            output_file.write_text(
                json.dumps({"operator": operator.operator_name, "ts": operator.timestamp_ms}, indent=2)
            )

        # Record in audit log (INV-004)
        record = AuditRecord(
            record_id=str(uuid.uuid4()),
            record_type="phase-transition",
            task_id=wme.get("task_id"),
            selected_operator=operator.operator_name,
            cq_isc_ids_evaluated=operator.cq_isc_ids_evaluated,
            cq_isc_prohibit_fired=operator.prohibit_fired,
            operator_outcome=self._map_operator_to_outcome(operator.operator_name),
            psi_at_decision=wm_state.get("psi_score", 0.0),
            violations_blocked=wm_state.get("violations_blocked", 0),
            timestamp_ms=operator.timestamp_ms,
        )
        self._audit_records.append(record)
        return operator

    def shutdown(self):
        """
        Graceful shutdown of SOAR process (Model A).
        Saves WM state to file before exit (Model B compatibility).
        """
        if self._process and self._alive:
            try:
                self._send_command("quit")
                self._process.stdin.close()
                self._process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                self._process.kill()
            finally:
                self._alive = False
                self._pid = None
                print("[SOAR Bridge] Model A process shut down.", file=sys.stderr, flush=True)

        # Always save WM state for resumability
        wm_state = self._load_wm_state()
        wm_state["shutdown_ts"] = int(time.time() * 1000)
        wm_state["audit_records"] = [r.to_dict() for r in self._audit_records]
        self._save_wm_state(wm_state)

    # ------------------------------------------------------------------
    # Internal: Model A helpers
    # ------------------------------------------------------------------

    def _drain_stdout(self, timeout: float = 2.0) -> str:
        """
        Non-blocking drain of SOAR stdout using select() with deadline.
        Reads until no more data arrives within `timeout` seconds total.
        """
        import select as _select
        output_parts: list[str] = []
        if not self._process or not self._process.stdout:
            return ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                ready, _, _ = _select.select(
                    [self._process.stdout], [], [], min(remaining, 0.2)
                )
            except (OSError, ValueError):
                break
            if not ready:
                # No data available — if we already got some output, stop reading
                if output_parts:
                    break
                continue
            try:
                import os as _os
                chunk = _os.read(self._process.stdout.fileno(), 4096)
                if chunk:
                    decoded = chunk.decode(errors="replace")
                    output_parts.append(decoded)
                    if self.verbose:
                        for line in decoded.splitlines():
                            if "[SOAR]" in line:
                                print(line.strip(), file=sys.stderr, flush=True)
                else:
                    break
            except (IOError, OSError):
                break
        return "".join(output_parts)

    def _find_soar_binary(self) -> Optional[str]:
        """Locate the SOAR binary on PATH."""
        for name in SOAR_BINARY_NAMES:
            result = subprocess.run(
                ["which", name], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        # Also check common install locations
        common_paths = [
            "/usr/local/bin/soar",
            "/opt/soar/bin/soar",
            os.path.expanduser("~/soar/bin/soar"),
            os.path.expanduser("~/.soar/soar"),
        ]
        for path in common_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def _startup_configure(self) -> None:
        """
        Configure persistent EPMEM and SMEM stores before first decision cycle.

        Called by start() after sourcing the SOAR config file, before run 2 -d.
        Requires self.memory_config to be set (ADR-001, ADR-002).
        If memory_config is None, skips persistence configuration (ephemeral mode).

        T-007: EPMEM file-backed persistence (FR-EPMEM-001, FR-EPMEM-002, FR-EPMEM-004, FR-EPMEM-005)
        T-011: SMEM file-backed persistence (FR-SMEM-001, FR-SMEM-002, FR-SMEM-003)
        """
        if self.memory_config is None:
            return

        cfg = self.memory_config

        # --- T-007: EPMEM persistence config ---
        # Ensure parent directory exists
        cfg.epmem_db_path.parent.mkdir(parents=True, exist_ok=True)
        epmem_path = str(cfg.epmem_db_path)
        self._send_command("epmem --set database file")
        self._send_command(f"epmem --set path {{{epmem_path}}}")
        self._send_command("epmem --set append on")
        self._send_command("epmem --init")
        print(
            f"[SOAR Bridge] EPMEM configured: file-backed at {epmem_path} (append mode)",
            file=__import__("sys").stderr, flush=True,
        )

        # --- T-011: SMEM persistence config ---
        cfg.smem_db_path.parent.mkdir(parents=True, exist_ok=True)
        smem_path = str(cfg.smem_db_path)
        self._send_command("smem --set database file")
        self._send_command(f"smem --set path {{{smem_path}}}")
        self._send_command("smem --init")
        print(
            f"[SOAR Bridge] SMEM configured: file-backed at {smem_path}",
            file=__import__("sys").stderr, flush=True,
        )

    def _send_command(self, cmd: str):
        """Send a command to the SOAR process stdin (bytes mode)."""
        if self._process and self._process.stdin:
            self._process.stdin.write((cmd + "\n").encode())
            self._process.stdin.flush()

    def _verify_alive(self) -> bool:
        """Check if the SOAR process is still running."""
        if self._process is None:
            return False
        poll = self._process.poll()
        if poll is not None:
            self._alive = False
            return False
        return True

    def _get_operator_model_a(self) -> OperatorSelection:
        """
        Run one SOAR decision cycle and parse the selected operator from stdout.
        """
        if not self._verify_alive():
            if REQUIRE_MODEL_A:
                raise RuntimeError(
                    "CODEGEN_REQUIRE_MODEL_A=1 but SOAR Model A process died mid-run."
                )
            # Process died — fall back to Model B
            self.model = SOARBridgeModel.B
            return self._get_operator_model_b()

        self._send_command("run 1 -d")
        # Give SOAR time to run the decision cycle (0.8s is sufficient in practice)
        time.sleep(0.8)
        output = self._drain_stdout(timeout=MODEL_A_IPC_TIMEOUT_SECONDS)

        operator_name = self._parse_operator_from_output(output)
        return OperatorSelection(
            operator_name=operator_name,
            confidence=1.0,
            source="soar",
        )

    def _parse_operator_from_output(self, output: str) -> str:
        """Parse SOAR stdout for selected operator name.

        SOAR 9.6.4 decision-trace format:  '   3:    O: O2 (advance-phase)'
        Older trace format:                '==>O: O1 (operator-name)'
        Production writes via (write):     '[SOAR] ...'
        """
        import re
        for line in output.split("\n"):
            line = line.strip()
            # SOAR 9.6.4 decision trace: '3:    O: O2 (advance-phase)'
            m = re.search(r"O:\s+\S+\s+\(([^)]+)\)", line)
            if m:
                return m.group(1).strip()
            # Phase transition apply writes
            if "[SOAR] Phase transition" in line or "Phase transition:" in line:
                return "advance-phase"
            # Phase propose writes that indicate a clean advance
            if "[SOAR] GATE phase CLEAN" in line:
                return "advance-phase"
            if "[SOAR] TEST phase: Tier 1 gate PASSED" in line:
                return "advance-phase"
            if "[SOAR] RE phase ready to advance" in line:
                return "advance-phase"
            if "[SOAR] DECOMPOSE phase ready" in line:
                return "advance-phase"
            if "[SOAR] RETRY_TASK" in line:
                return "retry-task"
            if "[SOAR] ESCALATE" in line or "ESCALATE:" in line:
                return "escalate"
            if "[SOAR] DELIVER: pipeline complete" in line:
                return "deliver"
        return "unknown"

    def _parse_wme_timetags(self, output: str) -> dict[str, int]:
        """
        Parse 'print -i <id>' output and return {attribute: timetag} mapping.

        SOAR 9.6.4 format: '(19: B1 ^current-phase RE)'
        Returns dict mapping attribute name → timetag integer.
        """
        import re
        result: dict[str, int] = {}
        for m in re.finditer(r'\((\d+):\s*\S+\s+\^(\S+)\s+', output):
            timetag = int(m.group(1))
            attribute = m.group(2)
            result[attribute] = timetag
        return result

    def _parse_build_id(self, output: str) -> Optional[str]:
        """
        Parse SOAR print output for the build sub-object identifier.

        After the init rule fires, S1 has: (S1 ^name codegen ^build B3 ...)
        SOAR prints identifiers as uppercase letter + digits (e.g. B3, B12).
        Returns the identifier string (e.g. "B3") or None if not found.
        """
        import re
        # Look for ^build followed by an identifier like B3, I7, etc.
        m = re.search(r'\^build\s+([A-Za-z]\d+)', output)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------
    # Internal: Model B helpers
    # ------------------------------------------------------------------

    def _inject_wme_model_b(
        self,
        attribute: str,
        value: Any,
        wme_id: str,
        ts: int,
        task_id: Optional[str],
    ) -> WMEInjectionResult:
        """Append WME to serialized WM state file (Model B)."""
        wm_state = self._load_wm_state()
        wm_state.setdefault("wmes", []).append({
            "id": wme_id,
            "attr": attribute,
            "value": value,
            "task_id": task_id,
            "ts": ts,
        })
        self._save_wm_state(wm_state)
        return WMEInjectionResult(
            success=True,
            wme_id=wme_id,
            attribute=attribute,
            value=value,
            timestamp_ms=ts,
            model=self.model,
        )

    def _get_operator_model_b(self) -> OperatorSelection:
        """
        Model B: evaluate operator from serialized WM state file.
        Uses a Python reimplementation of the SOAR Rete evaluation logic
        for the core prohibit/advance/retry/escalate operators.
        """
        wm_state = self._load_wm_state()
        return self._evaluate_model_b(wm_state)

    def _evaluate_model_b(self, wm_state: dict) -> OperatorSelection:
        """
        Model B Rete evaluation: determine selected operator from WM state.

        Mirrors the SOAR production rule logic in codegen.soar and phases.soar.
        INV-005 semantics: current-phase is checked first.
        INV-002 semantics: any CQ-ISC violation blocks ADVANCE.
        INV-010 semantics: tier1-gate=fail blocks DELIVER.
        """
        violations = wm_state.get("violations", [])
        confirmed_failing = [v for v in violations if v.get("status") == "confirmed-failing"]
        retry_count = wm_state.get("retry_count", 0)
        max_retries = wm_state.get("max_retries", 3)
        psi_score = wm_state.get("psi_score", 0.0)
        psi_threshold = wm_state.get("psi_threshold", 0.70)
        tier1_gate = wm_state.get("tier1_gate", "pending")
        current_phase = wm_state.get("current_phase", "RE")
        prohibit_fired = [v.get("cq_isc_id", "UNKNOWN") for v in confirmed_failing]
        cq_isc_evaluated = list({v.get("cq_isc_id") for v in violations if v.get("cq_isc_id")})

        # Escalate if max retries exceeded
        if confirmed_failing and retry_count >= max_retries:
            return OperatorSelection(
                operator_name="escalate",
                confidence=1.0,
                source="model-b-rete",
                cq_isc_ids_evaluated=cq_isc_evaluated,
                prohibit_fired=prohibit_fired,
            )

        # Retry if violations exist and retries available
        if confirmed_failing and retry_count < max_retries:
            return OperatorSelection(
                operator_name="retry-task",
                confidence=1.0,
                source="model-b-rete",
                cq_isc_ids_evaluated=cq_isc_evaluated,
                prohibit_fired=prohibit_fired,
            )

        # Deliver if at DELIVER phase with all gates passing
        if (
            current_phase == "DELIVER"
            and tier1_gate == "pass"
            and psi_score >= psi_threshold
            and not confirmed_failing
        ):
            return OperatorSelection(
                operator_name="deliver",
                confidence=1.0,
                source="model-b-rete",
                cq_isc_ids_evaluated=cq_isc_evaluated,
                prohibit_fired=[],
            )

        # Tier 1 fail blocks advance at TEST phase
        if current_phase == "TEST" and tier1_gate == "fail":
            return OperatorSelection(
                operator_name="retry-tier1",
                confidence=1.0,
                source="model-b-rete",
                cq_isc_ids_evaluated=cq_isc_evaluated,
                prohibit_fired=[],
            )

        # Default: advance phase if clean
        if not confirmed_failing and psi_score >= psi_threshold:
            return OperatorSelection(
                operator_name="advance-phase",
                confidence=1.0,
                source="model-b-rete",
                cq_isc_ids_evaluated=cq_isc_evaluated,
                prohibit_fired=[],
            )

        # Default fallback
        return OperatorSelection(
            operator_name="wait",
            confidence=0.5,
            source="model-b-rete",
            cq_isc_ids_evaluated=cq_isc_evaluated,
            prohibit_fired=prohibit_fired,
        )

    def _load_wm_state(self) -> dict:
        """Load serialized WM state from file (Model B)."""
        if self.wm_state_file.exists():
            try:
                return json.loads(self.wm_state_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "pipeline_id": self._pipeline_id,
            "current_phase": "RE",
            "violations": [],
            "retry_count": 0,
            "max_retries": 3,
            "psi_score": 0.0,
            "psi_threshold": 0.70,
            "tier1_gate": "pending",
            "wmes": [],
        }

    def _save_wm_state(self, state: dict):
        """Persist WM state to file (Model B) with secure permissions (SEC-025 FIX-2)."""
        _secure_write_wm_state(self.wm_state_file, json.dumps(state, indent=2))

    def _hash_wm_state(self) -> str:
        """Produce a short hash of current WM state for confidence envelope."""
        wm_state = self._load_wm_state()
        import hashlib
        return hashlib.sha256(json.dumps(wm_state, sort_keys=True).encode()).hexdigest()[:16]

    def _map_operator_to_outcome(self, operator_name: str) -> str:
        mapping = {
            "advance-phase": "ADVANCE",
            "retry-task": "RETRY",
            "retry-tier1": "RETRY",
            "escalate": "ESCALATE",
            "deliver": "DELIVER",
        }
        return mapping.get(operator_name, "UNKNOWN")


# ---------------------------------------------------------------------------
# CLI entry point — used by codegen skill via Bash tool
# ---------------------------------------------------------------------------

def _cli_main():
    """
    CLI for SOAR bridge invocation from Bash tool.
    Usage:
      python soar_bridge.py --start --smem-file <path>
      python soar_bridge.py --inject-wme '{"attr": "function-length", "value": 45}'
      python soar_bridge.py --get-operator
      python soar_bridge.py --export-epmem --output <path>
      python soar_bridge.py --stop
      python soar_bridge.py --phase-invoke --wm-state <path> --inject-wme '...'
    """
    import argparse

    parser = argparse.ArgumentParser(description="SOAR SML Bridge for /codegen")
    parser.add_argument("--start", action="store_true", help="Start SOAR daemon (Model A)")
    parser.add_argument("--stop", action="store_true", help="Stop SOAR daemon")
    parser.add_argument("--inject-wme", type=str, help="JSON WME to inject")
    parser.add_argument("--get-operator", action="store_true", help="Get selected operator")
    parser.add_argument("--export-epmem", action="store_true", help="Export EPMEM audit records")
    parser.add_argument("--output", type=str, help="Output file for EPMEM export")
    parser.add_argument("--phase-invoke", action="store_true", help="Per-phase invocation (Model B)")
    parser.add_argument("--wm-state", type=str, default=str(DEFAULT_WM_STATE_FILE))
    parser.add_argument("--smem-file", type=str, default=str(DEFAULT_SMEM_FILE))
    parser.add_argument("--pid-file", type=str, default="/tmp/codegen-soar.pid")

    args = parser.parse_args()
    wm_state_file = Path(args.wm_state)
    smem_file = Path(args.smem_file)
    pid_file = Path(args.pid_file)

    if args.start:
        bridge = SOARBridge(smem_file=smem_file, wm_state_file=wm_state_file)
        success = bridge.start()
        if success:
            pid_file.write_text(str(bridge._pid))
            print(f"[SOAR Bridge] Started (Model A) — PID {bridge._pid}", flush=True)
        else:
            # Model B fallback — SEC-025 FIX-2: secure write + cleanup registration
            state = {"model": "B", "started_ts": int(time.time() * 1000)}
            _secure_write_wm_state(wm_state_file, json.dumps(state, indent=2))
            _register_wm_state_cleanup(wm_state_file)
            print("[SOAR Bridge] Model B active (per-phase invocation)", flush=True)
        sys.exit(0 if success else 1)

    if args.phase_invoke:
        bridge = SOARBridge(
            model=SOARBridgeModel.B,
            wm_state_file=wm_state_file,
            smem_file=smem_file,
        )
        wme = {}
        if args.inject_wme:
            wme = json.loads(args.inject_wme)
        op = bridge.phase_invoke(wme)
        result = {"operator": op.operator_name, "prohibit_fired": op.prohibit_fired, "ts": op.timestamp_ms}
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2))
        else:
            print(json.dumps(result, indent=2))
        sys.exit(0)

    if args.inject_wme:
        wme_data = json.loads(args.inject_wme)
        bridge = SOARBridge(wm_state_file=wm_state_file)
        result = bridge.inject_wme(
            attribute=wme_data.get("attr", wme_data.get("attribute", "unknown")),
            value=wme_data.get("value"),
            task_id=wme_data.get("task_id"),
        )
        print(json.dumps({"success": result.success, "wme_id": result.wme_id, "model": result.model.value}))
        sys.exit(0)

    if args.get_operator:
        bridge = SOARBridge(wm_state_file=wm_state_file)
        op = bridge.get_selected_operator()
        print(json.dumps({"operator": op.operator_name, "prohibit_fired": op.prohibit_fired}))
        sys.exit(0)

    if args.export_epmem:
        bridge = SOARBridge(wm_state_file=wm_state_file)
        audit = bridge.export_audit_record()
        if args.output:
            Path(args.output).write_text(json.dumps(audit, indent=2))
            print(f"[SOAR Bridge] EPMEM exported to {args.output}")
        else:
            print(json.dumps(audit, indent=2))
        sys.exit(0)

    if args.stop:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, 15)  # SIGTERM
                pid_file.unlink()
                print(f"[SOAR Bridge] Stopped process {pid}")
            except ProcessLookupError:
                print(f"[SOAR Bridge] Process {pid} not found (already stopped)")
                pid_file.unlink(missing_ok=True)
        else:
            print("[SOAR Bridge] No PID file found — nothing to stop")
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    _cli_main()
