# Phase: phase1-constitution
# Source: echelon.run.md §3.5 — Constitution Creation
# Agent: speckit-echelon-commander (COMMANDER) internal (calls speckit.constitution)
# Read by: speckit-echelon-commander (COMMANDER) — this is a commander_internal phase

## 3.5 Constitution Creation (Bridge UNDERSTAND → DECIDE)

> **Why here?** Constitution needs UNDERSTAND phase outputs to be meaningful. We now have domain understanding (glossary, mental model, boundaries) and validated assumptions — enough context to establish project principles.

### Check Constitution Status

If `state.json.constitution_status` is `"exists"`:

- Skip to WHAT phase (constitution already established)
- Proceed to section 4

If `state.json.constitution_status` is `"pending"`:

- Continue with constitution creation below

### NEVER Rules

**NEVER write `constitution.md` via Bash directly.** `speckit.constitution` is the only permitted creation path — the same way CARTOGRAPHER must call `speckit.specify` and may not create `spec.md` manually. A Bash-written constitution skips version assignment, date population, template sync, and the Sync Impact Report. If you find yourself writing to `.specify/memory/constitution.md` via the Write or Bash tool instead of the Skill tool, STOP — you are violating this rule.

### Prepare Constitution Context — MANDATORY

**NEVER call `speckit.constitution` before completing all four extractions below.** A constitution created without domain context is a generic template with no project-specific principles — it provides no governance value.

Read each staging file and extract the key data that should drive constitution principles:

**1. Domain context** — read `glossary.md` and `mental-model.md`. Extract:

- The 3–5 core domain concepts
- The primary user/system boundary
- Any domain-specific quality requirements (e.g., "sub-second latency", "GDPR compliance")

**2. Boundaries** — read `boundaries.md`. Extract:

- External systems the project must integrate with
- Hard constraints (what the project must NOT do)
- Security or compliance requirements implied by external boundaries

**3. Assumptions to encode as principles** — read `assumptions.md`. Extract:

- Validated assumptions that should be policy (e.g., "single developer team → prefer simple over clever")
- Invalidated assumptions that need guarding against (e.g., "framework overhead is unacceptable → no runtime frameworks")

**4. User constraints** — from the original user request and `user-intent.md`. Extract:

- Technology preferences stated explicitly
- Autonomy level (banzai → encode "no manual steps")
- Any timeline, scale, or team constraints

After all four extractions, construct the context string for `speckit.constitution`. The quality of the constitution is directly proportional to the specificity of this context — vague input produces generic output.

### Create Constitution via Spec-Kit

**Print:** `[CONSTITUTION] Calling speckit.constitution — extracting principles from UNDERSTAND artifacts`

**Call `speckit.constitution`** with the gathered context, substituting real extracted values (not placeholders):

```text
speckit.constitution

Based on our understanding phase:
- Domain: {actual domain summary from glossary/mental-model — e.g., "single-page interactive demo application with animated UI"}
- Core concepts: {3-5 terms from glossary — e.g., "Fancy Tier, viewport, prefers-reduced-motion"}
- Key constraints: {actual constraints from boundaries — e.g., "no external CDN, 500KB page budget, static hosting only"}
- Team/project context: {from user input — e.g., "solo developer, banzai mode, demo project"}
- Validated assumptions to encode: {actual assumptions — e.g., "no runtime framework, CSS-primary animation"}
- Quality requirements: {domain-specific — e.g., "FCP < 3s, WCAG AA accessibility"}

Please establish the project constitution.
```

Spec-kit will:

- Create `.specify/memory/constitution.md` from template
- Fill in principles based on provided context
- Establish governance rules

### Verify Constitution Created

After `speckit.constitution` completes:

**Print:** `[CONSTITUTION] Verifying constitution.md — checking for unfilled placeholders`

1. Verify `.specify/memory/constitution.md` exists — if missing, the skill failed; STOP and report.
2. Check for unfilled template placeholders:

   ```bash
   grep -E '\[CONSTITUTION_VERSION\]|\[RATIFICATION_DATE\]|\[LAST_AMENDED_DATE\]' \
     .specify/memory/constitution.md && echo "PLACEHOLDERS_FOUND" || echo "CLEAN"
   ```

   If `PLACEHOLDERS_FOUND`: the skill returned without filling the governance header (this is a known failure mode when context is sparse). Fill the knowable fields directly — do NOT re-invoke the skill:

   ```bash
   TODAY=$(date +%Y-%m-%d)
   sed -i '' \
     -e 's/\[CONSTITUTION_VERSION\]/1.0.0/g' \
     -e "s/\[RATIFICATION_DATE\]/$TODAY/g" \
     -e "s/\[LAST_AMENDED_DATE\]/$TODAY/g" \
     .specify/memory/constitution.md
   echo "[CONSTITUTION] Placeholder fix applied: version=1.0.0, date=$TODAY"
   ```

3. Read and store constitution principles in context.
4. Write journal entry:

   ```bash
   # append to reasoning-journal.jsonl
   printf '{"type":"constitution_created","phase":"phase1-constitution","method":"speckit.constitution","placeholders_fixed":%s,"timestamp":"%s"}\n' \
     "$(grep -qE '\[CONSTITUTION_VERSION\]' .specify/memory/constitution.md && echo true || echo false)" \
     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
     >> .specify/squad/reasoning-journal.jsonl
   ```

5. Update `state.json.constitution_status` to `"exists"`.

**Print:** `[CONSTITUTION] Complete ✓`

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

1. **Option A:** If speckit-echelon-golddigger (GOLDDIGGER) ran and extraction artifacts are present (check `state.json.golddigger_artifacts`), derive principles from the domain inventory and hotspot analysis in the revenge extension artifacts.
2. **Option B:** speckit-echelon-scout (SCOUT)'s discovery outputs may include implicit patterns — use these as constitution input
3. Either way, `speckit.constitution` is called with the derived context

**Transition:** `phases[phase1-what]` — see `workflow/definition.yaml`
