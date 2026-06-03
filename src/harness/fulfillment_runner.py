"""Fulfillment verification orchestration for harness convergence."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol

from harness.skill_loader import build_skill_prompt, find_skill


class PromptExecutor(Protocol):
    @property
    def cli(self) -> str:
        ...

    def exec_prompt(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> int:
        ...


class FulfillmentRunner:
    """Runs the verify-spec skill without teaching the LLM provider Echelon semantics."""

    def __init__(self, prompt_executor: PromptExecutor) -> None:
        self._prompt_executor = prompt_executor

    def refresh(self, worktree_path: str, spec_id: str) -> int:
        skill_path = find_skill(
            "echelon.verify-spec",
            Path(worktree_path),
            self._prompt_executor.cli,
        )
        if skill_path is None:
            return 127

        prompt = build_skill_prompt(skill_path, spec_id)
        return self._prompt_executor.exec_prompt(worktree_path, prompt)
