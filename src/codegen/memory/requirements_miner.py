"""
requirements_miner.py — Mine requirement sources into MemPalace drawers.

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


@dataclass
class MineResult:
    wing: str
    total: int
    written: int
    skipped: int
    failed: int
    requirements: list[MinedRequirement] = field(default_factory=list)
    drawer_ids: list[str] = field(default_factory=list)
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
        fr_match = _REQ_ID_PATTERN.match(line)
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
                if not next_line or next_line.startswith(("**FR-", "**NFR-", "#")):
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

    while i < len(lines):
        line = lines[i]
        m = _REQ_ID_PATTERN.match(line)
        if m:
            req_id = m.group("id")
            body_lines = [m.group("text").strip()]
            # Accumulate continuation lines
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
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


class RequirementsMiner:
    """
    Mines requirement sources and writes them as MemPalace drawers.

    Supports:
      - Markdown / plain-text spec files (FR-RM-001)
      - Jira issue dicts (for programmatic use with Jira MCP tool output)
      - Confluence page text (treated as markdown)

    Usage:
        ctx = MemPalaceContext.from_project(project_dir, run_id="mine-run")
        miner = RequirementsMiner(ctx, project_dir=project_dir)
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
            logger.warning("[RequirementsMiner] %s", msg)
            result.errors.append(msg)
            return result

        reqs = _parse_markdown(text, source=str(path))
        result.total = len(reqs)
        result.requirements = reqs
        self._write_requirements(reqs, result, artifact_metadata=artifact_metadata)
        logger.info(
            "[RequirementsMiner] %s: %d mined, %d written, %d failed",
            path.name, result.total, result.written, result.failed,
        )
        return result

    def mine_directory(self, directory: Path, glob: str = "**/*.md") -> MineResult:
        """Mine all matching files in a directory tree."""
        combined = MineResult(wing=self.wing, total=0, written=0, skipped=0, failed=0)
        for path in sorted(directory.glob(glob)):
            r = self.mine_file(path)
            combined.total += r.total
            combined.written += r.written
            combined.skipped += r.skipped
            combined.failed += r.failed
            combined.requirements.extend(r.requirements)
            combined.drawer_ids.extend(r.drawer_ids)
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
                logger.warning("[RequirementsMiner] %s", msg)
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
        logger.info("[RequirementsMiner] Bug mined: %s", req_id)
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
        for req in reqs:
            try:
                drawer_id = writer.write(  # type: ignore[union-attr]
                    room=req.room,
                    content=scrub_secrets(req.content),
                    phase="RE",
                    provenance_type="requirements_mine",
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
                logger.warning("[RequirementsMiner] %s", msg)
                result.errors.append(msg)
                result.failed += 1
