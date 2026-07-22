# Echelon Workflow Web Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the card-based Echelon workflow export with a standalone Mermaid-based page that visibly renders every forward path and feedback loop.

**Architecture:** A single standalone HTML document contains accessible view tabs, embedded Mermaid graph definitions, a version-pinned Mermaid module, and small local controls for zoom and reset. Rendering is isolated per tab so a failure in one graph leaves the other views usable and preserves readable graph source as a fallback.

**Tech Stack:** HTML5, CSS, JavaScript ES modules, Mermaid 11.4.1 from jsDelivr.

## Global Constraints

- Modify `/Users/michalbachorik/work/echelon_r/echelon-workflow.html` only for the exported page.
- Keep Overview, Phase A, Build, Delivery, and Brownfield RE views.
- Use solid edges for normal transitions and dashed edges for repair or repetition.
- Show conditions and bounds directly on feedback edges.
- Use a light neutral background and responsive diagrams.
- Preserve keyboard-accessible tabs and zoom controls.
- Leave readable Mermaid source and an error message if rendering fails.

---

### Task 1: Mermaid diagram export

**Files:**
- Modify: `/Users/michalbachorik/work/echelon_r/echelon-workflow.html`

**Interfaces:**
- Consumes: the approved workflow graph in `extension/workflow/definition.yaml` and harness loops under `src/harness/`
- Produces: five `<section role="tabpanel">` elements containing `.mermaid` graph definitions and `.diagram-controls`

- [ ] **Step 1: Record structural assertions that fail against the card export**

Run:

```bash
rg -q 'mermaid@11.4.1' ../echelon-workflow.html && rg -q -- '-\.->' ../echelon-workflow.html
```

Expected: non-zero exit because the existing page has neither Mermaid nor explicit dashed graph edges.

- [ ] **Step 2: Replace the page with the Mermaid implementation**

Write a standalone document with five embedded flowcharts, tab semantics, light theme variables, edge-label conditions, gate/terminal/escalation classes, error fallbacks, and zoom/reset controls.

- [ ] **Step 3: Run structural verification**

Run:

```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('../echelon-workflow.html').read()); p.close()"
rg -c 'class="mermaid"' ../echelon-workflow.html
rg -q 'mermaid@11.4.1' ../echelon-workflow.html
rg -q -- '-\.->' ../echelon-workflow.html
```

Expected: HTML parse succeeds, Mermaid count is `5`, and both searches succeed.

### Task 2: Browser verification and correction

**Files:**
- Modify if required: `/Users/michalbachorik/work/echelon_r/echelon-workflow.html`

**Interfaces:**
- Consumes: completed standalone page from Task 1
- Produces: visually verified diagrams with working tabs and zoom controls

- [ ] **Step 1: Open or reload the local page in the in-app browser**

Expected: Overview renders on a light background with visible arrowheads and dashed feedback edges.

- [ ] **Step 2: Exercise every tab and zoom control**

Expected: all five graphs render; selected-tab state updates; zoom in, zoom out, and reset visibly change only the active diagram.

- [ ] **Step 3: Inspect desktop and narrow layouts**

Expected: labels remain readable, controls wrap, and diagram overflow stays inside its viewport.

- [ ] **Step 4: Check browser errors and correct any Mermaid syntax or runtime failures**

Expected: no page errors, Mermaid parsing failures, or undefined identifiers.

