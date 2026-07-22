# Echelon Workflow Web Export Design

## Goal

Replace the card-based standalone workflow page with a diagram-first export that preserves the structure and readability of the Markdown Mermaid presentation. The page must make forward transitions, repair loops, conditional returns, and loop bounds visible without requiring a separate textual loop list.

## Scope

Update `/Users/michalbachorik/work/echelon_r/echelon-workflow.html`. Keep it as a standalone local HTML page with five views:

- Overview
- Phase A
- Build
- Delivery
- Brownfield RE

The underlying workflow content remains based on Echelon commit `af0998b` from 2026-07-22. This change affects presentation only.

## Design

Use Mermaid flowcharts embedded in the page. Each view owns one Mermaid graph and is selected through a compact tab bar. The selected graph occupies the dominant page area.

Visual conventions:

- Light neutral page background, matching the readability of rendered Markdown.
- Rectangular nodes with restrained fills and borders.
- Solid arrows for normal forward transitions.
- Dashed arrows for repair, retry, verification, and re-entry loops.
- Edge labels state the exact triggering condition or bound in concise language.
- Phase or lifecycle groupings use Mermaid subgraphs.
- Gate nodes receive a subtle blue treatment; terminal states receive a subtle green treatment; escalation receives a subtle red treatment.
- A small legend repeats these conventions.

Mermaid is loaded from a version-pinned jsDelivr CDN module. Graph definitions are embedded in the document, and the page performs no data fetching beyond loading Mermaid itself.

## Interaction

The page initially displays Overview. Selecting a tab reveals and renders the corresponding graph while hiding the others. Tabs remain keyboard accessible and expose their selected state through `aria-selected`.

Each graph receives zoom controls for zoom in, zoom out, and reset. Zoom is implemented by applying a transform to the rendered Mermaid SVG; the graph remains centered and can overflow inside a bounded diagram viewport when enlarged.

The initial rendering must remain useful without interaction. Graphs use responsive SVG sizing and preserve their view boxes.

## Content Model

The diagrams encode the executable graph currently defined in `extension/workflow/definition.yaml` and the nested delivery loops implemented under `src/harness/`:

- Phase A includes the deterministic Understanding nodes after Requirements and Planning.
- Phase A includes WHY1, WHY2, feasibility, alignment, planning, and consensus feedback paths.
- Build includes task-level quality-gate repair returns, task/group repetition, integration repair, and documentation verification.
- Delivery includes the inner fix–verify loop, outer build loop, optional visual loop, and PR review re-entry.
- Brownfield RE includes the coverage verify–expand loop.

## Failure Handling

If Mermaid cannot load or a graph fails to render, the page leaves the graph source visible in a readable fallback block and shows a short rendering-error message. Tab switching and the rest of the page continue to work.

## Verification

- Open the file locally and confirm all five diagrams render.
- Confirm every diagram contains visible arrowheads and labeled dashed feedback edges.
- Confirm tabs, zoom controls, and reset work with mouse and keyboard.
- Inspect at desktop and narrow widths for clipping or unreadable labels.
- Confirm the browser console contains no JavaScript or Mermaid parsing errors.
- Compare the Build view with the supplied screenshot and verify that the repair arrows returning to IMPLEMENTER are explicit.
