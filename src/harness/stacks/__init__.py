"""Echelon stack loading, validation, resolution, and rendering."""

from harness.stacks.detection import (
    DetectedStack,
    StackDecision,
    StackDetectionReport,
    detect_stacks,
    detection_report_from_file,
    detection_report_to_yaml,
    render_detection_markdown,
    write_detection_report,
)
from harness.stacks.loader import load_stack_definitions
from harness.stacks.preflight import (
    StackPreflightFinding,
    StackPreflightResult,
    preflight_to_dict,
    render_preflight_markdown,
    run_stack_preflight,
)
from harness.stacks.renderer import render_resolved_markdown, resolved_to_dict
from harness.stacks.resolver import ResolvedStacks, resolve_stacks

__all__ = [
    "DetectedStack",
    "ResolvedStacks",
    "StackDecision",
    "StackDetectionReport",
    "StackPreflightFinding",
    "StackPreflightResult",
    "detect_stacks",
    "detection_report_from_file",
    "detection_report_to_yaml",
    "load_stack_definitions",
    "preflight_to_dict",
    "render_detection_markdown",
    "render_preflight_markdown",
    "render_resolved_markdown",
    "resolve_stacks",
    "resolved_to_dict",
    "run_stack_preflight",
    "write_detection_report",
]
