"""Phase 2 interface compliance checks.

Per T054 / FR-PHASE2-001 / Constitution P4:
- SandboxProvider method signatures match Phase 1 exactly
- No new abstract methods added
- No echelon internal imports in harness code
"""

from __future__ import annotations

import inspect
import importlib
from pathlib import Path

import pytest

from harness.provider import SandboxProvider, MANDATORY_METHODS


# Phase 1 interface snapshot
PHASE1_METHODS = {
    "create", "exec", "write_file", "read_file", "destroy",
    "capabilities", "snapshot", "restore", "stream_exec", "get_cost",
}


@pytest.mark.unit
class TestSandboxProviderInterface:
    """Verify Phase 1 SandboxProvider interface is unchanged."""

    def test_mandatory_methods_unchanged(self) -> None:
        """All Phase 1 mandatory methods still exist."""
        expected_mandatory = {"create", "exec", "write_file", "read_file", "destroy"}
        assert MANDATORY_METHODS == expected_mandatory

    def test_all_phase1_methods_present(self) -> None:
        """All Phase 1 methods still exist on SandboxProvider."""
        for method_name in PHASE1_METHODS:
            assert hasattr(SandboxProvider, method_name), (
                f"Phase 1 method '{method_name}' missing from SandboxProvider"
            )

    def test_no_new_abstract_methods(self) -> None:
        """No new abstract methods added beyond Phase 1."""
        abstract_methods = {
            name for name, method in inspect.getmembers(SandboxProvider)
            if getattr(method, "__isabstractmethod__", False)
        }
        phase1_abstract = {"create", "exec", "write_file", "read_file", "destroy"}
        new_abstract = abstract_methods - phase1_abstract
        assert not new_abstract, (
            f"New abstract methods added (P4 violation): {new_abstract}"
        )

    def test_create_signature_unchanged(self) -> None:
        sig = inspect.signature(SandboxProvider.create)
        params = list(sig.parameters.keys())
        assert params == ["self", "spec"]

    def test_exec_signature_unchanged(self) -> None:
        sig = inspect.signature(SandboxProvider.exec)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "handle" in params
        assert "cmd" in params

    def test_destroy_signature_unchanged(self) -> None:
        sig = inspect.signature(SandboxProvider.destroy)
        params = list(sig.parameters.keys())
        assert params == ["self", "handle"]


@pytest.mark.unit
class TestImportGuard:
    """Verify harness imports no echelon internals (FR-SHIM-002b)."""

    def test_no_echelon_imports(self) -> None:
        """Harness modules must not import echelon internals."""
        harness_dir = Path(__file__).parent.parent.parent / "harness"
        violations = []

        for py_file in harness_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Check for echelon imports
                if "import echelon" in stripped or "from echelon" in stripped:
                    violations.append(f"{py_file.name}: {stripped}")

        assert not violations, (
            f"Echelon internal imports found in harness code (FR-SHIM-002b): "
            f"{violations}"
        )
