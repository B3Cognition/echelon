"""
Echelon Typed Kernel
====================
Pure-function modules for deterministic state management and transition evaluation.

Modules:
    schema_validator  — Tier-1 JSON Schema subset validator (T008)
    accessors         — Typed state field accessors (T009)
    state_loader      — Load + validate state.json (T010)
    evaluator         — Typed transition evaluator (T011)
    preflight         — Preflight runner + probe registry (T019)
    constitution_checker — Constitution principle grammar runner (T021)

Non-goals:
    - No I/O on the critical path (pure functions only)
    - No agent dispatch
    - No journal writes (caller's responsibility)
    - No state mutation
"""

__version__ = "0.1.0"
__all__ = ["schema_validator", "accessors", "state_loader", "evaluator"]
