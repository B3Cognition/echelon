"""Unit tests for image security — digest pinning and vulnerability scanning.

Tests use mocks since trivy/docker may not be available.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

import pytest

from harness.image_security import (
    validate_digest_pin,
    scan_image,
    DigestMismatchError,
    VulnerabilityScanResult,
)


class TestDigestPinValidation:
    """Tests for image digest pin validation."""

    def test_no_pin_passes(self):
        """No digest pin set -> passes."""
        assert validate_digest_pin("alpine:latest", None) is True

    @patch("harness.image_security.subprocess.run")
    def test_matching_digest_passes(self, mock_run):
        """Matching digest passes validation."""
        mock_run.return_value = MagicMock(
            stdout="alpine@sha256:abc123\n",
            returncode=0,
        )
        assert validate_digest_pin("alpine:latest", "sha256:abc123") is True

    @patch("harness.image_security.subprocess.run")
    def test_mismatched_digest_blocks(self, mock_run):
        """Mismatched digest raises DigestMismatchError."""
        mock_run.return_value = MagicMock(
            stdout="alpine@sha256:different\n",
            returncode=0,
        )
        with pytest.raises(DigestMismatchError):
            validate_digest_pin("alpine:latest", "sha256:expected")


class TestVulnerabilityScan:
    """Tests for vulnerability scanning."""

    @patch("harness.image_security.subprocess.run")
    def test_trivy_command_constructed(self, mock_run):
        """Trivy command constructed correctly."""
        mock_run.return_value = MagicMock(
            stdout='{"Results": []}',
            stderr="",
            returncode=0,
        )
        result = scan_image("alpine:latest", scanner="trivy")
        assert result.passed is True
        assert result.scanner == "trivy"

        # Verify trivy was called
        call_args = mock_run.call_args[0][0]
        assert "trivy" in call_args

    @patch("harness.image_security.subprocess.run")
    def test_severity_threshold_critical_blocks(self, mock_run):
        """CRITICAL severity blocks when threshold is CRITICAL."""
        mock_run.return_value = MagicMock(
            stdout='{"Results": [{"Vulnerabilities": [{"Severity": "CRITICAL"}]}]}',
            stderr="",
            returncode=0,
        )
        result = scan_image("alpine:latest", scanner="trivy", severity_threshold="CRITICAL")
        assert result.passed is False
        assert result.critical_count == 1

    def test_scan_disabled_when_trivy_absent(self):
        """Scanning disabled by default (no error when trivy absent)."""
        with patch("harness.image_security.subprocess.run", side_effect=FileNotFoundError):
            result = scan_image("alpine:latest", scanner="trivy")
            assert result.passed is True
