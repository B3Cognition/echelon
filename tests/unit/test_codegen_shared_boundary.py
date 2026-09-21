"""Behavioral tests for the retained codegen shared-utility boundary."""

from codegen.security.credential_patterns import CREDENTIAL_DENY_PATTERNS
from codegen.security.secret_scrubber import scrub_secrets


def test_secret_scrubber_owns_patterns_without_soar_import() -> None:
    """Removing the execution package must not remove credential scrubbing."""
    assert CREDENTIAL_DENY_PATTERNS
    assert scrub_secrets("token=abcdefghijklmnopqrstuvwxyz123456") == "[REDACTED]"
