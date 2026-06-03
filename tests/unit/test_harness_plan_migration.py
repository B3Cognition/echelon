"""Harness-facing migration for legacy plan.md files."""

from __future__ import annotations

from harness.plan_migration import migrate_plan_markdown
from kernel.plan_contract import validate_plan_markdown


def test_migrate_plan_promotes_nested_project_structure_and_adds_missing_sections() -> None:
    migrated = migrate_plan_markdown(
        """
# Architecture Plan: Demo

## Summary

Demo plan.

## Technical Context

### Stack

Swift.

## Component Architecture

### Project Structure

```text
src/
```

## Risks Identified by ARCHITECT

- Parser risk.

## Implementation Phases

### Phase 1: Foundation
"""
    )

    assert "## Project Structure\n\n```text\nsrc/" in migrated
    assert "## Architecture Decisions" in migrated
    assert "## Testing Strategy" in migrated
    assert "## Risks\n\n- Parser risk." in migrated
    assert "## Constitution Check" in migrated
    assert validate_plan_markdown(migrated).valid is True


def test_migrate_plan_leaves_template_compliant_plan_unchanged() -> None:
    source = """
# Implementation Plan: Demo

## Summary

Demo.

## Technical Context

### Stack

Swift.

## Architecture Decisions

- ADR-001: Swift.

## Project Structure

```text
src/
```

## Implementation Phases

### Phase 1: Foundation

## Testing Strategy

- Unit tests.

## Risks

- None.

## Constitution Check

| Principle | Compliance |
| --- | --- |
| Local-first | PASS |
"""

    assert migrate_plan_markdown(source) == source
