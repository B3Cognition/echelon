"""Resume skill -- resume a blocked ralph-loop with an answer.

Per T045 / FR-CLI-002:
- Parse spec_id from user message
- Resume blocked loop with user answer
- Re-launch from current iteration (not from scratch)
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

from harness.escalation import EscalationHandler
from harness.paths import runs_dir, current_build_marker, build_dir as _build_dir_fn
from harness.state import StateStore

logger = logging.getLogger(__name__)


def resume(
    user_message: str,
    provider: Any,
    gitops: Any,
    base_dir: str = ".",
) -> None:
    """Execute /speckit-harness-resume skill.

    Args:
        user_message: Natural-language resume request with answer.
        provider: SandboxProvider instance.
        gitops: GitOpsManager instance.
        base_dir: Base directory for harness state.
    """
    # 1. Parse spec_id and answer
    spec_id, strategy_id, answer = _parse_resume_input(user_message)

    if not spec_id:
        print("Which spec? Provide a spec ID (e.g., 'resume spec 012 ...').",
              file=sys.stderr)
        return

    if not answer:
        print("Please provide an answer for the escalation.", file=sys.stderr)
        return

    # 2. Resolve build directory from .current-build-{spec_id} marker
    base_path = Path(base_dir)
    marker = current_build_marker(base_path, spec_id)
    if marker.exists():
        _bid = marker.read_text().strip()
        _bdir = _build_dir_fn(base_path, _bid)
    else:
        # Fall back to most-recent build-* dir for this spec
        rd = runs_dir(base_path)
        builds = sorted(rd.glob("build-*/"), reverse=True) if rd.exists() else []
        _bdir = builds[0] if builds else _build_dir_fn(base_path, "")
        _bid = _bdir.name if _bdir.name else ""
    state_dir = _bdir / "state"
    state_store = StateStore(state_dir, spec_id, strategy_id)
    state = state_store.read()

    if not state:
        print(f"No state found for spec={spec_id}, strategy={strategy_id}.",
              file=sys.stderr)
        return

    status = state.get("status", "unknown")

    # 3. Check if blocked
    if status != "blocked":
        print(f"Loop is not blocked. Current status: {status}.", file=sys.stderr)
        return

    # 4. Resume with answer
    escalation_file = state.get("escalation_file")
    escalation_handler = EscalationHandler(str(_bdir))

    if escalation_file:
        escalation_handler.resume(escalation_file, answer)
    else:
        logger.info("No escalation file -- resuming from guided mode pause")

    # 5. Re-enter the normal run/coordinator path so resume uses the same
    # provider, LLM prompt, build id, and strategy wiring as delivery resume.
    from harness.config import load_config
    from harness.skills.run_skill import run

    mode = state.get("mode", "semi")
    run_message = (
        f"spec {spec_id} strategy={strategy_id} mode={mode} resume\n\n"
        f"task: {answer}"
    )
    run(
        run_message,
        provider=provider,
        gitops=gitops,
        base_dir=base_dir,
        config=load_config(),
        resume_build_id=_bid or None,
    )


def _parse_resume_input(text: str) -> tuple:
    """Parse spec_id, strategy_id, and answer from text.

    Returns: (spec_id, strategy_id, answer)
    """
    spec_match = re.search(r"(?:spec\s+|spec_id\s*[=:]\s*)(\w[\w-]*)", text, re.IGNORECASE)
    spec_id = spec_match.group(1) if spec_match else ""

    strat_match = re.search(r"(?:strategy\s+|strategy_id\s*[=:]\s*)(\w[\w-]*)", text, re.IGNORECASE)
    strategy_id = strat_match.group(1) if strat_match else "default"

    # Answer is everything after "answer:" or the main message content
    answer_match = re.search(r"(?:answer\s*[:=]\s*)(.*)", text, re.IGNORECASE | re.DOTALL)
    if answer_match:
        answer = answer_match.group(1).strip()
    else:
        # Use the whole text minus the spec/strategy parts as the answer
        answer = text
        if spec_match:
            answer = answer[:spec_match.start()] + answer[spec_match.end():]
        if strat_match:
            answer = answer[:strat_match.start()] + answer[strat_match.end():]
        answer = answer.strip()

    return spec_id, strategy_id, answer
