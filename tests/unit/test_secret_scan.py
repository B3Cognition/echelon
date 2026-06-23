from pathlib import Path

from harness.secret_scan import scan_paths, scan_text


def test_clean_text_has_no_secret_findings() -> None:
    findings = scan_text(
        "API_TOKEN is read from the environment and never hardcoded.",
        path="README.md",
    )

    assert findings == []


def test_detects_github_token_pattern_without_storing_token_literal(tmp_path: Path) -> None:
    token = "ghp_" + ("A" * 36)
    secret_file = tmp_path / "config.txt"
    secret_file.write_text(f"GITHUB_TOKEN={token}\n", encoding="utf-8")

    result = scan_paths([secret_file])

    assert not result.ok
    assert result.findings[0].rule_id == "github-token"
    assert result.findings[0].path == str(secret_file)
    assert result.findings[0].line == 1


def test_detects_private_key_header_without_storing_key_literal() -> None:
    header = "-----BEGIN " + "PRIVATE KEY-----"
    findings = scan_text(f"{header}\nabc\n", path="id.key")

    assert len(findings) == 1
    assert findings[0].rule_id == "private-key"


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    binary_file = tmp_path / "image.bin"
    binary_file.write_bytes(b"\x00\x01\x02ghp_" + b"A" * 36)

    result = scan_paths([binary_file])

    assert result.ok
    assert result.findings == []
