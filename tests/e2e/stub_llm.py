"""Stub LLM for E2E testing.

Returns pre-baked responses based on prompt content patterns.
Tracks token usage per call for budget testing.

Per T047 task specification:
- Stub returns correct pre-baked diff for known fixture prompt
- Stub tracks token usage per call
- Stub raises on unknown prompt (not silent wrong answer)
- Can simulate convergence (correct fix) and non-convergence (wrong fix)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class UnknownPromptError(Exception):
    """Raised when the stub encounters a prompt it has no response for."""


class StubLLMResponse:
    """A pre-baked response from the stub LLM."""

    def __init__(
        self,
        content: str,
        tokens_used: int = 500,
        exit_code: int = 0,
    ) -> None:
        self.content = content
        self.tokens_used = tokens_used
        self.exit_code = exit_code


# === Pre-baked diffs ===

# Correct fix: changes `a * b` to `a / b` in calculator.py
CORRECT_DIVIDE_FIX = """--- a/src/calculator.py
+++ b/src/calculator.py
@@ -16,4 +16,4 @@ def divide(a: float, b: float) -> float:
-    return a * b  # should be a / b
+    return a / b
"""

# Wrong fix: changes the test assertion instead of fixing the code
WRONG_DIVIDE_FIX = """--- a/tests/test_calculator.py
+++ b/tests/test_calculator.py
@@ -21,4 +21,4 @@ def test_divide():
-    assert divide(10, 2) == 5  # Will fail: divide returns 10*2=20
+    assert divide(10, 2) == 20  # Adjusted to match implementation
"""

# Verify result: all tests pass (after correct fix)
VERIFY_PASSED = json.dumps({
    "passed": True,
    "failures": [],
    "duration_s": 2.5,
    "token_usage": 100,
})

# Verify result: divide test fails (before fix or wrong fix)
VERIFY_FAILED_DIVIDE = json.dumps({
    "passed": False,
    "failures": [
        {
            "category": "test",
            "id": "tests/test_calculator.py::test_divide",
            "error": "assert divide(10, 2) == 5\nAssertionError: assert 20 == 5",
        }
    ],
    "duration_s": 2.0,
    "token_usage": 100,
})

# Verify result: spec guard violation
VERIFY_SPEC_GUARD_VIOLATION = json.dumps({
    "passed": False,
    "failures": [
        {
            "category": "lint",
            "id": "spec-guard::constitution-p1",
            "error": "Constitution P1 violation: sandbox boundary crossed",
        }
    ],
    "duration_s": 1.0,
    "token_usage": 50,
})


class StubLLM:
    """Stub LLM that returns pre-baked responses.

    Modes:
    - converge_on_first: Returns correct fix on first feedback, verify passes.
    - converge_on_inner: Returns wrong fix, then correct fix on inner loop.
    - never_converge: Always returns wrong fix (for cap/budget testing).
    - same_failure_3x: Returns same wrong fix 3 times (for escalation testing).
    - spec_guard_fail: Returns fix that triggers spec guard violation.
    """

    def __init__(
        self,
        mode: str = "converge_on_first",
        tokens_per_call: int = 500,
    ) -> None:
        self.mode = mode
        self.tokens_per_call = tokens_per_call
        self.total_tokens_used = 0
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    def exec(self, cmd: str, **kwargs: Any) -> StubLLMResponse:
        """Execute a command and return a stub response.

        Routes based on command type (build/verify/feedback).
        """
        self.call_count += 1
        self.total_tokens_used += self.tokens_per_call

        call_record = {
            "call_number": self.call_count,
            "cmd": cmd,
            "tokens": self.tokens_per_call,
        }
        self.calls.append(call_record)

        if "build" in cmd:
            return self._handle_build(cmd)
        elif "verify" in cmd:
            return self._handle_verify(cmd)
        elif "feedback" in cmd:
            return self._handle_feedback(cmd)
        else:
            raise UnknownPromptError(f"Unknown command type: {cmd}")

    def _handle_build(self, cmd: str) -> StubLLMResponse:
        """Handle echelon build command — always succeeds."""
        return StubLLMResponse(
            content="Build completed successfully.",
            tokens_used=self.tokens_per_call,
            exit_code=0,
        )

    def _handle_verify(self, cmd: str) -> StubLLMResponse:
        """Handle echelon verify command — depends on mode and call count."""
        verify_calls = sum(1 for c in self.calls if "verify" in c["cmd"])

        if self.mode == "converge_on_first":
            # First verify after build fails, then after feedback fix passes
            if verify_calls <= 1:
                return StubLLMResponse(
                    content=VERIFY_FAILED_DIVIDE,
                    tokens_used=self.tokens_per_call,
                    exit_code=1,
                )
            else:
                return StubLLMResponse(
                    content=VERIFY_PASSED,
                    tokens_used=self.tokens_per_call,
                    exit_code=0,
                )

        elif self.mode == "converge_on_inner":
            # Fails until 3rd verify call
            if verify_calls <= 2:
                return StubLLMResponse(
                    content=VERIFY_FAILED_DIVIDE,
                    tokens_used=self.tokens_per_call,
                    exit_code=1,
                )
            else:
                return StubLLMResponse(
                    content=VERIFY_PASSED,
                    tokens_used=self.tokens_per_call,
                    exit_code=0,
                )

        elif self.mode in ("never_converge", "same_failure_3x"):
            return StubLLMResponse(
                content=VERIFY_FAILED_DIVIDE,
                tokens_used=self.tokens_per_call,
                exit_code=1,
            )

        elif self.mode == "spec_guard_fail":
            return StubLLMResponse(
                content=VERIFY_SPEC_GUARD_VIOLATION,
                tokens_used=self.tokens_per_call,
                exit_code=1,
            )

        else:
            raise UnknownPromptError(f"Unknown mode: {self.mode}")

    def _handle_feedback(self, cmd: str) -> StubLLMResponse:
        """Handle echelon feedback command — returns fix diff based on mode."""
        feedback_calls = sum(1 for c in self.calls if "feedback" in c["cmd"])

        if self.mode == "converge_on_first":
            return StubLLMResponse(
                content=CORRECT_DIVIDE_FIX,
                tokens_used=self.tokens_per_call,
                exit_code=0,
            )

        elif self.mode == "converge_on_inner":
            # Wrong fix first, correct fix on second feedback
            if feedback_calls <= 1:
                return StubLLMResponse(
                    content=WRONG_DIVIDE_FIX,
                    tokens_used=self.tokens_per_call,
                    exit_code=0,
                )
            else:
                return StubLLMResponse(
                    content=CORRECT_DIVIDE_FIX,
                    tokens_used=self.tokens_per_call,
                    exit_code=0,
                )

        elif self.mode in ("never_converge", "same_failure_3x"):
            return StubLLMResponse(
                content=WRONG_DIVIDE_FIX,
                tokens_used=self.tokens_per_call,
                exit_code=0,
            )

        elif self.mode == "spec_guard_fail":
            return StubLLMResponse(
                content=CORRECT_DIVIDE_FIX,
                tokens_used=self.tokens_per_call,
                exit_code=0,
            )

        else:
            raise UnknownPromptError(f"Unknown mode: {self.mode}")

    def reset(self) -> None:
        """Reset state for re-use."""
        self.total_tokens_used = 0
        self.call_count = 0
        self.calls.clear()


class StubSandboxProvider:
    """A mock SandboxProvider that uses StubLLM for exec calls.

    Bridges the gap between the real SandboxProvider interface and the stub LLM.
    Suitable for E2E tests that test the ralph loop without real Docker.
    """

    def __init__(self, stub_llm: StubLLM) -> None:
        from harness.provider import Capability, SandboxHandle, SandboxSpec

        self._stub = stub_llm
        self._created: Dict[str, bool] = {}
        self._destroyed: Dict[str, bool] = {}

    def create(self, spec: Any) -> Any:
        """Create a mock sandbox."""
        from harness.provider import SandboxHandle
        import uuid

        handle = SandboxHandle(
            id=f"stub-{uuid.uuid4().hex[:8]}",
            session_id=f"sess-{uuid.uuid4().hex[:8]}",
        )
        self._created[handle.id] = True
        return handle

    def exec(
        self,
        handle: Any,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> Any:
        """Execute command via stub LLM."""
        from harness.exec_result import ExecResult

        response = self._stub.exec(cmd)
        return ExecResult(
            exit_code=response.exit_code,
            stdout=response.content,
            stderr="",
            duration_ms=int(1000),
            resource_stats=None,
        )

    def write_file(self, handle: Any, path: str, content: bytes) -> None:
        """No-op for stub."""
        pass

    def read_file(self, handle: Any, path: str) -> bytes:
        """Return empty bytes for stub."""
        return b""

    def destroy(self, handle: Any) -> None:
        """Mark as destroyed."""
        self._destroyed[handle.id] = True

    def stream_exec(self, handle: Any, cmd: str, **kwargs: Any) -> Any:
        """Not implemented for stub."""
        raise NotImplementedError("stream_exec not available in stub")

    def get_cost(self, handle: Any) -> Any:
        """Return zero cost."""
        from harness.provider import MonetaryCost
        return MonetaryCost(usd=0.0)

    @property
    def capabilities(self) -> set:
        """Return empty capabilities."""
        return set()
