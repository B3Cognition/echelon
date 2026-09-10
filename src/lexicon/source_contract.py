"""Source-contract checks for derived Lexicon artifacts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from lark.exceptions import LarkError

from .linter import Finding
from .parser import parse
from .resolver import content_terms

_SOURCE_RE = re.compile(r"^#\s*SOURCE:\s*(?P<source>.+?)\s*$", re.MULTILINE)
_SOURCE_SHA_RE = re.compile(
    r"^#\s*SOURCE_SHA256:\s*(?P<sha>[0-9a-fA-F]{64})\s*$", re.MULTILINE
)
# Acceptance criteria commonly carry a letter suffix for edge-case variants
# (for example ``AC-004b``).  Treat the complete identifier as one source ID;
# stopping at the numeric prefix makes an otherwise faithful derived contract
# look as though it invented the suffix and dropped the base criterion.
_SOURCE_ID = r"(?:FR|NFR|REQ|AC|ERR|ERROR)-\d+(?:[A-Za-z][A-Za-z0-9_-]*)?"
# Rich specifications declare their IDs at the beginning of a list item,
# heading, or standalone line. References embedded in a requirement body (for
# example ``003-base/FR-023``) are inherited context, not declarations owned
# by the current source. Capturing every identifier-shaped token turns those
# references into impossible projection obligations.
_SOURCE_DECLARED_ID_RE = re.compile(
    rf"^[ \t]*(?:[-*+][ \t]+|#+[ \t]+)?(?:\*\*|`)?(?P<id>{_SOURCE_ID})(?:\*\*|`)?(?=[ \t]*(?::|$))",
    re.MULTILINE,
)


def source_contract_findings(derived_text: str, source_ref: Path) -> list[Finding]:
    """Validate that a derived Lexicon artifact is fresh and ID-equivalent.

    The rich ``spec.md`` remains the semantic source of truth. A derived
    ``requirements.lexicon.md`` must carry enough metadata for deterministic
    consumers to prove it was compiled from the current source and does not
    invent or drop requirement/acceptance/error IDs.
    """

    findings: list[Finding] = []
    source_text = source_ref.read_text(encoding="utf-8")
    source_match = _SOURCE_RE.search(derived_text)
    hash_match = _SOURCE_SHA_RE.search(derived_text)

    if not source_match:
        findings.append(
            Finding(
                code="source-metadata-missing",
                message="derived artifact is missing # SOURCE metadata",
                line=1,
                span="SOURCE",
            )
        )
    elif Path(source_match.group("source")).name != source_ref.name:
        findings.append(
            Finding(
                code="source-ref-mismatch",
                message=(
                    "derived artifact SOURCE metadata does not match "
                    f"{source_ref.name}"
                ),
                line=_line_of_match(derived_text, source_match.start()),
                span=source_match.group("source"),
            )
        )

    if not hash_match:
        findings.append(
            Finding(
                code="source-metadata-missing",
                message="derived artifact is missing # SOURCE_SHA256 metadata",
                line=1,
                span="SOURCE_SHA256",
            )
        )
    else:
        actual_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        declared_sha = hash_match.group("sha").lower()
        if declared_sha != actual_sha:
            findings.append(
                Finding(
                    code="source-hash-mismatch",
                    message="derived artifact SOURCE_SHA256 does not match source_ref",
                    line=_line_of_match(derived_text, hash_match.start()),
                    span=hash_match.group("sha"),
                )
            )

    source_ids = _source_ids(source_text)
    derived_ids = _derived_ids(derived_text)

    # A structural parse failure makes the projection's declared ID set
    # unknowable.  Reporting every source ID as missing in that state is both
    # false and counterproductive: the parse error is the actionable root
    # cause, while the apparent source-ID diff is just an artifact of the
    # parser returning no tree.  Metadata remains independently checkable.
    if derived_ids is None:
        return findings

    for extra in sorted(derived_ids - source_ids):
        findings.append(
            Finding(
                code="source-id-extra",
                message=f"derived artifact declares ID {extra} absent from source_ref",
                line=_line_for_id(derived_text, extra),
                span=extra,
            )
        )

    for missing in sorted(source_ids - derived_ids):
        findings.append(
            Finding(
                code="source-id-missing",
                message=f"source_ref ID {missing} is missing from derived artifact",
                line=0,
                span=missing,
            )
        )

    return findings


def _derived_ids(text: str) -> set[str] | None:
    try:
        tree = parse(text)
    except LarkError:
        return None

    ids: set[str] = set()
    for kind in ("req", "ac", "error_block"):
        for node in tree.find_data(kind):
            ids.add(str(node.children[0]))
    return ids


def _source_ids(text: str) -> set[str]:
    """Return IDs declared by a rich source, excluding inline references."""
    return {match.group("id") for match in _SOURCE_DECLARED_ID_RE.finditer(text)}


def source_approved_terms(source_ref: Path) -> set[str]:
    """Return governed identifier terms that the canonical source already owns.

    A derived projection must preserve source-defined measurable constraints.
    Those identifiers are valid in the projection even when a separately
    authored glossary has not repeated them; identifiers absent from both stay
    unresolved and therefore cannot be invented by a derivation agent.
    """
    source_text = source_ref.read_text(encoding="utf-8")
    return {term for term, _line in content_terms(source_text)}


def _line_for_id(text: str, value: str) -> int:
    for lineno, line in enumerate(text.splitlines(), start=1):
        if value in line:
            return lineno
    return 0


def _line_of_match(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
