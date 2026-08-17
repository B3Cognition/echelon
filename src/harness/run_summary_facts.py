"""Typed, controller-authored facts for terminal run summaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
import json
from types import MappingProxyType
import re
from typing import Mapping, Sequence


MAX_FACT_BYTES = 280
MAX_PACKET_BYTES = 12 * 1024
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])"
)
_MULTI_SENTENCE_RE = re.compile(r"[.!?][\"')\]]*\s+\S")


class SummaryFactCategory(str, Enum):
    OUTCOME = "outcome"
    WORK = "work"
    VERIFICATION = "verification"
    BLOCKER = "blocker"
    HANDOFF = "handoff"


class SummaryFactImportance(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2


@dataclass(frozen=True)
class SummaryFact:
    category: SummaryFactCategory
    importance: SummaryFactImportance
    text: str
    source_order: int


@dataclass(frozen=True)
class CatalogFact:
    id: str
    category: SummaryFactCategory
    importance: SummaryFactImportance
    text: str
    source_order: int


@dataclass(frozen=True)
class SummaryCatalog:
    entries: tuple[CatalogFact, ...]
    by_id: Mapping[str, CatalogFact]
    packet_json: str


def _compact_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.translate(
        {ord("&"): "\\u0026", ord("<"): "\\u003c", ord(">"): "\\u003e"}
    )


def _bounded_context(value: object, byte_limit: int) -> str:
    normalized = _CONTROL_RE.sub(" ", str(value or ""))
    encoded = normalized.encode("utf-8", errors="replace")
    return encoded[:byte_limit].decode("utf-8", errors="ignore")


def _default_outcome(command: str, status: str) -> str:
    delivery = "delivery" in command.casefold()
    work = "delivery" if delivery else "specification work"
    normalized_status = status.casefold().strip()
    if normalized_status == "done":
        return f"Echelon completed the requested {work}."
    if normalized_status == "returned":
        return f"Echelon finished dispatching the requested {work}."
    return f"Echelon worked on the requested {work}, but it is not complete."


def _valid_fact(value: object) -> bool:
    if type(value) is not SummaryFact:
        return False
    if type(value.category) is not SummaryFactCategory:
        return False
    if type(value.importance) is not SummaryFactImportance:
        return False
    if type(value.source_order) is not int or value.source_order < 0:
        return False
    if type(value.text) is not str:
        return False
    text = value.text.strip()
    return bool(
        text
        and text == value.text
        and text[-1:] in {".", "!", "?"}
        and len(text.encode("utf-8")) <= MAX_FACT_BYTES
        and not _CONTROL_RE.search(text)
        and not _ANSI_RE.search(text)
        and not _MULTI_SENTENCE_RE.search(text[:-1])
    )


def _packet_value(
    command: str,
    task: str,
    status: str,
    facts: Sequence[SummaryFact],
) -> tuple[tuple[CatalogFact, ...], str]:
    entries = tuple(
        CatalogFact(
            id=f"f{index:04d}",
            category=fact.category,
            importance=fact.importance,
            text=fact.text,
            source_order=fact.source_order,
        )
        for index, fact in enumerate(facts, 1)
    )
    packet = {
        "schema_version": 2,
        "command": _bounded_context(command, 256),
        "task": _bounded_context(task, 1_024),
        "status": _bounded_context(status, 128),
        "facts": [
            {
                "id": entry.id,
                "category": entry.category.value,
                "importance": entry.importance.name.casefold(),
                "text": entry.text,
            }
            for entry in entries
        ],
    }
    return entries, _compact_json(packet)


def build_summary_catalog(
    *,
    facts: tuple[SummaryFact, ...],
    command: str,
    task: str,
    status: str,
    max_packet_bytes: int = MAX_PACKET_BYTES,
) -> SummaryCatalog:
    """Admit valid facts by authority priority into one bounded packet."""
    valid = [
        (fact.importance, fact.source_order, index, fact)
        for index, fact in enumerate(facts)
        if _valid_fact(fact)
    ]
    if not any(item[3].category is SummaryFactCategory.OUTCOME for item in valid):
        outcome = SummaryFact(
            SummaryFactCategory.OUTCOME,
            SummaryFactImportance.NORMAL,
            _default_outcome(command, status),
            max((item[1] for item in valid), default=-1) + 1,
        )
        valid.append((outcome.importance, outcome.source_order, len(valid), outcome))
    ordered = [item[3] for item in sorted(valid, key=lambda item: item[:3])]

    outcome = next(
        fact for fact in ordered if fact.category is SummaryFactCategory.OUTCOME
    )
    admitted: list[SummaryFact] = [outcome]
    for fact in ordered:
        if fact is outcome:
            continue
        candidate = sorted(
            (*admitted, fact),
            key=lambda item: (item.importance, item.source_order),
        )
        _entries, packet_json = _packet_value(command, task, status, candidate)
        if len(packet_json.encode("utf-8")) <= max_packet_bytes:
            admitted.append(fact)
    admitted.sort(key=lambda item: (item.importance, item.source_order))
    entries, packet_json = _packet_value(command, task, status, admitted)
    if len(packet_json.encode("utf-8")) > max_packet_bytes:
        entries, packet_json = _packet_value(command, task, status, (outcome,))
    by_id = MappingProxyType({entry.id: entry for entry in entries})
    return SummaryCatalog(entries=entries, by_id=by_id, packet_json=packet_json)


def resolve_fact_ids(
    catalog: SummaryCatalog,
    selected_ids: Sequence[str],
) -> tuple[str, ...]:
    selected = tuple(selected_ids)
    if len(selected) != len(set(selected)):
        raise ValueError("summary fact IDs must be unique")
    if any(item not in catalog.by_id for item in selected):
        raise ValueError("summary fact ID is not in the admitted catalog")
    return tuple(catalog.by_id[item].text for item in selected)


def _fits_output(
    lines: Sequence[str],
    mandatory_lines: Sequence[str],
    max_lines: int,
    max_bytes: int,
) -> bool:
    combined = (*lines, *mandatory_lines)
    return len(combined) <= max_lines and len("\n".join(combined).encode("utf-8")) <= max_bytes


def select_fallback_fact_ids(
    catalog: SummaryCatalog,
    *,
    mandatory_lines: tuple[str, ...] = (),
    max_lines: int = 7,
    max_bytes: int = 1_200,
) -> tuple[str, ...]:
    """Select at most three important facts while favoring category diversity."""
    if not catalog.entries:
        return ()
    candidates = list(catalog.entries)
    desired: list[CatalogFact] = [candidates.pop(0)]
    represented = {desired[0].category}
    for candidate in tuple(candidates):
        if len(desired) >= 3:
            break
        if candidate.category not in represented:
            desired.append(candidate)
            represented.add(candidate.category)
            candidates.remove(candidate)
    for candidate in candidates:
        if len(desired) >= 3:
            break
        desired.append(candidate)

    selected: list[str] = []
    for candidate in desired:
        lines = resolve_fact_ids(catalog, (*selected, candidate.id))
        if _fits_output(lines, mandatory_lines, max_lines, max_bytes):
            selected.append(candidate.id)
    return tuple(selected)
