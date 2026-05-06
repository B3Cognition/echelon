# Phase: phase1-constitution
# Source: echelon.run.md §3.5 — Constitution Creation
# Agent: COMMANDER internal (calls speckit.constitution)
# Read by: COMMANDER — this is a commander_internal phase

## 3.5 Constitution Creation (Bridge UNDERSTAND → DECIDE)

> **Why here?** Constitution needs UNDERSTAND phase outputs to be meaningful. We now have domain understanding (glossary, mental model, boundaries) and validated assumptions — enough context to establish project principles.

### Check Constitution Status

If `state.json.constitution_status` is `"exists"`:

- Skip to WHAT phase (constitution already established)
- Proceed to section 4

If `state.json.constitution_status` is `"pending"`:

- Continue with constitution creation below

### Prepare Constitution Context

Gather UNDERSTAND findings from `.specify/squad/staging/`:

1. **Domain context:** Extract key concepts from `glossary.md` and `mental-model.md`
2. **Boundaries:** Extract external dependencies and constraints from `boundaries.md`
3. **Assumptions:** Extract validated assumptions that should become principles from `assumptions.md`
4. **User constraints:** Any team size, timeline, tech stack preferences from user input

### Create Constitution via Spec-Kit

**Call `speckit.constitution`** with the gathered context:

```text
speckit.constitution

Based on our understanding phase:
- Domain: {summarize from glossary/mental-model}
- Key constraints: {from boundaries}
- Team/project context: {from user input if provided}
- Validated assumptions to encode: {from assumptions.md}

Please establish the project constitution.
```

Spec-kit will:

- Create `.specify/memory/constitution.md` from template
- Fill in principles based on provided context
- Establish governance rules

### Verify Constitution Created

After `speckit.constitution` completes:

1. Verify `.specify/memory/constitution.md` exists
2. Read and store constitution principles in context
3. Update `state.json.constitution_status` to `"exists"`

### Mode-Specific Behavior

**In `guided` mode:**

- Present constitution draft to user for review before proceeding
- User can modify principles via `speckit.constitution` amendments

**In `semi` mode:**

- Show constitution summary to user
- Proceed unless user explicitly requests changes

**In `banzai` mode:**

- Create constitution automatically
- Log for post-run review

### Brownfield Special Case

For brownfield projects where constitution doesn't exist:

1. **Option A:** If GOLDDIGGER ran and extraction artifacts are present (check `state.json.golddigger_artifacts`), derive principles from the domain inventory and hotspot analysis in the revenge extension artifacts.
2. **Option B:** SCOUT's discovery outputs may include implicit patterns — use these as constitution input
3. Either way, `speckit.constitution` is called with the derived context

**Transition:** `phases[phase1-what]` — see `workflow/definition.yaml`
