"""
spec_memory_miner.py — Mine Echelon spec memory into MemPalace drawers.

Spec 025: Requirements Memory Store
FR-RM-001: Parse markdown/Jira/Confluence sources and chunk by requirement ID.
FR-RM-002: Write each requirement as a MemPalace drawer (wing=project,
           room=requirement category, drawer=individual FR/NFR/AC).
FR-RM-003: Return MineResult with counts and drawer IDs for traceability.
FR-RM-004: Non-fatal — miner failures degrade gracefully; pipeline continues.

ADR-005: Requirement ID regex is intentionally broad (FR-*, NFR-*, AC-*, ADR-*,
         US-*). Unknown requirement formats are written to room=uncategorised.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# SEC-025 FIX-1: Import secret scrubber — applied to all content before ChromaDB writes.
try:
    from codegen.security.secret_scrubber import scrub_secrets
except ImportError:
    from src.codegen.security.secret_scrubber import scrub_secrets  # type: ignore

try:
    from codegen.memory.collision import check_wing_collision
    from codegen.memory.context import MemPalaceContext
except ImportError:
    from src.codegen.memory.collision import check_wing_collision  # type: ignore
    from src.codegen.memory.context import MemPalaceContext  # type: ignore

logger = logging.getLogger(__name__)

# Requirement ID patterns (ADR-005)
_REQ_ID_PATTERN = re.compile(
    r"^(?P<id>(?:FR|NFR|AC|ADR|US|CQ-ISC|SEC|MSR|PERF|REL)-[\w-]+)\s*[:\-—]?\s*(?P<text>.+)",
    re.MULTILINE,
)

_REQ_PREFIX_PATTERN = r"(?:FR|NFR|AC|ADR|US|CQ-ISC|SEC|MSR|PERF|REL|BUG)"

_ECHELON_BULLET_BOLD_REQ_PATTERN = re.compile(
    rf"^\s*[-*]\s+\*\*(?P<id>{_REQ_PREFIX_PATTERN}-[\w-]+)"
    r"(?:\s*\([^)]*\))?\*\*\s*[:\-—]?\s*(?P<text>.+)"
)

_ECHELON_BOLD_REQ_PATTERN = re.compile(
    rf"^\s*\*\*(?P<id>{_REQ_PREFIX_PATTERN}-[\w-]+)"
    r"(?:\s*\([^)]*\))?\*\*\s*[:\-—]?\s*(?P<text>.+)"
)

_LINKED_REQ_ID_PATTERN = re.compile(rf"\b{_REQ_PREFIX_PATTERN}-[\w-]+\b")
_TABLE_REQ_ID_CELL_PATTERN = re.compile(
    rf"^\s*\*\*(?P<id>{_REQ_PREFIX_PATTERN}-[\w-]+)"
    r"(?:\s*\([^)]*\))?\*\*\s*$|"
    rf"^\s*(?P<plain_id>{_REQ_PREFIX_PATTERN}-[\w-]+)"
    r"(?:\s*\([^)]*\))?\s*$"
)

# Heading pattern — used to detect section context
_HEADING_PATTERN = re.compile(r"^#{1,4}\s+(.+)", re.MULTILINE)

# Map requirement ID prefix → MemPalace room name
_ID_TO_ROOM: dict[str, str] = {
    "FR": "functional-requirements",
    "NFR": "non-functional-requirements",
    "AC": "acceptance-criteria",
    "ADR": "domain-decisions",
    "US": "user-stories",
    "CQ-ISC": "quality-constraints",
    "SEC": "security-requirements",
    "MSR": "measurement-requirements",
    "PERF": "performance-requirements",
    "REL": "reliability-requirements",
    "BUG": "bugs",
}

# Pattern for inline *Acceptance:* / *AC:* blocks that follow an FR
_ACCEPTANCE_PATTERN = re.compile(
    r"\*(?:Acceptance|AC)\*\s*:\s*(?P<text>.+?)(?=\n\n|\n\*\*FR-|\n\*\*NFR-|\Z)",
    re.DOTALL,
)


@dataclass
class MinedRequirement:
    req_id: str
    room: str
    content: str
    source: str  # file path or Jira/Confluence URL


@dataclass(frozen=True)
class CanonicalRequirementDrawerPlan:
    """One canonical requirement row planned without backend access."""

    drawer_id: str
    requirement_id: str
    room: str
    source: str
    artifact_hash: str
    canonical_spec_sha256: str
    requirement_content_sha256: str


@dataclass
class MineResult:
    wing: str
    total: int
    written: int
    skipped: int
    failed: int
    already_present: int = 0
    drifted: int = 0
    unavailable: int = 0
    requirements: list[MinedRequirement] = field(default_factory=list)
    drawer_ids: list[str] = field(default_factory=list)
    expected_drawer_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _prefix_to_room(req_id: str) -> str:
    """Map a requirement ID to the correct MemPalace room name."""
    for prefix, room in _ID_TO_ROOM.items():
        if req_id.upper().startswith(prefix):
            return room
    return "uncategorised"


# Filename stem → room (used when a spec file has no explicit FR-*/NFR-* IDs)
_FILENAME_ROOM_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("spec", "requirements", "gamelens-ui-spec", "parity-checklist"),
        "functional-requirements",
    ),
    (
        ("tasks", "plan", "critical-path", "mvp-scope", "prioritization"),
        "functional-requirements",
    ),
    (
        ("quality-gates", "test-strategy", "coverage-map"),
        "quality-constraints",
    ),
    (
        ("threat-model",),
        "security-requirements",
    ),
    (
        ("data-model", "estimates"),
        "domain-decisions",
    ),
]

_SUPPORT_ARTIFACT_ROOM_RULES: list[tuple[tuple[str, ...], str]] = [
    (("plan", "critical-path", "mvp-scope", "prioritization"), "implementation-plan"),
    (("tasks",), "implementation-tasks"),
    (("coverage-map",), "traceability"),
    (("research",), "research-findings"),
    (("issues", "fulfillment-gaps", "contradictions-and-gaps"), "risks-and-gaps"),
    (("quality-gates", "test-strategy", "test-architecture"), "quality-constraints"),
]


def _match_requirement_definition(line: str) -> re.Match[str] | None:
    """Match canonical requirement definitions in historical Echelon markdown."""
    return (
        _REQ_ID_PATTERN.match(line)
        or _ECHELON_BULLET_BOLD_REQ_PATTERN.match(line)
        or _ECHELON_BOLD_REQ_PATTERN.match(line)
    )


def _filename_to_room(source: str) -> str:
    """
    Infer MemPalace room from the spec file's path when no req IDs are found.

    Checks directory name first, then filename stem.
    """
    path = Path(source)
    stem = path.stem.lower()
    parent = path.parent.name.lower()

    # Directory-based rules (take precedence over filename)
    if parent == "contracts":
        return "functional-requirements"
    if parent == "adrs":
        return "domain-decisions"

    for stems, room in _FILENAME_ROOM_RULES:
        if stem in stems:
            return room

    return "uncategorised"


def _support_artifact_room(source: str) -> str:
    stem = Path(source).stem.lower()
    for stems, room in _SUPPORT_ARTIFACT_ROOM_RULES:
        if stem in stems:
            return room
    return "uncategorised"


def _split_markdown_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_markdown_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _extract_acceptance_blocks(
    text: str, source: str
) -> list[MinedRequirement]:
    """
    Second-pass extraction: find inline *Acceptance:* blocks that follow FR lines.

    Each block is written as AC-<FR-ID>-<N> in the acceptance-criteria room,
    paired with the FR it verifies so IMPLEMENTER can query ACs by FR ID.
    """
    requirements: list[MinedRequirement] = []
    lines = text.splitlines()
    current_fr: str | None = None
    ac_index = 0

    for i, line in enumerate(lines):
        # Track current FR context
        fr_match = _match_requirement_definition(line)
        if fr_match and fr_match.group("id").startswith("FR"):
            current_fr = fr_match.group("id")
            ac_index = 0
            continue

        # Detect *Acceptance:* or *AC:* lines
        stripped = line.strip()
        if stripped.lower().startswith(("*acceptance:*", "*ac:*")):
            # Collect multi-line acceptance text
            colon_pos = stripped.index(":*") + 2
            body_lines = [stripped[colon_pos:].strip()]
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if (
                    not next_line
                    or _match_requirement_definition(next_line)
                    or next_line.startswith("#")
                ):
                    break
                body_lines.append(next_line)
                j += 1

            body = " ".join(b for b in body_lines if b)
            if not body:
                continue

            fr_tag = current_fr or "UNKNOWN"
            req_id = f"AC-{fr_tag}-{ac_index:02d}"
            content = (
                f"{req_id}: [{fr_tag}] {body} "
                f"[source: {Path(source).name}]"
            )
            requirements.append(MinedRequirement(
                req_id=req_id,
                room="acceptance-criteria",
                content=content,
                source=source,
            ))
            ac_index += 1

    return requirements


def _parse_markdown(text: str, source: str) -> list[MinedRequirement]:
    """
    Extract individual requirements from a markdown document.

    Strategy:
    1. Match lines that start with a known requirement ID pattern.
    2. Accumulate continuation lines (indented or part of a list item) as body.
    3. Fall back to heading-chunked paragraphs for documents with no IDs.
    """
    requirements: list[MinedRequirement] = []
    lines = text.splitlines()
    i = 0
    table_header: list[str] | None = None

    while i < len(lines):
        line = lines[i]
        cells = _split_markdown_table_row(line)
        if cells is not None:
            if _is_markdown_table_separator(cells):
                i += 1
                continue
            if not table_header:
                table_header = cells
                i += 1
                continue
            if table_header and table_header[0].strip().lower() == "id":
                req_match = _TABLE_REQ_ID_CELL_PATTERN.match(cells[0])
                if req_match:
                    req_id = req_match.group("id") or req_match.group("plain_id")
                    body = " ".join(cell for cell in cells[1:] if cell).strip()
                    if body:
                        content = f"{req_id}: {body}"
                        requirements.append(
                            MinedRequirement(
                                req_id=req_id,
                                room=_prefix_to_room(req_id),
                                content=content,
                                source=source,
                            )
                        )
                i += 1
                continue
        else:
            table_header = None

        m = _match_requirement_definition(line)
        if m:
            req_id = m.group("id")
            body_lines = [m.group("text").strip()]
            # Accumulate continuation lines
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                if _match_requirement_definition(next_line):
                    break
                if next_line.startswith(("  ", "\t", "   ")):
                    body_lines.append(next_line.strip())
                    j += 1
                elif next_line == "":
                    j += 1
                    break
                else:
                    break
            i = j
            content = f"{req_id}: " + " ".join(body_lines)
            room = _prefix_to_room(req_id)
            requirements.append(MinedRequirement(req_id=req_id, room=room, content=content, source=source))
        else:
            i += 1

    # Second pass: extract inline *Acceptance:* blocks (always runs, independent of ID pass)
    requirements.extend(_extract_acceptance_blocks(text, source))

    # Fallback: no IDs found — chunk by heading, infer room from filename
    if not requirements:
        fallback_room = _filename_to_room(source)
        current_heading = "general"
        current_lines: list[str] = []
        chunk_index = 0
        for line in lines:
            hm = _HEADING_PATTERN.match(line)
            if hm:
                if current_lines:
                    chunk_text = "\n".join(current_lines).strip()
                    if chunk_text:
                        req_id = f"DOC-{chunk_index:03d}"
                        requirements.append(MinedRequirement(
                            req_id=req_id,
                            room=fallback_room,
                            content=f"{current_heading}: {chunk_text}",
                            source=source,
                        ))
                        chunk_index += 1
                current_heading = hm.group(1)
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            chunk_text = "\n".join(current_lines).strip()
            if chunk_text:
                req_id = f"DOC-{chunk_index:03d}"
                requirements.append(MinedRequirement(
                    req_id=req_id,
                    room=fallback_room,
                    content=f"{current_heading}: {chunk_text}",
                    source=source,
                ))

    return requirements


def _parse_support_markdown(text: str, source: str) -> list[MinedRequirement]:
    """Chunk selected non-spec artifacts as contextual memory."""
    room = _support_artifact_room(source)
    return _parse_context_markdown(
        text,
        source=source,
        room=room,
        req_prefix="CTX",
        content_suffix=True,
        id_stem=None,
    )


def _parse_context_markdown(
    text: str,
    *,
    source: str,
    room: str,
    req_prefix: str,
    content_suffix: bool,
    id_stem: str | None,
) -> list[MinedRequirement]:
    """Chunk a contextual artifact by headings using stable synthetic IDs."""
    stem = (
        id_stem
        or re.sub(r"[^A-Za-z0-9]+", "-", Path(source).stem).strip("-")
        or "artifact"
    )
    requirements: list[MinedRequirement] = []
    current_heading = Path(source).name
    current_lines: list[str] = []
    chunk_index = 0

    def flush() -> None:
        nonlocal chunk_index, current_lines
        chunk_text = "\n".join(current_lines).strip()
        if not chunk_text:
            current_lines = []
            return
        linked_ids = sorted(set(_LINKED_REQ_ID_PATTERN.findall(chunk_text)))
        linked_text = ", ".join(linked_ids) if linked_ids else "none"
        req_id = f"{req_prefix}-{stem}-{chunk_index:03d}"
        content = f"{req_id}: {current_heading}: {chunk_text}"
        if content_suffix:
            content = f"{content} [linked_requirements: {linked_text}]"
        requirements.append(
            MinedRequirement(
                req_id=req_id,
                room=room,
                content=content,
                source=source,
            )
        )
        chunk_index += 1
        current_lines = []

    for line in text.splitlines():
        heading = _HEADING_PATTERN.match(line)
        if heading:
            flush()
            current_heading = heading.group(1).strip()
        else:
            current_lines.append(line)
    flush()
    return requirements


def _parse_re_artifact_markdown(
    text: str,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
) -> list[MinedRequirement]:
    room = artifact_metadata.get("room")
    if not isinstance(room, str) or not room:
        room = "re-workspace-context"
    return _parse_context_markdown(
        text,
        source=source,
        room=room,
        req_prefix="RE",
        content_suffix=False,
        id_stem=re.sub(r"[^A-Za-z0-9]+", "-", source).strip("-") or None,
    )


def _parse_spec_evidence_artifact_markdown(
    text: str,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
) -> list[MinedRequirement]:
    room = artifact_metadata.get("room")
    if not isinstance(room, str) or not room:
        room = "spec-evidence"
    return _parse_context_markdown(
        text,
        source=source,
        room=room,
        req_prefix="EVID",
        content_suffix=False,
        id_stem=re.sub(r"[^A-Za-z0-9]+", "-", source).strip("-") or None,
    )


def _parse_jira_issue(issue: dict, source: str) -> Optional[MinedRequirement]:
    """
    Extract a MinedRequirement from a Jira issue dict.
    Expected keys: key, summary, description, issuetype.
    """
    key = issue.get("key", "UNKNOWN")
    summary = issue.get("summary", "")
    description = issue.get("description", "") or ""
    issue_type = (issue.get("issuetype") or "").upper()

    room_map = {
        "STORY": "user-stories",
        "BUG": "uncategorised",
        "EPIC": "functional-requirements",
        "TASK": "functional-requirements",
        "SUB-TASK": "functional-requirements",
    }
    room = room_map.get(issue_type, "uncategorised")
    content = f"{key}: {summary}. {description[:500]}".strip()
    return MinedRequirement(req_id=key, room=room, content=content, source=source)


def _canonical_requirements_from_bytes(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
) -> tuple[str, list[MinedRequirement]]:
    if (
        type(content) is not bytes
        or type(source) is not str
        or not source
        or type(artifact_metadata) is not dict
        or artifact_metadata.get("canonical") is not True
    ):
        raise ValueError("invalid canonical mining input")
    digest = hashlib.sha256(content).hexdigest()
    if artifact_metadata.get("artifact_hash") != f"sha256:{digest}":
        raise ValueError("canonical spec digest mismatch")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("canonical spec is not UTF-8") from exc
    return digest, _parse_markdown(text, source=source)


def _canonical_support_from_bytes(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
) -> tuple[str, list[MinedRequirement]]:
    if (
        type(content) is not bytes
        or type(source) is not str
        or not source
        or type(artifact_metadata) is not dict
        or artifact_metadata.get("canonical") is not True
        or artifact_metadata.get("scope") != "canonical-support"
    ):
        raise ValueError("invalid canonical support mining input")
    digest = hashlib.sha256(content).hexdigest()
    if artifact_metadata.get("artifact_hash") != f"sha256:{digest}":
        raise ValueError("canonical support digest mismatch")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("canonical support artifact is not UTF-8") from exc
    return digest, _parse_support_markdown(text, source=source)


def _re_artifact_from_bytes(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
) -> tuple[str, list[MinedRequirement]]:
    if (
        type(content) is not bytes
        or type(source) is not str
        or not source
        or type(artifact_metadata) is not dict
        or artifact_metadata.get("canonical") is not True
        or artifact_metadata.get("artifact_kind") != "reverse-engineering"
        or artifact_metadata.get("scope") != "reverse-engineering"
    ):
        raise ValueError("invalid reverse-engineering mining input")
    digest = hashlib.sha256(content).hexdigest()
    if artifact_metadata.get("artifact_hash") != f"sha256:{digest}":
        raise ValueError("reverse-engineering artifact digest mismatch")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("reverse-engineering artifact is not UTF-8") from exc
    return digest, _parse_re_artifact_markdown(
        text,
        source=source,
        artifact_metadata=artifact_metadata,
    )


def _spec_evidence_artifact_from_bytes(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
) -> tuple[str, list[MinedRequirement]]:
    if (
        type(content) is not bytes
        or type(source) is not str
        or not source
        or type(artifact_metadata) is not dict
        or artifact_metadata.get("canonical") is not True
        or artifact_metadata.get("artifact_kind") != "spec-evidence"
        or artifact_metadata.get("scope") != "spec-evidence"
    ):
        raise ValueError("invalid spec evidence mining input")
    digest = hashlib.sha256(content).hexdigest()
    if artifact_metadata.get("artifact_hash") != f"sha256:{digest}":
        raise ValueError("spec evidence artifact digest mismatch")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("spec evidence artifact is not UTF-8") from exc
    return digest, _parse_spec_evidence_artifact_markdown(
        text,
        source=source,
        artifact_metadata=artifact_metadata,
    )


def plan_canonical_requirement_drawers(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
    wing: str,
) -> list[CanonicalRequirementDrawerPlan]:
    """Plan structured canonical rows through the shared parser and ID logic."""
    if type(wing) is not str or not wing:
        raise ValueError("invalid canonical mining input")
    digest, requirements = _canonical_requirements_from_bytes(
        content,
        source=source,
        artifact_metadata=artifact_metadata,
    )
    from codegen.memory.mempalace_writer import (
        deterministic_requirement_drawer_id,
    )

    result: list[CanonicalRequirementDrawerPlan] = []
    for requirement in requirements:
        scrubbed_content = scrub_secrets(requirement.content)
        result.append(
            CanonicalRequirementDrawerPlan(
                drawer_id=deterministic_requirement_drawer_id(
                    wing=wing,
                    room=requirement.room,
                    spec_sha256=digest,
                    requirement_id=requirement.req_id,
                    content=scrubbed_content,
                ),
                requirement_id=requirement.req_id,
                room=requirement.room,
                source=requirement.source,
                artifact_hash=f"sha256:{digest}",
                canonical_spec_sha256=digest,
                requirement_content_sha256=hashlib.sha256(
                    scrubbed_content.encode("utf-8")
                ).hexdigest(),
            )
        )
    if len({row.drawer_id for row in result}) != len(result):
        raise ValueError("deterministic drawer identity collision")
    return result


def plan_canonical_support_drawers(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
    wing: str,
) -> list[CanonicalRequirementDrawerPlan]:
    """Plan deterministic contextual rows for selected canonical artifacts."""
    if type(wing) is not str or not wing:
        raise ValueError("invalid canonical support mining input")
    digest, requirements = _canonical_support_from_bytes(
        content,
        source=source,
        artifact_metadata=artifact_metadata,
    )
    from codegen.memory.mempalace_writer import (
        deterministic_requirement_drawer_id,
    )

    result: list[CanonicalRequirementDrawerPlan] = []
    for requirement in requirements:
        scrubbed_content = scrub_secrets(requirement.content)
        result.append(
            CanonicalRequirementDrawerPlan(
                drawer_id=deterministic_requirement_drawer_id(
                    wing=wing,
                    room=requirement.room,
                    spec_sha256=digest,
                    requirement_id=requirement.req_id,
                    content=scrubbed_content,
                ),
                requirement_id=requirement.req_id,
                room=requirement.room,
                source=requirement.source,
                artifact_hash=f"sha256:{digest}",
                canonical_spec_sha256=digest,
                requirement_content_sha256=hashlib.sha256(
                    scrubbed_content.encode("utf-8")
                ).hexdigest(),
            )
        )
    if len({row.drawer_id for row in result}) != len(result):
        raise ValueError("deterministic drawer identity collision")
    return result


def plan_re_artifact_drawers(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
    wing: str,
) -> list[CanonicalRequirementDrawerPlan]:
    """Plan deterministic contextual rows for curated RE artifacts."""
    if type(wing) is not str or not wing:
        raise ValueError("invalid reverse-engineering mining input")
    digest, requirements = _re_artifact_from_bytes(
        content,
        source=source,
        artifact_metadata=artifact_metadata,
    )
    from codegen.memory.mempalace_writer import (
        deterministic_requirement_drawer_id,
    )

    result: list[CanonicalRequirementDrawerPlan] = []
    for requirement in requirements:
        scrubbed_content = scrub_secrets(requirement.content)
        result.append(
            CanonicalRequirementDrawerPlan(
                drawer_id=deterministic_requirement_drawer_id(
                    wing=wing,
                    room=requirement.room,
                    spec_sha256=digest,
                    requirement_id=requirement.req_id,
                    content=scrubbed_content,
                ),
                requirement_id=requirement.req_id,
                room=requirement.room,
                source=requirement.source,
                artifact_hash=f"sha256:{digest}",
                canonical_spec_sha256=digest,
                requirement_content_sha256=hashlib.sha256(
                    scrubbed_content.encode("utf-8")
                ).hexdigest(),
            )
        )
    if len({row.drawer_id for row in result}) != len(result):
        raise ValueError("deterministic drawer identity collision")
    return result


def plan_spec_evidence_artifact_drawers(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
    wing: str,
) -> list[CanonicalRequirementDrawerPlan]:
    """Plan deterministic contextual rows for curated spec evidence artifacts."""
    if type(wing) is not str or not wing:
        raise ValueError("invalid spec evidence mining input")
    digest, requirements = _spec_evidence_artifact_from_bytes(
        content,
        source=source,
        artifact_metadata=artifact_metadata,
    )
    from codegen.memory.mempalace_writer import (
        deterministic_requirement_drawer_id,
    )

    result: list[CanonicalRequirementDrawerPlan] = []
    for requirement in requirements:
        scrubbed_content = scrub_secrets(requirement.content)
        result.append(
            CanonicalRequirementDrawerPlan(
                drawer_id=deterministic_requirement_drawer_id(
                    wing=wing,
                    room=requirement.room,
                    spec_sha256=digest,
                    requirement_id=requirement.req_id,
                    content=scrubbed_content,
                ),
                requirement_id=requirement.req_id,
                room=requirement.room,
                source=requirement.source,
                artifact_hash=f"sha256:{digest}",
                canonical_spec_sha256=digest,
                requirement_content_sha256=hashlib.sha256(
                    scrubbed_content.encode("utf-8")
                ).hexdigest(),
            )
        )
    if len({row.drawer_id for row in result}) != len(result):
        raise ValueError("deterministic drawer identity collision")
    return result


def plan_canonical_requirement_drawer_ids(
    content: bytes,
    *,
    source: str,
    artifact_metadata: dict[str, Any],
    wing: str,
) -> list[str]:
    """Plan canonical IDs without constructing or accessing a backend."""
    return [
        row.drawer_id
        for row in plan_canonical_requirement_drawers(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            wing=wing,
        )
    ]


class SpecMemoryMiner:
    """
    Mines requirement sources and writes them as MemPalace drawers.

    Supports:
      - Markdown / plain-text spec files (FR-RM-001)
      - Jira issue dicts (for programmatic use with Jira MCP tool output)
      - Confluence page text (treated as markdown)

    Usage:
        ctx = MemPalaceContext.from_project(project_dir, run_id="mine-run")
        miner = SpecMemoryMiner(ctx, project_dir=project_dir)
        result = miner.mine_file(Path("spec.md"))
    """

    def __init__(self, ctx: MemPalaceContext, project_dir: Path = Path(".")) -> None:
        self.ctx = ctx
        self.wing = ctx.wing
        self.run_id = ctx.run_id
        self.project_dir = project_dir
        self._writer: Optional[object] = None  # MemPalaceWriter, lazy-loaded
        self._collision_checked: bool = False

    def _get_writer(self):
        if self._writer is None:
            try:
                from codegen.memory.mempalace_writer import MemPalaceWriter
            except ImportError:
                from src.codegen.memory.mempalace_writer import MemPalaceWriter  # type: ignore
            self._writer = MemPalaceWriter(self.ctx)
        return self._writer

    def mine_file(self, path: Path, artifact_metadata: dict[str, Any] | None = None) -> MineResult:
        """
        Mine a single markdown/text spec file.

        FR-RM-001: Parse by requirement ID.
        FR-RM-004: Non-fatal on read or write failures.
        """
        result = MineResult(wing=self.wing, total=0, written=0, skipped=0, failed=0)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"Cannot read {path}: {exc}"
            logger.warning("[SpecMemoryMiner] %s", msg)
            result.errors.append(msg)
            return result

        reqs = _parse_markdown(text, source=str(path))
        result.total = len(reqs)
        result.requirements = reqs
        self._write_requirements(reqs, result, artifact_metadata=artifact_metadata)
        logger.info(
            "[SpecMemoryMiner] %s: %d mined, %d written, %d failed",
            path.name, result.total, result.written, result.failed,
        )
        return result

    def _canonical_requirements_from_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> tuple[str, list[MinedRequirement]]:
        return _canonical_requirements_from_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )

    def plan_canonical_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[CanonicalRequirementDrawerPlan]:
        """Compute structured expected rows without reading or writing."""
        return plan_canonical_requirement_drawers(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            wing=self.wing,
        )

    def plan_canonical_support_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[CanonicalRequirementDrawerPlan]:
        """Compute structured support-context rows without reading or writing."""
        return plan_canonical_support_drawers(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            wing=self.wing,
        )

    def plan_re_artifact_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[CanonicalRequirementDrawerPlan]:
        """Compute structured RE-context rows without reading or writing."""
        return plan_re_artifact_drawers(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            wing=self.wing,
        )

    def plan_spec_evidence_artifact_rows(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[CanonicalRequirementDrawerPlan]:
        """Compute structured spec-evidence rows without reading or writing."""
        return plan_spec_evidence_artifact_drawers(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            wing=self.wing,
        )

    def open_collection_read_only(self) -> object:
        """Open existing storage for inspection without creating it."""
        writer = self._get_writer()
        opener = getattr(writer, "get_collection_read_only", None)
        if not callable(opener):
            raise RuntimeError(
                "installed MemPalace does not support read-only collection access"
            )
        return opener()

    def plan_canonical_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> list[str]:
        """Compute every exact drawer identity without reading or writing."""
        return plan_canonical_requirement_drawer_ids(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            wing=self.wing,
        )

    def mine_canonical_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> MineResult:
        """Mine one already-snapshotted canonical spec without a path reread."""
        _, requirements = self._canonical_requirements_from_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )
        result = MineResult(
            wing=self.wing,
            total=len(requirements),
            written=0,
            skipped=0,
            failed=0,
        )
        result.requirements = requirements
        self._write_requirements(
            requirements,
            result,
            artifact_metadata=artifact_metadata,
        )
        return result

    def mine_canonical_support_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> MineResult:
        """Mine one selected canonical support artifact without a path reread."""
        _, requirements = _canonical_support_from_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )
        result = MineResult(
            wing=self.wing,
            total=len(requirements),
            written=0,
            skipped=0,
            failed=0,
        )
        result.requirements = requirements
        self._write_requirements(
            requirements,
            result,
            artifact_metadata=artifact_metadata,
        )
        return result

    def mine_re_artifact_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> MineResult:
        """Mine one curated reverse-engineering artifact without a path reread."""
        _, requirements = _re_artifact_from_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )
        result = MineResult(
            wing=self.wing,
            total=len(requirements),
            written=0,
            skipped=0,
            failed=0,
        )
        result.requirements = requirements
        self._write_requirements(
            requirements,
            result,
            artifact_metadata=artifact_metadata,
        )
        return result

    def mine_spec_evidence_artifact_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
    ) -> MineResult:
        """Mine one curated spec evidence artifact without a path reread."""
        _, requirements = _spec_evidence_artifact_from_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )
        result = MineResult(
            wing=self.wing,
            total=len(requirements),
            written=0,
            skipped=0,
            failed=0,
        )
        result.requirements = requirements
        self._write_requirements(
            requirements,
            result,
            artifact_metadata=artifact_metadata,
        )
        return result

    def verify_canonical_bytes(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
        drawer_ids: list[str],
    ) -> bool:
        """Verify selected exact drawers from canonical bytes without writing."""
        return self.verify_canonical_bytes_outcome(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
            drawer_ids=drawer_ids,
        ) == "exact"

    def verify_canonical_bytes_outcome(
        self,
        content: bytes,
        *,
        source: str,
        artifact_metadata: dict[str, Any],
        drawer_ids: list[str],
    ) -> str:
        """Verify exact drawers while preserving backend unavailability."""
        digest, requirements = self._canonical_requirements_from_bytes(
            content,
            source=source,
            artifact_metadata=artifact_metadata,
        )
        if (
            type(drawer_ids) is not list
            or any(type(value) is not str for value in drawer_ids)
            or drawer_ids != sorted(set(drawer_ids))
        ):
            return "drift"
        from codegen.memory.mempalace_writer import (
            deterministic_requirement_drawer_id,
        )

        planned: dict[str, MinedRequirement] = {}
        for requirement in requirements:
            scrubbed = scrub_secrets(requirement.content)
            drawer_id = deterministic_requirement_drawer_id(
                wing=self.wing,
                room=requirement.room,
                spec_sha256=digest,
                requirement_id=requirement.req_id,
                content=scrubbed,
            )
            if drawer_id in planned:
                return "drift"
            planned[drawer_id] = requirement
        if any(drawer_id not in planned for drawer_id in drawer_ids):
            return "drift"
        writer = self._get_writer()
        verify = getattr(writer, "verify_exact", None)
        if not callable(verify):
            return "unavailable"
        for drawer_id in drawer_ids:
            requirement = planned[drawer_id]
            result = verify(
                room=requirement.room,
                content=scrub_secrets(requirement.content),
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id=requirement.req_id,
            )
            if getattr(result, "outcome", None) == "unavailable":
                return "unavailable"
            if (
                getattr(result, "outcome", None)
                != "already_present"
                or getattr(result, "drawer_id", None) != drawer_id
            ):
                return "drift"
        return "exact"

    def mine_directory(self, directory: Path, glob: str = "**/*.md") -> MineResult:
        """Mine all matching files in a directory tree."""
        combined = MineResult(wing=self.wing, total=0, written=0, skipped=0, failed=0)
        for path in sorted(directory.glob(glob)):
            r = self.mine_file(path)
            combined.total += r.total
            combined.written += r.written
            combined.skipped += r.skipped
            combined.failed += r.failed
            combined.already_present += r.already_present
            combined.unavailable += r.unavailable
            combined.requirements.extend(r.requirements)
            combined.drawer_ids.extend(r.drawer_ids)
            combined.expected_drawer_ids.extend(
                r.expected_drawer_ids
            )
            combined.errors.extend(r.errors)
        return combined

    def mine_text(self, text: str, source: str = "inline") -> MineResult:
        """Mine a raw text string (e.g. Confluence page content)."""
        result = MineResult(wing=self.wing, total=0, written=0, skipped=0, failed=0)
        reqs = _parse_markdown(text, source=source)
        result.total = len(reqs)
        result.requirements = reqs
        self._write_requirements(reqs, result, artifact_metadata=None)
        return result

    def mine_jira_issues(self, issues: list[dict]) -> MineResult:
        """
        Mine a list of Jira issue dicts (from Jira MCP tool output).

        Each dict expected to have: key, summary, description, issuetype.
        """
        result = MineResult(wing=self.wing, total=len(issues), written=0, skipped=0, failed=0)
        reqs = []
        for issue in issues:
            try:
                source = f"jira:{issue.get('key', 'UNKNOWN')}"
                req = _parse_jira_issue(issue, source=source)
                if req:
                    reqs.append(req)
            except Exception as exc:
                msg = f"Jira parse error for {issue.get('key')}: {exc}"
                logger.warning("[SpecMemoryMiner] %s", msg)
                result.errors.append(msg)
                result.failed += 1
        result.requirements = reqs
        self._write_requirements(reqs, result, artifact_metadata=None)
        return result

    def mine_bug(self, bug: dict) -> MineResult:
        """
        Write a test-period bug as a BUG-NNN drawer in the bugs room.

        Expected keys: id, title, test_name, fr_id, description, file, iteration.
        FR-RM-004: Non-fatal — failures degrade gracefully.
        """
        result = MineResult(wing=self.wing, total=1, written=0, skipped=0, failed=0)
        req_id = f"BUG-{bug.get('id', '001')}"
        content = (
            f"{req_id}: {bug.get('title', 'Unknown bug')}. "
            f"Test: {bug.get('test_name', 'unknown')}. "
            f"FR: {bug.get('fr_id', 'UNTRACED')}. "
            f"Description: {bug.get('description', '')}. "
            f"File: {bug.get('file', 'unknown')}. "
            f"Iteration: {bug.get('iteration', 0)}."
        )
        req = MinedRequirement(req_id=req_id, room="bugs", content=content, source="test-loop")
        result.requirements = [req]
        self._write_requirements([req], result, artifact_metadata=None)
        logger.info("[SpecMemoryMiner] Bug mined: %s", req_id)
        return result

    def _write_requirements(
        self,
        reqs: list[MinedRequirement],
        result: MineResult,
        artifact_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write mined requirements to MemPalace via MemPalaceWriter.

        SEC-025 FIX-1: All content fields are scrubbed of credentials before
        any ChromaDB write, on every code path (FR-001, FR-002).
        """
        if not self._collision_checked:
            self._collision_checked = True
            foreign = check_wing_collision(self.ctx.wing, self.project_dir, self.ctx.palace_path)
            if foreign:
                print(
                    f"\n⚠  Wing '{self.ctx.wing}' already has drawers from a different project:",
                    file=sys.stderr,
                )
                for path in foreign[:5]:
                    print(f"     {path}", file=sys.stderr)
                print(
                    "   Mining continues — shared memory is intentional or choose a different wing.\n",
                    file=sys.stderr,
                )
        writer = self._get_writer()
        canonical_spec_sha256: str | None = None
        if (
            type(artifact_metadata) is dict
            and artifact_metadata.get("canonical") is True
        ):
            artifact_digest = artifact_metadata.get("artifact_hash")
            if (
                type(artifact_digest) is str
                and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest)
            ):
                canonical_spec_sha256 = artifact_digest.removeprefix(
                    "sha256:"
                )
        deterministic_ids: set[str] = set()
        for req in reqs:
            try:
                content = scrub_secrets(req.content)
                exact_write = getattr(writer, "write_exact", None)
                if (
                    canonical_spec_sha256 is not None
                    and callable(exact_write)
                ):
                    from codegen.memory.mempalace_writer import (
                        deterministic_requirement_drawer_id,
                    )

                    expected_id = deterministic_requirement_drawer_id(
                        wing=self.wing,
                        room=req.room,
                        spec_sha256=canonical_spec_sha256,
                        requirement_id=req.req_id,
                        content=content,
                    )
                    result.expected_drawer_ids.append(expected_id)
                    if expected_id in deterministic_ids:
                        result.failed += 1
                        result.errors.append(
                            "deterministic_identity_collision"
                        )
                        continue
                    deterministic_ids.add(expected_id)
                    provenance_type = artifact_metadata.get("provenance_type")
                    if not isinstance(provenance_type, str) or not provenance_type:
                        provenance_type = "requirements_mine"
                    phase = artifact_metadata.get("phase")
                    if not isinstance(phase, str) or not phase:
                        phase = "RE"
                    exact_result = exact_write(
                        room=req.room,
                        content=content,
                        phase=phase,
                        drawer_id=expected_id,
                        spec_sha256=canonical_spec_sha256,
                        requirement_id=req.req_id,
                        provenance_type=provenance_type,
                        source_file=req.source,
                        extra_metadata=artifact_metadata,
                    )
                    outcome = getattr(exact_result, "outcome", None)
                    drawer_id = getattr(
                        exact_result,
                        "drawer_id",
                        None,
                    )
                    if outcome == "written" and drawer_id == expected_id:
                        result.written += 1
                        result.drawer_ids.append(expected_id)
                    elif (
                        outcome == "already_present"
                        and drawer_id == expected_id
                    ):
                        result.already_present += 1
                        result.drawer_ids.append(expected_id)
                    elif outcome == "unavailable" and drawer_id is None:
                        result.unavailable += 1
                    elif outcome == "drift" and drawer_id is None:
                        result.drifted += 1
                        result.errors.append(
                            "deterministic_write_drift"
                        )
                    else:
                        result.failed += 1
                        result.errors.append(
                            "deterministic_write_failed"
                        )
                    continue

                drawer_id = writer.write(  # type: ignore[union-attr]
                    room=req.room,
                    content=content,
                    phase=(
                        artifact_metadata.get("phase")
                        if isinstance(artifact_metadata, dict)
                        and isinstance(artifact_metadata.get("phase"), str)
                        else "RE"
                    ),
                    provenance_type=(
                        artifact_metadata.get("provenance_type")
                        if isinstance(artifact_metadata, dict)
                        and isinstance(artifact_metadata.get("provenance_type"), str)
                        else "requirements_mine"
                    ),
                    source_file=req.source,
                    extra_metadata=artifact_metadata,
                )
                if drawer_id:
                    result.written += 1
                    result.drawer_ids.append(drawer_id)
                else:
                    result.skipped += 1
            except Exception as exc:
                msg = f"Write failed for {req.req_id}: {exc}"
                logger.warning("[SpecMemoryMiner] %s", msg)
                result.errors.append(msg)
                result.failed += 1


# Backward-compatible alias for legacy callers. New code should import
# SpecMemoryMiner from echelon.spec_memory_miner.
RequirementsMiner = SpecMemoryMiner
