"""Admission for optional tool-disabled, host-serviced inspection turns."""
from __future__ import annotations

import math
from pathlib import Path
from collections.abc import Mapping

from harness.ai_cli_backend import CliRunRequest, CliRunResult


def inspection_request_failure(request: CliRunRequest) -> CliRunResult | None:
    # Lazy import keeps the shared validator independent of adapter import order.
    from harness.ai_cli_backends.claude import host_workspace_synthesis_boundary_available

    if not host_workspace_synthesis_boundary_available():
        return CliRunResult(125, "", "inspection isolation is unavailable",
                            metadata={"failure_reason": "isolation_unavailable"})
    if not _valid_request(request):
        return CliRunResult(125, "", "invalid inspection request",
                            metadata={"failure_reason": "invalid_request"})
    return None


def _valid_request(request: object) -> bool:
    if not isinstance(request, CliRunRequest):
        return False
    timeout = request.timeout_s
    if (type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0
            or type(request.prompt) is not str or not request.prompt
            or type(request.cwd) is not str or not request.cwd
            or not isinstance(request.metadata, Mapping)
            or set(request.metadata) != {"prompt_metadata"}):
        return False
    metadata = request.metadata["prompt_metadata"]
    if (not isinstance(metadata, Mapping) or set(metadata) != {"model_tier", "effort"}
            or type(metadata["model_tier"]) is not str
            or metadata["model_tier"] not in {"fast", "balanced", "strong"}
            or type(metadata["effort"]) is not str
            or metadata["effort"] not in {"low", "medium", "high"}):
        return False
    try:
        cwd = Path(request.cwd)
        return cwd.is_dir() and not cwd.is_symlink() and next(cwd.iterdir(), None) is None
    except (OSError, ValueError):
        return False
