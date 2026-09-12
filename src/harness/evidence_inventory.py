"""Pure structural validation for captured evidence inventory text."""

from __future__ import annotations

import json


def validate_evidence_inventory_text(
    text: str,
    *,
    required_seed_locators: tuple[str, ...] = (),
) -> str | None:
    """Return a structural error for captured inventory text, or ``None``."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return "root must be an object"
    if payload.get("schema_version") != 1:
        return "schema_version must equal 1"
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return "missing required list: sources"
    if not sources:
        return "sources must not be empty"
    required_source_fields = (
        "id",
        "locator",
        "kind",
        "status",
        "disposition",
        "discovered_from",
        "discovery_method",
    )
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            return f"sources[{index}] must be an object"
        for field in required_source_fields:
            if not isinstance(source.get(field), str) or not source[field].strip():
                return f"sources[{index}].{field} must be a non-empty string"
    frontier = payload.get("frontier")
    if not isinstance(frontier, dict):
        return "missing required object: frontier"
    if not isinstance(frontier.get("disposition"), str) or not frontier[
        "disposition"
    ].strip():
        return "frontier.disposition must be a non-empty string"
    unvisited = frontier.get("unvisited_relevant_sources")
    if not isinstance(unvisited, list) or not all(
        isinstance(source, str) and source.strip() for source in unvisited
    ):
        return "frontier.unvisited_relevant_sources must be a list of non-empty strings"
    expanded_seeds = frontier.get("expanded_seed_locators")
    if not isinstance(expanded_seeds, list) or not all(
        isinstance(source, str) and source.strip() for source in expanded_seeds
    ):
        return "frontier.expanded_seed_locators must be a list of non-empty strings"
    inventory_locators = {str(source["locator"]).strip() for source in sources}
    missing_seeds = [
        seed for seed in required_seed_locators if seed not in inventory_locators
    ]
    if missing_seeds:
        return "missing declared source seed(s): " + ", ".join(missing_seeds)
    missing_expanded_seeds = [
        seed for seed in required_seed_locators if seed not in expanded_seeds
    ]
    if missing_expanded_seeds:
        return "frontier does not account for declared source seed(s): " + ", ".join(
            missing_expanded_seeds
        )
    return None
