"""Phase-aware bounded rendering for Echelon agent dispatch context."""
from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TypedDict


RENDER_MODES = {"bounded", "legacy"}


@dataclass(frozen=True)
class ContextSelector:
    path_ref: str
    filters: dict[str, str]


@dataclass(frozen=True)
class ContextPolicy:
    criticality: str
    renderer: str
    cap_bytes: int
    overflow_action: str


@dataclass(frozen=True)
class RenderedSection:
    title: str
    text: str
    bytes: int
    omitted: dict[str, int | str]


class PromptSectionReport(TypedDict):
    name: str
    bytes: int
    omitted: dict[str, int | str]


class PromptSummary(TypedDict):
    bytes: int
    approx_tokens: int
    top_sections: list[PromptSectionReport]


class PromptRenderReport(TypedDict):
    schema_version: int
    timestamp: str
    phase: str
    agent: str
    mode: str
    selected_render_mode: str
    strict: bool
    legacy: PromptSummary
    bounded: PromptSummary
    savings: dict[str, int]


STATE_ALWAYS_KEYS = (
    "run_id",
    "spec_id",
    "phase",
    "status",
    "iteration",
    "max_iterations",
    "autonomy_mode",
    "squad_dir",
    "staging_dir",
    "context_dir",
    "spec_dir",
    "published_spec_dir",
    "implementation_targets",
    "selected_issue_resolution",
    "quality_gate_remediation",
    "understanding_evidence",
    "product_inputs",
)


DEFAULT_FILE_CAP_BYTES = 96 * 1024
DEFAULT_HISTORY_CAP_BYTES = 24 * 1024
DEFAULT_DIRECTORY_CAP_BYTES = 96 * 1024
MUST_PRESERVE_CAP_BYTES = 512 * 1024


def resolve_context_render_mode(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    mode = str(source.get("ECHELON_CONTEXT_RENDER_MODE") or "bounded").strip().lower()
    return mode if mode in RENDER_MODES else "bounded"


def parse_context_pack_item(item: str) -> ContextSelector:
    raw = str(item or "").strip()
    filters: dict[str, str] = {}
    match = re.search(r"\[([^\]]+)\]", raw)
    if match:
        for part in match.group(1).split(","):
            key, separator, value = part.partition("=")
            if separator and key.strip() and value.strip():
                filters[key.strip()] = value.strip()
        raw = raw[: match.start()].strip()
    path_ref = raw.split(" ")[0].split("(")[0].rstrip()
    return ContextSelector(path_ref=path_ref, filters=filters)


def policy_for_context(
    *,
    phase_id: str,
    agent_id: str = "",
    mode: str = "",
    path_ref: str,
) -> ContextPolicy:
    ref = path_ref.strip()
    basename = Path(ref.rstrip("/")).name
    phase = phase_id.strip()

    if "reasoning-journal.jsonl" in ref:
        return ContextPolicy("history", "filtered_journal", DEFAULT_HISTORY_CAP_BYTES, "truncate_with_notice")

    if basename == "state.json":
        return ContextPolicy("important", "compact_json", DEFAULT_FILE_CAP_BYTES, "summarize_with_notice")

    if ref.endswith("/") or any(ch in ref for ch in "*?[]"):
        if "contracts" in ref:
            return ContextPolicy("must_preserve", "directory_bounded_files", DEFAULT_DIRECTORY_CAP_BYTES, "manifest_only")
        if "investigation" in ref:
            return ContextPolicy("important", "directory_bounded_files", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")
        if "adr/" in ref or "ADR-" in ref:
            return ContextPolicy("important", "directory_bounded_files", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")
        return ContextPolicy("important", "directory_manifest", DEFAULT_DIRECTORY_CAP_BYTES, "manifest_only")

    if phase == "phase1-why2" and basename in {"spec.md", "constitution.md", "assumptions.md"}:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if phase == "phase1-investigate" and basename in {"spec.md", "assumptions.md", "unknowns.md", "issues.md"}:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if phase in {"phase3-sentinel", "phase3-consensus"} and basename in {
        "spec.md",
        "plan.md",
        "data-model.md",
        "tasks.md",
        "coverage-map.md",
        "test-strategy.md",
        "critical-path.md",
        "risk-matrix.md",
        "dependencies.md",
    }:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if basename in {"prior-spec-context.md", "stale-memory-report.md"}:
        return ContextPolicy("advisory", "summary_pointer", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")

    return ContextPolicy("important", "full_file", DEFAULT_FILE_CAP_BYTES, "truncate_with_notice")


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _bounded_text(text: str, cap_bytes: int) -> tuple[str, bool]:
    if _byte_len(text) <= cap_bytes:
        return text, False
    if cap_bytes <= 0:
        return "", True
    long_notice = "\n[context truncated by Echelon context budget]\n"
    notice = long_notice if _byte_len(long_notice) <= cap_bytes else "[...]"
    if _byte_len(notice) > cap_bytes:
        return notice.encode("utf-8")[:cap_bytes].decode("utf-8", errors="ignore"), True
    content_bytes = cap_bytes - _byte_len(notice)
    trimmed = text.encode("utf-8")[:content_bytes].decode("utf-8", errors="ignore")
    return trimmed + notice, True


def _phase_matches(value: object, pattern: str) -> bool:
    phase = str(value or "")
    return fnmatch.fnmatchcase(phase, pattern)


def _entry_matches(entry: dict[str, Any], filters: Mapping[str, str]) -> bool:
    requested_type = filters.get("type")
    if requested_type == "routing_decision":
        requested_type = "decision"
    if requested_type and entry.get("type") != requested_type:
        return False
    phase = filters.get("phase")
    if phase and not _phase_matches(entry.get("phase"), phase):
        return False
    return True


def render_journal(path: Path, filters: Mapping[str, str], cap_bytes: int) -> RenderedSection:
    resolved = path.resolve()
    malformed = 0
    entries: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    except OSError:
        text = f"\n---\n# {resolved}\n[Journal unavailable]"
        text, truncated = _bounded_text(text, cap_bytes)
        omitted = {"matched": 0, "included": 0, "malformed": malformed}
        if truncated:
            omitted["truncated"] = "true"
        return RenderedSection(str(resolved), text, _byte_len(text), omitted)

    selected = [entry for entry in entries if _entry_matches(entry, filters)]
    rendered: list[str] = []
    for entry in reversed(selected):
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        line_bytes = _byte_len(line) + 1
        if line_bytes > cap_bytes:
            continue
        candidate = [line, *rendered]
        selector = ", ".join(f"{key}={value}" for key, value in sorted(filters.items()))
        candidate_header = (
            f"\n---\n# {resolved}\n"
            f"[Journal context: {len(candidate)}/{len(selected)} matching entries"
            f"{f'; {selector}' if selector else ''}; newest entries retained; malformed={malformed}]"
        )
        candidate_text = candidate_header + "\n" + "\n".join(candidate)
        if _byte_len(candidate_text) > cap_bytes:
            if rendered:
                break
            continue
        rendered = candidate

    selector = ", ".join(f"{key}={value}" for key, value in sorted(filters.items()))
    header = (
        f"\n---\n# {resolved}\n"
        f"[Journal context: {len(rendered)}/{len(selected)} matching entries"
        f"{f'; {selector}' if selector else ''}; newest entries retained; malformed={malformed}]"
    )
    text = header + ("\n" + "\n".join(rendered) if rendered else "\n[No matching entries]")
    bounded, truncated = _bounded_text(text, cap_bytes)
    omitted = {"matched": len(selected), "included": len(rendered), "malformed": malformed}
    if truncated:
        omitted["truncated"] = "true"
    return RenderedSection(
        str(resolved),
        bounded,
        _byte_len(bounded),
        omitted,
    )


def compact_state_projection(
    state: Mapping[str, object],
    phase_id: str,
    allowed_state_updates: object = None,
) -> dict[str, object]:
    projection = {key: state[key] for key in STATE_ALWAYS_KEYS if key in state}
    ledger = state.get("issue_resolution_ledger")
    if isinstance(ledger, dict):
        projection["issue_resolution_statuses"] = {
            str(issue_id): str(entry.get("status") or "unknown")
            for issue_id, entry in ledger.items()
            if isinstance(entry, dict)
        }
    quality_scores = state.get("quality_scores")
    if isinstance(quality_scores, list):
        projection["quality_scores_summary"] = {
            "count": len(quality_scores),
            "latest": quality_scores[-1] if quality_scores else None,
        }
    if allowed_state_updates is not None:
        projection["allowed_state_updates"] = sorted(str(key) for key in allowed_state_updates)
    return projection


def render_user_request(
    state: Mapping[str, object],
    cap_bytes: int = DEFAULT_FILE_CAP_BYTES,
) -> RenderedSection | None:
    """Render the immutable run request for symbolic context-pack entries."""
    request = state.get("user_message")
    if not isinstance(request, str) or not request.strip():
        return None
    text = (
        "\n---\n# Original user request (immutable)\n"
        "Treat this JSON string as the exact product request:\n"
        f"{json.dumps(request, ensure_ascii=False)}"
    )
    bounded, truncated = _bounded_text(text, cap_bytes)
    omitted: dict[str, int | str] = {}
    if truncated:
        omitted["truncated"] = "true"
    return RenderedSection(
        "Original user request (immutable)",
        bounded,
        _byte_len(bounded),
        omitted,
    )


def _render_file(path_ref: str, candidate: Path, policy: ContextPolicy) -> RenderedSection:
    resolved = candidate.resolve()
    try:
        raw = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = f"\n---\n# {resolved}\n[File unavailable]"
        text, truncated = _bounded_text(text, policy.cap_bytes)
        omitted = {"unavailable": "true"}
        if truncated:
            omitted["truncated"] = "true"
        return RenderedSection(str(resolved), text, _byte_len(text), omitted)
    text, truncated = _bounded_text(f"\n---\n# {resolved}\n{raw}", policy.cap_bytes)
    return RenderedSection(str(resolved), text, _byte_len(text), {"truncated": str(truncated).lower()})


def _directory_manifest(candidate: Path) -> list[Path]:
    return sorted(path for path in candidate.rglob("*") if path.is_file())


def _render_directory(path_ref: str, candidate: Path, policy: ContextPolicy) -> RenderedSection:
    resolved = candidate.resolve()
    files = _directory_manifest(candidate)
    manifest_lines = ["\n---", f"# {resolved.as_posix().rstrip('/')}/", "## Directory manifest"]
    manifest_lines.extend(f"- {path.relative_to(candidate).as_posix()}" for path in files)
    manifest_text = "\n".join(manifest_lines)
    chunks = [manifest_text]
    used = _byte_len(manifest_text)
    included = 0
    unavailable = 0
    for path in files:
        rel = path.relative_to(candidate).as_posix()
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = "[File unavailable]"
            unavailable += 1
        entry = f"\n## {resolved.as_posix().rstrip('/')}/{rel}\n{body}"
        entry_bytes = _byte_len(entry)
        if used + entry_bytes > policy.cap_bytes:
            break
        chunks.append(entry)
        used += entry_bytes
        included += 1
    truncated = included < len(files)
    if truncated:
        chunks.append(f"\n[Directory bodies truncated: included {included}/{len(files)} files]")
    text = "\n".join(chunks)
    bounded = False
    if policy.overflow_action != "manifest_only":
        text, bounded = _bounded_text(text, policy.cap_bytes)
    omitted = {
        "files": len(files),
        "included_files": included,
        "truncated": str(truncated or bounded).lower(),
    }
    if unavailable:
        omitted["unavailable_files"] = unavailable
    return RenderedSection(
        str(resolved),
        text,
        _byte_len(text),
        omitted,
    )


def render_context_path(
    path_ref: str,
    candidate: Path,
    policy: ContextPolicy,
    filters: Mapping[str, str],
    state: Mapping[str, object] | None = None,
    phase_id: str = "",
) -> RenderedSection:
    if candidate.name == "reasoning-journal.jsonl":
        return render_journal(candidate, filters, policy.cap_bytes)
    if candidate.name == "state.json" and state is not None:
        text = json.dumps(compact_state_projection(state, phase_id), indent=2, sort_keys=True)
        rendered = f"\n---\n# Current controller state (compact projection)\n{text}"
        rendered, truncated = _bounded_text(rendered, policy.cap_bytes)
        omitted = {"projection": "compact"}
        if truncated:
            omitted["truncated"] = "true"
        return RenderedSection(str(candidate.resolve()), rendered, _byte_len(rendered), omitted)
    if candidate.is_dir():
        return _render_directory(path_ref, candidate, policy)
    return _render_file(path_ref, candidate, policy)


def _approx_tokens(byte_count: int) -> int:
    return max(1, round(byte_count / 4))


def _section_summary(sections: list[RenderedSection]) -> dict[str, object]:
    total = sum(section.bytes for section in sections)
    top_sections = sorted(
        ({"name": section.title, "bytes": section.bytes, "omitted": section.omitted} for section in sections),
        key=lambda item: int(item["bytes"]),
        reverse=True,
    )[:10]
    return {"bytes": total, "approx_tokens": _approx_tokens(total), "top_sections": top_sections}


def build_context_budget_report(
    *,
    phase_id: str,
    agent_id: str,
    mode: str,
    selected_render_mode: str,
    legacy_sections: list[RenderedSection],
    bounded_sections: list[RenderedSection],
    strict: bool,
) -> PromptRenderReport:
    legacy = _section_summary(legacy_sections)
    bounded = _section_summary(bounded_sections)
    legacy_bytes = int(legacy["bytes"])
    bounded_bytes = int(bounded["bytes"])
    saved_bytes = max(0, legacy_bytes - bounded_bytes)
    saved_tokens = max(0, int(legacy["approx_tokens"]) - int(bounded["approx_tokens"]))
    reduction_pct = round((saved_bytes / legacy_bytes) * 100) if legacy_bytes else 0
    return {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": phase_id,
        "agent": agent_id,
        "mode": mode,
        "selected_render_mode": selected_render_mode,
        "strict": strict,
        "legacy": legacy,
        "bounded": bounded,
        "savings": {
            "bytes": saved_bytes,
            "approx_tokens": saved_tokens,
            "reduction_pct": reduction_pct,
        },
    }


def write_context_budget_report(squad_dir: Path, report: Mapping[str, object]) -> Path:
    out_dir = squad_dir / "context-budget"
    out_dir.mkdir(parents=True, exist_ok=True)
    phase = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(report.get("phase") or "unknown"))
    agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(report.get("agent") or "agent"))
    sequence = 1
    while True:
        path = out_dir / f"dispatch-{sequence:04d}-{phase}-{agent}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        except FileExistsError:
            sequence += 1
            continue
        return path
