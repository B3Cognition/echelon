"""Error type hierarchy for Echelon delivery.

Error hierarchy (from contracts/sandbox-provider.md and contracts/gitops-interface.md):

    SandboxError (base for all sandbox errors)
    ├── SandboxCreationError — sandbox create() failed
    ├── SandboxExecError — sandbox exec() failed
    ├── SchemaViolationError — ExecResult/VerifyResult missing required fields
    ├── NotSupportedError — optional capability not available on this provider
    └── CredentialLeakError — git credentials detected in sandbox environment

    GitOpsError (base for all gitops errors)
    ├── GitOpsEscalation — push failed after retry, requires human intervention
    └── SelfTargetError — target repo is the harness repo itself
"""

from __future__ import annotations

from typing import Optional


class SandboxError(Exception):
    """Base class for all sandbox-related errors."""

    def __init__(self, message: str, *, cause: Optional[str] = None) -> None:
        self.cause = cause
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.cause:
            return f"{base} (cause: {self.cause})"
        return base


class SandboxCreationError(SandboxError):
    """Raised when sandbox creation fails.

    Possible causes: Docker daemon not running, image pull failure,
    resource limit rejection, network setup failure.
    """


class SandboxExecError(SandboxError):
    """Raised when command execution inside the sandbox fails unexpectedly.

    This is for infrastructure failures, NOT for commands that return non-zero
    exit codes (those are reported via ExecResult.exit_code).
    """


class SchemaViolationError(SandboxError):
    """Raised when ExecResult or VerifyResult is missing required fields.

    Per FR-SANDBOX-002c: every field in ExecResult must be present.
    Missing fields must raise this error, not silently default.
    """

    def __init__(self, message: str, *, field: Optional[str] = None) -> None:
        self.field = field
        super().__init__(message)

    def __str__(self) -> str:
        base = Exception.__str__(self)
        if self.field:
            return f"{base} (field: {self.field})"
        return base


class NotSupportedError(SandboxError):
    """Raised when an optional capability is invoked on a provider that
    does not support it.

    Per FR-SANDBOX-001a: optional methods (snapshot, restore, stream_exec,
    get_cost) raise this error on providers that lack the capability.
    """


class CredentialLeakError(SandboxError):
    """Raised when git credentials or host credential stores are detected
    in the sandbox environment.

    Per FR-SANDBOX-005 and FR-CREDS-001b: the sandbox must never contain
    git credentials. Detection at create() time blocks sandbox creation.
    """


class GitOpsError(Exception):
    """Base class for all gitops-related errors."""

    def __init__(self, message: str, *, command: Optional[str] = None) -> None:
        self.command = command
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.command:
            return f"{base} (command: {self.command})"
        return base


class GitOpsEscalation(GitOpsError):
    """Raised when a git push fails after retry and requires human intervention.

    Per FR-REPO-005b: on non-fast-forward, harness retries once with rebase.
    If the retry also fails, this error is raised to escalate to the user.
    """


class SelfTargetError(GitOpsError):
    """Raised when the target repo resolves to the harness repo itself.

    Per FR-INIT-001: the harness must detect and reject self-targeting
    at init time by comparing resolved paths and remote URLs.
    """
