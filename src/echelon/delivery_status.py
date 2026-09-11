"""Typed delivery-status command service for the Typer CLI."""

from __future__ import annotations

import json
from pathlib import Path

from harness.provider_capability import ProviderCapability


def command(
    *,
    spec_id: str = "",
    strategy: str = "",
    json_output: bool = False,
    project_root: Path | None = None,
) -> None:
    """Render Phase B status from values already validated by Typer."""
    from echelon.cli import (
        _banner,
        _delivery_status_fields,
        _delivery_status_summary,
        _iter_harness_build_states,
        _require_provider_capability,
    )

    root = project_root or Path.cwd()
    _require_provider_capability(
        "echelon delivery status",
        ProviderCapability.BUILD,
        project_dir=root,
    )
    states = _iter_harness_build_states(root)
    if spec_id:
        states = [
            state
            for state in states
            if str(state.get("spec_id") or "") == spec_id
        ]
    if strategy:
        states = [
            state
            for state in states
            if str(state.get("strategy_id") or "") == strategy
        ]

    summaries = [
        _delivery_status_summary(state, project_root=root) for state in states
    ]
    if json_output:
        payload = {
            "status": summaries[0]["status"] if summaries else "none",
            "spec_id": spec_id
            or (summaries[0].get("spec_id") if summaries else ""),
            "strategy": strategy,
            "latest": summaries[0] if summaries else None,
            "states": summaries[:10],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if not summaries:
        next_step = (
            f"echelon delivery run {spec_id}"
            if spec_id
            else "echelon delivery run <spec_id>"
        )
        _banner(
            "DELIVERY STATUS",
            [
                ("status", "No delivery runs found"),
                ("next", next_step),
            ],
            subtitle="Phase B delivery",
        )
        return

    latest = summaries[0]
    subtitle = "Phase B delivery"
    if len(summaries) > 1:
        subtitle += f" - {len(summaries)} matching state files"
    _banner("DELIVERY STATUS", _delivery_status_fields(latest), subtitle=subtitle)
