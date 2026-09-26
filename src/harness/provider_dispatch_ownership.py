"""Structural inventory for command-driven Phase A provider boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


_FINALIZED = {
    ("squad.py", "_dispatch_controller_provider"),
    ("squad_executors.py", "_exec_raw_agent_with_contract"),
}
_STRONGER_BOUNDARIES = {
    ("discovery_turns.py", "run_inspection_turn"),
    ("managed_commander.py", "run_inspection_turn"),
}
_OUT_OF_SCOPE_PREFIXES = ("re_",)


class _CallInventory(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.stack: list[str] = []
        self.exec_calls: list[tuple[str, tuple[str, ...]]] = []
        self.inspection_calls: list[tuple[str, tuple[str, ...]]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            owner = self.stack[-1] if self.stack else "<module>"
            location = f"{self.filename}:{owner}"
            if node.func.attr == "exec_agent":
                self.exec_calls.append((location, tuple(self.stack)))
            elif node.func.attr == "run_inspection_turn":
                self.inspection_calls.append((location, tuple(self.stack)))
        self.generic_visit(node)


def provider_dispatch_call_sites(root: Path) -> dict[str, object]:
    """Classify Phase A provider calls; unknown calls are explicit bypasses."""
    finalized: set[str] = set()
    stronger: dict[str, str] = {}
    bypasses: set[str] = set()
    for path in sorted(Path(root).rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        filename = path.name
        if filename.startswith(_OUT_OF_SCOPE_PREFIXES) or "/re_v2/" in f"/{relative}":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeDecodeError):
            bypasses.add(f"{relative}:<unreadable>")
            continue
        inventory = _CallInventory(filename)
        inventory.visit(tree)
        for location, stack in inventory.exec_calls:
            owner = next(
                (
                    function
                    for function in stack
                    if (filename, function) in _FINALIZED
                ),
                None,
            )
            if owner is not None:
                finalized.add(f"{filename}:{owner}")
            else:
                bypasses.add(location)
        for location, _stack in inventory.inspection_calls:
            normalized = f"{filename}:run_inspection_turn"
            if (filename, "run_inspection_turn") in _STRONGER_BOUNDARIES:
                stronger[normalized] = "managed_discovery"
    return {
        "finalized": finalized,
        "stronger_boundaries": stronger,
        "bypasses": bypasses,
    }
