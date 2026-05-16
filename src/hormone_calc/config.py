"""DynamicsConfig — loads endocrine.dynamics from echelon-config.yml or falls back.

Loaded once per `hormone-calc compute` invocation. Trigger modules receive a
DynamicsConfig instance and use it for all magnitude calculations.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class Band:
    upto: float
    delta: float


@dataclass(frozen=True)
class BudgetPressureConfig:
    bands: tuple[Band, ...]
    critical_broadcast: float


@dataclass(frozen=True)
class IterationPressureConfig:
    bands: tuple[Band, ...]


@dataclass(frozen=True)
class TaskComplexityConfig:
    multiplier: float
    archetype_base: dict[str, float]
    agent_bump: dict[str, float]


@dataclass(frozen=True)
class DynamicsConfig:
    budget_pressure: BudgetPressureConfig
    iteration_pressure: IterationPressureConfig
    task_complexity: TaskComplexityConfig


DEFAULT_DYNAMICS = DynamicsConfig(
    budget_pressure=BudgetPressureConfig(
        bands=(
            Band(upto=0.40, delta=0.00),
            Band(upto=0.60, delta=0.02),
            Band(upto=0.80, delta=0.05),
            Band(upto=0.95, delta=0.10),
            Band(upto=1.00, delta=0.15),
        ),
        critical_broadcast=0.05,
    ),
    iteration_pressure=IterationPressureConfig(
        bands=(
            Band(upto=0.50, delta=0.00),
            Band(upto=0.75, delta=0.03),
            Band(upto=1.00, delta=0.08),
        ),
    ),
    task_complexity=TaskComplexityConfig(
        multiplier=0.15,
        archetype_base={
            "exploration": 0.40,
            "validation":  0.50,
            "feasibility": 0.60,
            "solution":    0.70,
            "build":       0.80,
            "innovation":  0.50,
            "learning":    0.30,
            "control":     0.40,
        },
        agent_bump={
            "IMPLEMENTER": 0.10,
            "DEBUGGER":    0.15,
            "ARCHITECT":   0.10,
            "GATEKEEPER":  0.10,
        },
    ),
)


def load(config_path: Optional[Path] = None) -> DynamicsConfig:
    """Load DynamicsConfig from echelon-config.yml, fall back to DEFAULT_DYNAMICS.

    If config_path is None, looks in this priority order:
      1. ENDOCRINE_CONFIG_FILE env var (matches endocrine.sh behaviour)
      2. <cwd>/extension/echelon-config.yml
      3. <cwd>/.specify/extensions/echelon/echelon-config.yml
      4. <cwd>/echelon-config.yml
    Returns DEFAULT_DYNAMICS if none found or if file lacks endocrine.dynamics.
    """
    if config_path is None:
        env = os.environ.get("ENDOCRINE_CONFIG_FILE")
        if env:
            config_path = Path(env)
        else:
            for cand in ("extension/echelon-config.yml",
                         ".specify/extensions/echelon/echelon-config.yml",
                         "echelon-config.yml"):
                p = Path.cwd() / cand
                if p.exists():
                    config_path = p
                    break

    if config_path is None or not config_path.exists():
        return DEFAULT_DYNAMICS

    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        return DEFAULT_DYNAMICS

    dyn = (data.get("endocrine") or {}).get("dynamics")
    if not isinstance(dyn, dict):
        return DEFAULT_DYNAMICS

    try:
        return _parse_dynamics(dyn)
    except Exception:
        return DEFAULT_DYNAMICS


def _parse_dynamics(d: dict) -> DynamicsConfig:
    bp = d.get("budget_pressure") or {}
    ip = d.get("iteration_pressure") or {}
    tc = d.get("task_complexity") or {}

    return DynamicsConfig(
        budget_pressure=BudgetPressureConfig(
            bands=tuple(Band(upto=float(b["upto"]), delta=float(b["delta"]))
                        for b in bp.get("bands", [])),
            critical_broadcast=float(bp.get("critical_broadcast", 0.0)),
        ),
        iteration_pressure=IterationPressureConfig(
            bands=tuple(Band(upto=float(b["upto"]), delta=float(b["delta"]))
                        for b in ip.get("bands", [])),
        ),
        task_complexity=TaskComplexityConfig(
            multiplier=float(tc.get("multiplier", 0.15)),
            archetype_base=dict(tc.get("archetype_base", {})),
            agent_bump=dict(tc.get("agent_bump", {})),
        ),
    )
