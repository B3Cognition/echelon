"""
constitution_writer.py — Writes ConstitutionDraft to constitution.md.
Spec 018 F3 T-013.

Safety rules:
  - Uses PathSafety.anchor_output() for all writes (RAR-002)
  - force=False + existing file → halt, no write
  - force=True → show unified diff, write .bak, write new file
  - No existing file → write directly
"""
from __future__ import annotations

import difflib
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.codegen.extract.constitution_extractor import ConstitutionDraft

logger = logging.getLogger(__name__)


class ConstitutionWriter:
    """
    Serialises a ConstitutionDraft to a constitution.md file.
    """

    def write(
        self,
        draft: ConstitutionDraft,
        output_path: str | None = None,
        force: bool = False,
    ) -> None:
        """
        Write draft to constitution.md (or output_path).

        Args:
            draft:       The ConstitutionDraft to serialise.
            output_path: Full output path. Defaults to CWD/constitution.md.
            force:       If True, overwrite existing file (after backup). If False,
                         halt when file already exists.

        Raises:
            FileExistsError: If constitution.md exists and force=False.
        """
        from src.codegen.security.path_safety import PathSafety

        if output_path is None:
            safety = PathSafety(os.getcwd())
            anchored = safety.anchor_output("constitution.md")
        else:
            # Anchor to the directory containing the supplied output path
            output_dir = os.path.dirname(os.path.realpath(output_path))
            safety = PathSafety(output_dir)
            anchored = safety.assert_contained(output_path, supplied_path=output_path)

        new_content = self._render(draft)

        if os.path.exists(anchored):
            if not force:
                raise FileExistsError(
                    f"constitution.md already exists at '{anchored}'. "
                    "Use force=True to overwrite."
                )
            # force=True: show diff, back up, write new
            with open(anchored, encoding="utf-8") as fh:
                existing_content = fh.read()

            diff_lines = list(
                difflib.unified_diff(
                    existing_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile="constitution.md (existing)",
                    tofile="constitution.md (new)",
                )
            )
            if diff_lines:
                print("".join(diff_lines))

            # Write backup
            bak_suffix = datetime.utcnow().strftime("%Y%m%d-%H%M%S-UTC")
            bak_filename = f"constitution.md.bak.{bak_suffix}"
            # anchor_output rejects path separators in filename — use raw join
            bak_path = os.path.join(os.path.dirname(anchored), bak_filename)
            with open(bak_path, "w", encoding="utf-8") as fh:
                fh.write(existing_content)
            logger.info("constitution_writer: backup written to %s", bak_path)

        with open(anchored, "w", encoding="utf-8") as fh:
            fh.write(new_content)

        logger.info("constitution_writer: written to %s", anchored)

    # -----------------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------------

    def _render(self, draft: ConstitutionDraft) -> str:
        """Render the ConstitutionDraft to Markdown."""
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        sources_str = ", ".join(draft.sources_found) if draft.sources_found else "(none)"
        banners_str = "\n".join(f"<!-- {b} -->" for b in draft.banners) if draft.banners else ""

        lines: list[str] = [
            "# Auto-Extracted Constitution",
            f"<!-- generated: {timestamp} -->",
            f"<!-- sources: {sources_str} -->",
            f"<!-- extraction_confidence: {draft.overall_confidence:.2f} -->",
        ]
        if banners_str:
            lines.append(banners_str)
        lines.append("")
        lines.append("## Extracted Rules")
        lines.append("")

        category_s = [r for r in draft.rules if r.category in ("S", "S_HUMAN")]
        category_b = [r for r in draft.rules if r.category == "B"]

        lines.append("### Category S Rules (Auto-Enforceable)")
        if category_s:
            for rule in category_s:
                human_note = " *(requires human predicate)*" if rule.category == "S_HUMAN" else ""
                lines.append(f"- [{rule.source_type}] {rule.raw_text}{human_note}")
        else:
            lines.append("*(no Category S rules extracted)*")
        lines.append("")

        lines.append("### Category B Rules (Advisory)")
        if category_b:
            for rule in category_b:
                source_note = f" *(source: {rule.source})*" if rule.source != "direct" else ""
                lines.append(f"- [{rule.source_type}] {rule.raw_text}{source_note}")
        else:
            lines.append("*(no Category B rules extracted)*")
        lines.append("")

        return "\n".join(lines)
