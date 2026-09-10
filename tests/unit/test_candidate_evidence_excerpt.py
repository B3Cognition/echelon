from harness.candidate_evidence import _failure_excerpt


def test_failure_excerpt_keeps_early_timeout_and_cleanup_context() -> None:
    output = "\n".join(
        ["passing test output"] * 1200
        + [
            "[chromium] tests/concurrent-sessions.spec.ts:4 Test timeout of 60000ms exceeded.",
            "Error: Object with guid response@abc was not bound in the connection",
        ]
        + ["late framework warning"] * 1200
    )

    excerpt = _failure_excerpt(output, "")

    assert "Test timeout of 60000ms exceeded" in excerpt
    assert "Object with guid response@abc" in excerpt
    assert "late framework warning" in excerpt
    assert len(excerpt) <= 4_000
