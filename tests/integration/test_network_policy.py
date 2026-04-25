"""Network policy integration tests.

Per T009 acceptance criteria:
- Generated squid.conf blocks non-allowlisted FQDNs
- Generated squid.conf allows all 9 default FQDNs
- LLM API endpoints explicitly blocked
- Loopback allowed
- Blocked requests logged
- Additional FQDNs from config.yml injected correctly
- shellcheck passes on generate-squid-conf.sh

These tests validate the squid.conf generation logic without requiring
a running Squid instance. Docker-based integration tests that verify
actual network blocking are in the system test suite.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# Path to network directory
NETWORK_DIR = Path(__file__).parent.parent.parent / "network"
TEMPLATE_PATH = NETWORK_DIR / "squid.conf.template"
GENERATE_SCRIPT = NETWORK_DIR / "generate-squid-conf.sh"


# --- Fixture ---

@pytest.fixture
def generated_conf(tmp_path: Path) -> Path:
    """Generate a squid.conf from template with no additional FQDNs."""
    output_path = tmp_path / "squid.conf"
    result = subprocess.run(
        [str(GENERATE_SCRIPT), str(TEMPLATE_PATH), str(output_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"generate-squid-conf.sh failed: {result.stderr}"
    return output_path


@pytest.fixture
def generated_conf_with_extras(tmp_path: Path) -> Path:
    """Generate a squid.conf with additional FQDNs."""
    output_path = tmp_path / "squid.conf"
    result = subprocess.run(
        [
            str(GENERATE_SCRIPT),
            str(TEMPLATE_PATH),
            str(output_path),
            "custom.registry.io",
            "internal.nexus.corp.com",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"generate-squid-conf.sh failed: {result.stderr}"
    return output_path


# --- Tests ---

@pytest.mark.integration
class TestSquidConfGeneration:
    """Test squid.conf template and generation."""

    def test_template_exists(self) -> None:
        """Verify the squid.conf.template exists."""
        assert TEMPLATE_PATH.exists(), f"Template not found: {TEMPLATE_PATH}"

    def test_generate_script_exists(self) -> None:
        """Verify generate-squid-conf.sh exists and is executable."""
        assert GENERATE_SCRIPT.exists(), f"Script not found: {GENERATE_SCRIPT}"
        assert os.access(str(GENERATE_SCRIPT), os.X_OK), "Script is not executable"

    def test_default_deny_all(self, generated_conf: Path) -> None:
        """FR-NETWORK-001a: default deny-all policy."""
        content = generated_conf.read_text()
        assert "http_access deny all" in content

    def test_default_allowlist_9_fqdns(self, generated_conf: Path) -> None:
        """FR-NETWORK-001b: all 9 default package registries allowed."""
        content = generated_conf.read_text()
        expected_fqdns = [
            "registry.npmjs.org",
            "pypi.org",
            "files.pythonhosted.org",
            "proxy.golang.org",
            "crates.io",
            "static.crates.io",
            "repo1.maven.org",
            "playwright.azureedge.net",
            "cdn.playwright.dev",
        ]
        for fqdn in expected_fqdns:
            assert f"acl allowlist dstdomain {fqdn}" in content, (
                f"Missing default allowlist entry: {fqdn}"
            )

    def test_llm_apis_blocked(self, generated_conf: Path) -> None:
        """FR-SANDBOX-004: LLM API endpoints explicitly blocked."""
        content = generated_conf.read_text()
        assert "acl llm_apis dstdomain api.anthropic.com" in content
        assert "acl llm_apis dstdomain api.openai.com" in content
        assert "http_access deny llm_apis" in content
        # Verify deny llm_apis comes BEFORE allow rules
        deny_llm_pos = content.index("http_access deny llm_apis")
        allow_pos = content.index("http_access allow allowlist")
        assert deny_llm_pos < allow_pos, (
            "LLM API deny rule must come before allowlist allow rule"
        )

    def test_loopback_allowed(self, generated_conf: Path) -> None:
        """FR-NETWORK-002: loopback unrestricted."""
        content = generated_conf.read_text()
        assert "acl loopback dst 127.0.0.0/8" in content
        assert "http_access allow loopback" in content

    def test_access_logging_enabled(self, generated_conf: Path) -> None:
        """FR-NETWORK-001b: blocked requests logged for debugging."""
        content = generated_conf.read_text()
        assert "access_log" in content

    def test_additional_fqdns_injected(self, generated_conf_with_extras: Path) -> None:
        """Additional FQDNs from config.yml allowlist injected."""
        content = generated_conf_with_extras.read_text()
        assert "acl allowlist dstdomain custom.registry.io" in content
        assert "acl allowlist dstdomain internal.nexus.corp.com" in content


@pytest.mark.integration
class TestSquidConfEdgeCases:
    """Edge case tests for squid.conf generation."""

    def test_missing_template_fails(self, tmp_path: Path) -> None:
        """Generation fails gracefully with missing template."""
        output_path = tmp_path / "squid.conf"
        result = subprocess.run(
            [str(GENERATE_SCRIPT), "/nonexistent/template", str(output_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_no_additional_fqdns(self, generated_conf: Path) -> None:
        """Generation succeeds with no additional FQDNs."""
        content = generated_conf.read_text()
        # Placeholder should be removed
        assert "{{ADDITIONAL_ALLOWLIST}}" not in content
        # Default entries still present
        assert "acl allowlist dstdomain pypi.org" in content
