from harness.browser_runtime import (
    is_ambiguous_browser_runtime_failure,
    is_transient_browser_runtime_failure,
)


def test_timeout_followed_by_playwright_cleanup_error_requires_diagnosis() -> None:
    output = """
    Test timeout of 60000ms exceeded.
    Error: Object with guid response@abc was not bound in the connection
    """

    assert is_ambiguous_browser_runtime_failure(output, "") is True
    assert is_transient_browser_runtime_failure(output, "") is False


def test_actual_browser_crash_remains_a_transient_runtime_failure() -> None:
    output = "browserContext.newPage: Target crashed; session closed"

    assert is_ambiguous_browser_runtime_failure(output, "") is False
    assert is_transient_browser_runtime_failure(output, "") is True
