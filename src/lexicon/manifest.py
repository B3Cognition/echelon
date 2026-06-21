"""Governance manifest: derive a structural artifact's section contract from its
template, and load the governance.artifacts config block."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_H2 = re.compile(r"^##\s+(?P<title>\S.*?)\s*$")


def _norm_heading(s: str) -> str:
    return s.strip().casefold().rstrip(".:").strip()


def required_sections(template_path: Path) -> list[str]:
    """Return the normalized H2 headings of a template, in document order."""
    try:
        text = template_path.read_text(errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        m = _H2.match(line)
        if m:
            out.append(_norm_heading(m.group("title")))
    return out


def load_governance(config_path: Path) -> dict:
    """Return the governance.artifacts mapping ({} when absent/unparseable)."""
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        return {}
    block = (data.get("governance") or {}).get("artifacts")
    return block if isinstance(block, dict) else {}
