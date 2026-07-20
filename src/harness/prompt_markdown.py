"""Markdown prompt loading with YAML frontmatter metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised when PyYAML is unavailable
    yaml = None  # type: ignore[assignment]


class FrontmatterParseError(ValueError):
    """Raised when leading YAML frontmatter cannot be parsed safely."""


@dataclass(frozen=True)
class ParsedPromptMarkdown:
    body: str
    metadata: dict[str, Any]
    had_frontmatter: bool


_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<meta>[\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)"
)


def parse_prompt_markdown(
    content: str,
    *,
    source: str | Path = "<string>",
) -> ParsedPromptMarkdown:
    """Parse leading YAML frontmatter and return only Markdown body text."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return ParsedPromptMarkdown(body=content, metadata={}, had_frontmatter=False)

    raw_metadata = match.group("meta")
    metadata = _parse_frontmatter(raw_metadata, source=source)
    body = content[match.end():]
    return ParsedPromptMarkdown(body=body, metadata=metadata, had_frontmatter=True)


def read_prompt_markdown(path: Path) -> ParsedPromptMarkdown:
    """Read a Markdown prompt file and parse leading frontmatter metadata."""
    return parse_prompt_markdown(path.read_text(encoding="utf-8"), source=path)


def _parse_frontmatter(raw_metadata: str, *, source: str | Path) -> dict[str, Any]:
    last_error: Exception | None = None
    for candidate in (raw_metadata, _sanitize_unquoted_colon_scalars(raw_metadata)):
        try:
            loaded = _safe_load_frontmatter(candidate)
        except Exception as exc:
            last_error = exc
            continue
        if loaded is None:
            return {}
        if isinstance(loaded, dict):
            return dict(loaded)
        raise FrontmatterParseError(
            f"{source}: YAML frontmatter must be a mapping, got {type(loaded).__name__}"
        )
    raise FrontmatterParseError(f"{source}: failed to parse YAML frontmatter: {last_error}")


def _safe_load_frontmatter(raw_metadata: str) -> object:
    if not raw_metadata.strip():
        return {}
    if yaml is not None:
        return yaml.safe_load(raw_metadata)
    return _parse_simple_yaml_mapping(raw_metadata)


def _parse_simple_yaml_mapping(raw_metadata: str) -> dict[str, Any]:
    """Parse the limited YAML subset used by prompt frontmatter."""
    result: dict[str, Any] = {}
    lines = raw_metadata.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():
            raise ValueError(f"unexpected indented line: {line}")
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", line)
        if not match:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, raw_value = match.group(1), match.group(2).strip()
        if raw_value in {"|", "|-"}:
            block: list[str] = []
            while index < len(lines) and (
                not lines[index].strip() or lines[index][:1].isspace()
            ):
                block.append(
                    lines[index][2:]
                    if lines[index].startswith("  ")
                    else lines[index].lstrip()
                )
                index += 1
            result[key] = "\n".join(block)
            continue
        result[key] = _parse_simple_scalar(raw_value)
    return result


def _parse_simple_scalar(raw_value: str) -> Any:
    if raw_value == "":
        return ""
    if raw_value.startswith("["):
        if not raw_value.endswith("]"):
            raise ValueError(f"invalid inline list: {raw_value}")
        body = raw_value[1:-1].strip()
        if not body:
            return []
        return [_parse_simple_scalar(item.strip()) for item in body.split(",")]
    if raw_value[:1] == raw_value[-1:] and raw_value[:1] in {"'", '"'}:
        return raw_value[1:-1]
    lowered = raw_value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(raw_value)
    except ValueError:
        pass
    try:
        return float(raw_value)
    except ValueError:
        return raw_value


def _sanitize_unquoted_colon_scalars(raw_metadata: str) -> str:
    """Retry opencode-style frontmatter values containing unquoted colons."""
    result: list[str] = []
    for line in raw_metadata.splitlines():
        if line.strip().startswith("#") or line.strip() == "" or line[:1].isspace():
            result.append(line)
            continue
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$", line)
        if not match:
            result.append(line)
            continue
        value = match.group(2).strip()
        if (
            value in {"", ">", "|"}
            or value.startswith(('"', "'"))
            or ":" not in value
        ):
            result.append(line)
            continue
        result.extend([f"{match.group(1)}: |-", f"  {value}"])
    return "\n".join(result)
