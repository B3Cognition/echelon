"""Tests for error type hierarchy.

Validates:
- Correct inheritance chain
- Message formatting with optional fields
- All error types are importable from harness package
"""

import pytest

from harness.errors import (
    CredentialLeakError,
    GitOpsError,
    GitOpsEscalation,
    NotSupportedError,
    SandboxCreationError,
    SandboxError,
    SandboxExecError,
    SchemaViolationError,
    SelfTargetError,
)


@pytest.mark.unit
class TestSandboxErrorHierarchy:
    """Verify sandbox error inheritance chain."""

    def test_sandbox_creation_error_is_sandbox_error(self) -> None:
        err = SandboxCreationError("create failed")
        assert isinstance(err, SandboxError)
        assert isinstance(err, Exception)

    def test_sandbox_exec_error_is_sandbox_error(self) -> None:
        err = SandboxExecError("exec failed")
        assert isinstance(err, SandboxError)

    def test_schema_violation_error_is_sandbox_error(self) -> None:
        err = SchemaViolationError("missing field", field="exit_code")
        assert isinstance(err, SandboxError)
        assert err.field == "exit_code"
        assert "exit_code" in str(err)

    def test_not_supported_error_is_sandbox_error(self) -> None:
        err = NotSupportedError("snapshot not available")
        assert isinstance(err, SandboxError)

    def test_credential_leak_error_is_sandbox_error(self) -> None:
        err = CredentialLeakError("git credentials detected in env")
        assert isinstance(err, SandboxError)


@pytest.mark.unit
class TestGitOpsErrorHierarchy:
    """Verify gitops error inheritance chain."""

    def test_gitops_escalation_is_gitops_error(self) -> None:
        err = GitOpsEscalation("push failed after retry")
        assert isinstance(err, GitOpsError)
        assert isinstance(err, Exception)

    def test_self_target_error_is_gitops_error(self) -> None:
        err = SelfTargetError("target is self")
        assert isinstance(err, GitOpsError)


@pytest.mark.unit
class TestErrorMessageFormatting:
    """Verify error messages include optional context."""

    def test_sandbox_error_with_cause(self) -> None:
        err = SandboxError("failed", cause="Docker not running")
        assert "Docker not running" in str(err)
        assert "cause:" in str(err)

    def test_sandbox_error_without_cause(self) -> None:
        err = SandboxError("failed")
        assert str(err) == "failed"
        assert err.cause is None

    def test_schema_violation_with_field(self) -> None:
        err = SchemaViolationError("missing required field", field="exit_code")
        assert "field: exit_code" in str(err)

    def test_gitops_error_with_command(self) -> None:
        err = GitOpsError("clone failed", command="git clone --mirror")
        assert "git clone --mirror" in str(err)
        assert "command:" in str(err)

    def test_gitops_error_without_command(self) -> None:
        err = GitOpsError("failed")
        assert str(err) == "failed"
        assert err.command is None
