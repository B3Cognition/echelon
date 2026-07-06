from __future__ import annotations

from pathlib import Path


class StackError(Exception):
    """Base class for Echelon stack errors."""


class StackValidationError(StackError):
    """Raised when a stack definition fails schema validation."""

    def __init__(self, message: str, *, path: Path | None = None, field_path: str | None = None) -> None:
        self.path = path
        self.field_path = field_path
        super().__init__(message)

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.field_path:
            parts.append(f"field: {self.field_path}")
        if self.path:
            parts.append(f"path: {self.path}")
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0]} ({', '.join(parts[1:])})"


class StackResolutionError(StackError):
    """Raised when selected stacks cannot be resolved."""


class StackConflictError(StackResolutionError):
    """Raised when selected stacks provide conflicting capabilities."""
