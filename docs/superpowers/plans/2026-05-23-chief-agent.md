# CHIEF Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `speckit-echelon-chief` agent that owns constitution creation and amendment, replacing COMMANDER as the dispatcher for `phase1-constitution`, and document two new agent authoring patterns in `CLAUDE.md`.

**Architecture:** A+C — mode-aware agent file (`chief.md`) holds the invariant protocol for Creation and Amendment modes; spec files hold phase-specific dispatching context. CHIEF uses the Skill tool to invoke `speckit.constitution`, identical to how SAGE invokes Understanding skills. ALWAYS/NEVER paired rules replace the NEVER-only convention.

**Tech Stack:** Markdown (agent file, spec file), YAML (extension.yml, definition.yaml), Python (test additions), Bash (placeholder fix in agent protocol).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `extension/agents/control/chief.md` | CHIEF identity, ALWAYS/NEVER rules, Creation + Amendment protocols, echelon_result schema |
| Modify | `extension/extension.yml` | Register `speckit.echelon.chief` under `provides.commands` |
| Modify | `extension/workflow/definition.yaml` | Change `phase1-constitution` agent from `speckit-echelon-commander` to `speckit-echelon-chief`; update description |
| Modify | `extension/workflow/phases/phase1-constitution.md` | Thin to dispatcher + phase contract only; remove how-to-invoke content |
| Modify | `extension/agents/control/commander.md` | Update governance line to reflect CHIEF owns constitution creation; remove any creation instructions |
| Modify | `CLAUDE.md` | Add `## Agent Authoring Patterns` section with Dispatcher/Protocol Split and ALWAYS/NEVER Pairs |
| Modify | `tests/integration/test_squad_controller.py` | Add `TestConstitutionPhase` verifying phase1-constitution is agent type dispatching CHIEF |

---

### Task 1: Create `extension/agents/control/chief.md`

**Files:**
- Create: `extension/agents/control/chief.md`

- [ ] **Step 1: Write the agent file**

Create `extension/agents/control/chief.md` with the following exact content:

```markdown
---
name: speckit-echelon-chief
description: CHIEF — project constitution author and governance steward
model: claude-sonnet-4-6
tools: Read Write Edit Bash Glob Grep
color: blue
---

## Role

You are CHIEF, the sole author of the project constitution. You have exactly
one job: create and amend `.specify/memory/constitution.md` using the
`speckit.constitution` skill. You do not orchestrate other agents, produce
spec/plan/task artifacts, or make routing decisions.

---

## ALWAYS / NEVER Rules

### Rule 1 — Invocation
ALWAYS invoke `speckit.constitution` (via the Skill tool) to write or update the constitution.
NEVER write `constitution.md` via the Write or Edit tools without first invoking `speckit.constitution`.

### Rule 2 — Context
ALWAYS extract concrete, project-specific context from the provided staging inputs and pass it to the skill.
NEVER call `speckit.constitution` with empty, generic, or placeholder context strings.

### Rule 3 — Verification
ALWAYS verify the output file exists and contains no unfilled placeholders after the skill completes.
NEVER assume the skill succeeded without reading the result file.

### Rule 4 — Amendment
ALWAYS read the current `.specify/memory/constitution.md` before making any amendment.
NEVER amend without loading the existing constitution first.

---

## Modes

The dispatching spec file declares which mode to operate in. Select the
matching protocol below.

---

### Creation Mode

**Entry condition:** `.specify/memory/constitution.md` does not exist or still
contains the blank template marker `[PROJECT_NAME]`.

**Protocol:**

1. **Read the five context-pack files** provided in your prompt:
   - `glossary.md` — extract the 3–5 core domain concepts
   - `mental-model.md` — extract the primary user/system boundary and behavioural patterns
   - `boundaries.md` — extract hard constraints (what the project must NOT do), compliance requirements, external integrations
   - `assumptions.md` — identify validated assumptions that should become encoded principles
   - `user-intent.md` — extract technology preferences, autonomy level, team/scale constraints

2. **Build the context string** — concrete values only, no placeholders:
   ```
   Based on our understanding phase:
   - Domain: {3-5 core domain concepts from glossary + mental-model}
   - Key constraints: {hard constraints from boundaries — specific, not generic}
   - Team/project context: {from user-intent — solo/team, mode, scale}
   - Validated assumptions to encode: {from assumptions.md — specific decisions}
   - Quality requirements: {domain-specific non-functionals, e.g. "offline-first", "COPPA-K compliance"}
   ```

3. **Invoke `speckit.constitution`** via the Skill tool with the assembled context string.

4. **Verify the result:**
   ```bash
   ls -la .specify/memory/constitution.md && \
   grep -E '\[PROJECT_NAME\]|\[PRINCIPLE_1_NAME\]' .specify/memory/constitution.md \
     && echo "PLACEHOLDERS_FOUND" || echo "CLEAN"
   ```

5. **Fix remaining placeholders** if `PLACEHOLDERS_FOUND`:
   ```bash
   TODAY=$(date +%Y-%m-%d)
   sed -i '' \
     -e 's/\[CONSTITUTION_VERSION\]/1.0.0/g' \
     -e "s/\[RATIFICATION_DATE\]/$TODAY/g" \
     -e "s/\[LAST_AMENDED_DATE\]/$TODAY/g" \
     -e 's/\[PROJECT_NAME\]/'"$(basename "$PWD")"'/g' \
     .specify/memory/constitution.md
   echo "[CHIEF] Placeholder fix applied"
   ```

6. **Emit `echelon_result`** (see Output Block below).

---

### Amendment Mode

**Entry condition:** `.specify/memory/constitution.md` exists with real content.
A specific amendment is required (scope change, new architectural constraint,
or gap identified by SAGE/GATEKEEPER).

**Protocol:**

1. **Read the current constitution** (mandatory — never skip):
   ```bash
   cat .specify/memory/constitution.md
   ```

2. **Read the amendment trigger** provided in the context: change description,
   scope delta, or gap report. Identify the specific principle(s) to add or modify.

3. **Build a targeted amendment context string** — describe only the change,
   not the full project. Example:
   ```
   Amendment: add principle for offline-first data persistence.
   Current principles: [list from reading constitution].
   New constraint: server costs must stay under $50/month/MAU.
   ```

4. **Invoke `speckit.constitution`** with the targeted amendment context.

5. **Verify the amendment:**
   - Confirm the new principle appears in the constitution
   - Confirm no unintended principles were altered (diff mentally against what you read in step 1)

6. **Emit `echelon_result`** (see Output Block below).

---

## Completion Signal

```
CHIEF COMPLETE
Mode: <Creation | Amendment>
Constitution: .specify/memory/constitution.md
Status: <created | amended>
Placeholders fixed: <yes | no | n/a>
```

---

## Belief Register

Calibration beliefs are in `${PROJECT_ROOT}/.specify/extensions/echelon/config/belief-registers/chief.yaml`.
Read this file before proceeding if it exists. If absent, proceed with defaults.

---

## Output Block

At the end of your response, append this block exactly.
speckit-echelon-commander (COMMANDER) reads this block to update journal and
state. Do NOT write to `reasoning-journal.jsonl` directly.

echelon_result:
  verdict: DONE
  output_files:
    - .specify/memory/constitution.md
  state_updates:
    constitution_status: <exists | amended>
  journal_entries:
    - id: null
      type: constitution_created
      phase: phase1-constitution
      agent: CHIEF
      timestamp: null
      data:
        mode: <Creation | Amendment>
        constitution_path: .specify/memory/constitution.md
        placeholder_fix_applied: <true | false>
```

- [ ] **Step 2: Verify file created**

```bash
wc -l extension/agents/control/chief.md
grep -c "ALWAYS\|NEVER" extension/agents/control/chief.md
```

Expected: ~120 lines, 8 ALWAYS/NEVER matches (4 pairs).

- [ ] **Step 3: Commit**

```bash
git add extension/agents/control/chief.md
git commit -m "feat: add speckit-echelon-chief agent for constitution creation and amendment"
```

---

### Task 2: Register CHIEF in `extension/extension.yml`

**Files:**
- Modify: `extension/extension.yml` (after line with `speckit.echelon.commander` entry, ~line 163)

- [ ] **Step 1: Write a failing test**

```python
# In tests/kernel/test_phase_graph.py (new test at end of file)
def test_chief_registered_in_extension():
    """CHIEF must be registered in extension.yml so phase_graph resolves it."""
    import yaml
    from pathlib import Path
    ext = yaml.safe_load(
        (Path(__file__).parent.parent.parent / "extension/extension.yml").read_text()
    )
    commands = ext.get("provides", {}).get("commands", [])
    names = [c["name"] for c in commands]
    assert "speckit.echelon.chief" in names, "speckit.echelon.chief not in extension.yml provides.commands"
    chief = next(c for c in commands if c["name"] == "speckit.echelon.chief")
    assert chief["file"] == "agents/control/chief.md"
    assert chief["behavior"]["execution"] == "agent"
```

Run: `pytest tests/kernel/test_phase_graph.py::test_chief_registered_in_extension -v`
Expected: FAIL — `speckit.echelon.chief not in extension.yml provides.commands`

- [ ] **Step 2: Add CHIEF to `extension/extension.yml`**

After the `speckit.echelon.commander` entry (around line 170), insert:

```yaml
    - name: "speckit.echelon.chief"
      file: "agents/control/chief.md"
      description: "CHIEF — project constitution author and governance steward"
      behavior:
        execution: agent
        capability: balanced
        tools: full          # needs Skill (speckit.constitution) + Bash (verification) + Write (placeholder fix)
        color: blue
        invocation: explicit
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/kernel/test_phase_graph.py::test_chief_registered_in_extension -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add extension/extension.yml tests/kernel/test_phase_graph.py
git commit -m "feat: register speckit-echelon-chief in extension.yml"
```

---

### Task 3: Update `definition.yaml` — wire CHIEF into `phase1-constitution`

**Files:**
- Modify: `extension/workflow/definition.yaml` (~line 365, the `phase1-constitution` block)

- [ ] **Step 1: Write a failing test**

```python
# In tests/kernel/test_phase_graph.py
def test_phase1_constitution_uses_chief():
    """phase1-constitution must dispatch CHIEF, not COMMANDER."""
    import yaml
    from pathlib import Path
    from harness.phase_graph import PhaseGraph
    EXT_ROOT = Path(__file__).parent.parent.parent
    graph = PhaseGraph(
        EXT_ROOT / "extension/workflow/definition.yaml",
        EXT_ROOT / "extension/extension.yml",
    )
    node = graph.get("phase1-constitution")
    assert node.type == "agent", f"Expected type=agent, got {node.type!r}"
    assert node.agent == "speckit-echelon-chief", f"Expected speckit-echelon-chief, got {node.agent!r}"
    # Must resolve to an actual file
    rel = graph.agent_file("speckit-echelon-chief")
    assert rel is not None, "speckit-echelon-chief not resolved by agent_file()"
    assert rel == "agents/control/chief.md"
```

Run: `pytest tests/kernel/test_phase_graph.py::test_phase1_constitution_uses_chief -v`
Expected: FAIL — agent is `speckit-echelon-commander`, not `speckit-echelon-chief`

- [ ] **Step 2: Update `definition.yaml`**

In the `phase1-constitution` block, change:
```yaml
    agent: speckit-echelon-commander
    tier: control
    context_pack:
      ...
    description: >
      speckit-echelon-commander (COMMANDER) calls the speckit.constitution Skill
      ...
```

To:
```yaml
    agent: speckit-echelon-chief
    tier: control
    context_pack:
      - .specify/squad/staging/glossary.md
      - .specify/squad/staging/mental-model.md
      - .specify/squad/staging/boundaries.md
      - .specify/squad/staging/assumptions.md
      - .specify/squad/staging/user-intent.md
    description: >
      speckit-echelon-chief (CHIEF) invokes the speckit.constitution Skill
      to create constitution.md from UNDERSTAND artifacts. CHIEF extracts domain
      context, calls the skill, verifies output, and fixes placeholders if needed.
      See phase1-constitution.md for phase contract; chief.md for full protocol.
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/kernel/test_phase_graph.py::test_phase1_constitution_uses_chief -v`
Expected: PASS

- [ ] **Step 4: Run full kernel suite**

Run: `pytest tests/kernel/ -q`
Expected: all passing

- [ ] **Step 5: Commit**

```bash
git add extension/workflow/definition.yaml tests/kernel/test_phase_graph.py
git commit -m "feat: wire speckit-echelon-chief into phase1-constitution"
```

---

### Task 4: Thin `phase1-constitution.md` to dispatcher + contract

**Files:**
- Modify: `extension/workflow/phases/phase1-constitution.md`

- [ ] **Step 1: Replace the file content**

Overwrite `extension/workflow/phases/phase1-constitution.md` with:

```markdown
# Phase: phase1-constitution
# Agent: speckit-echelon-chief (CHIEF)
# Mode: Creation

> **Dispatcher contract** — this file tells CHIEF what to read, what mode to
> operate in, and what to produce. It does NOT describe how CHIEF invokes the
> skill or verifies output — that invariant protocol lives in `chief.md`.

## Dispatch

You are CHIEF. Operate in **Creation mode**.

The five staging files in your context pack (glossary, mental-model, boundaries,
assumptions, user-intent) are your raw material. Follow your Creation mode
protocol from `chief.md` exactly.

## Expected Output

- `.specify/memory/constitution.md` — filled, verified, no unfilled placeholders

## State Contract

The harness reads `state_updates.constitution_status` to record that the
constitution was created. Emit:

```yaml
state_updates:
  constitution_status: "exists"
```

## echelon_result Contract

```yaml
echelon_result:
  verdict: DONE
  output_files:
    - .specify/memory/constitution.md
  state_updates:
    constitution_status: "exists"
```

## Mode-Specific Notes

- If `.specify/memory/constitution.md` already exists with real content (no
  `[PROJECT_NAME]` marker), the constitution was previously created. Emit
  `verdict: DONE` immediately without re-invoking the skill.
- `constitution_status: "exists"` in state.json skips this phase on subsequent
  runs — the harness will not re-dispatch CHIEF for creation.
```

- [ ] **Step 2: Verify the file is thin**

```bash
wc -l extension/workflow/phases/phase1-constitution.md
```

Expected: under 55 lines. If it still contains "NEVER write via Bash" or "call speckit.constitution with" instructions, those are protocol content that belongs in `chief.md` — remove them.

- [ ] **Step 3: Commit**

```bash
git add extension/workflow/phases/phase1-constitution.md
git commit -m "refactor: thin phase1-constitution.md to dispatcher/contract only"
```

---

### Task 5: Update `commander.md` — constitution governance line

**Files:**
- Modify: `extension/agents/control/commander.md` (line 57)

- [ ] **Step 1: Update the governance line**

Find line 57 in `extension/agents/control/commander.md`:
```
The constitution is the highest authority. No agent may override it. Any conflict → route back to the agent to revise. Constitution gaps → human escalation via `speckit.constitution`. Only humans amend the constitution.
```

Replace with:
```
The constitution is the highest authority. No agent may override it. Any conflict → route back to the agent to revise. Constitution creation and amendment is CHIEF's responsibility — do not invoke `speckit.constitution` directly. Constitution gaps identified during runtime → dispatch CHIEF in Amendment mode.
```

- [ ] **Step 2: Verify the change**

```bash
grep -n "constitution\|CHIEF" extension/agents/control/commander.md
```

Expected: line 57 now references CHIEF; no `speckit.constitution` invocation instructions remain.

- [ ] **Step 3: Commit**

```bash
git add extension/agents/control/commander.md
git commit -m "refactor: update commander.md — constitution ownership transferred to CHIEF"
```

---

### Task 6: Add `## Agent Authoring Patterns` to `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (append new section at end)

- [ ] **Step 1: Append the patterns section**

At the end of `CLAUDE.md`, add:

```markdown
## Agent Authoring Patterns

Established patterns for writing echelon agent and phase spec files. Apply to
all new agents; adopt in existing agents when next revised.

### Dispatcher / Protocol Split

> The spec file is the dispatcher + phase contract. The agent file is the invariant protocol.

A phase spec file (e.g. `workflow/phases/phase1-constitution.md`) owns:
- **What to read** — context pack (which files)
- **What mode** — Creation, Amendment, WHY1, ASSESS2, etc.
- **What to produce** — expected output filenames
- **What state to write** — `state_updates` keys the harness reads
- **What echelon_result to emit** — routing contract

A phase spec file must NOT describe how the agent does its work internally —
that belongs in the agent file. Violations cause protocol drift: the same logic
appears in two places and diverges over time (e.g. filename changes that only
land in one location).

The agent file owns the invariant protocol: identity, NEVER rules, reasoning
steps, tool invocation sequences, verification logic, output block schema.

### ALWAYS / NEVER Pairs

> Every behavioural rule in an agent file has both a positive and a negative form.

The ALWAYS form states what good behaviour looks like (positive motivation,
aligned with Anthropic prompting best-practices). The NEVER form closes the
escape route and prevents rationalisation. Together they form a complete
behavioural contract.

Format:
```
ALWAYS [positive behaviour — what the agent should reach for]
NEVER  [its violation — what must not happen]
```

Example (from CHIEF):
```
ALWAYS invoke `speckit.constitution` to write or update the constitution.
NEVER write `constitution.md` via Write or Edit without first invoking `speckit.constitution`.
```

Existing agents only have NEVER rules. New agents must have paired rules.
Existing agents adopt paired rules when next revised.
```

- [ ] **Step 2: Verify**

```bash
grep -c "ALWAYS / NEVER\|Dispatcher / Protocol" CLAUDE.md
```

Expected: 2

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add agent authoring patterns to CLAUDE.md (Dispatcher/Protocol Split, ALWAYS/NEVER Pairs)"
```

---

### Task 7: Integration test — CHIEF dispatched for phase1-constitution

**Files:**
- Modify: `tests/integration/test_squad_controller.py` (append new class)

- [ ] **Step 1: Write the test**

Append to `tests/integration/test_squad_controller.py`:

```python
class TestConstitutionPhase:
    """Regression: phase1-constitution must dispatch CHIEF (agent), not be a no-op."""

    def test_phase1_constitution_is_agent_not_commander_internal(self, tmp_path):
        """phase1-constitution must be type=agent so CHIEF gets dispatched."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        node = graph.get("phase1-constitution")
        assert node.type == "agent", (
            f"phase1-constitution must be type=agent (so CHIEF is dispatched by the harness). "
            f"Got: {node.type!r}. commander_internal silently skips the phase."
        )

    def test_phase1_constitution_agent_is_chief_not_commander(self, tmp_path):
        """phase1-constitution must dispatch CHIEF, not COMMANDER."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        node = graph.get("phase1-constitution")
        assert node.agent == "speckit-echelon-chief", (
            f"phase1-constitution must dispatch speckit-echelon-chief. "
            f"Got: {node.agent!r}. COMMANDER must not own constitution creation."
        )

    def test_chief_resolves_to_agent_file(self, tmp_path):
        """speckit-echelon-chief must resolve to a real agent file path."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        rel = graph.agent_file("speckit-echelon-chief")
        assert rel == "agents/control/chief.md", (
            f"speckit-echelon-chief should resolve to agents/control/chief.md. "
            f"Got: {rel!r}. Check extension.yml provides.commands registration."
        )
        agent_path = EXT_ROOT / "extension" / rel
        assert agent_path.exists(), f"Agent file not found: {agent_path}"

    def test_chief_has_constitution_context_pack(self, tmp_path):
        """phase1-constitution must include staging artifacts in context_pack."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        node = graph.get("phase1-constitution")
        pack = " ".join(node.context_pack)
        assert "glossary" in pack
        assert "mental-model" in pack
        assert "boundaries" in pack
        assert "assumptions" in pack
        assert "user-intent" in pack

    def test_chief_dispatched_in_controller(self, tmp_path):
        """SquadController dispatches an agent (not no-op) for phase1-constitution."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-constitution")
        ctrl.run("msg", "banzai")
        # AgentExecutor calls exec_agent; CommanderInternalExecutor does not.
        assert provider.exec_agent.called, (
            "exec_agent was not called — phase1-constitution is still a harness no-op. "
            "It must be type=agent so CHIEF gets dispatched."
        )
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/integration/test_squad_controller.py::TestConstitutionPhase -v`
Expected: all 5 PASS

- [ ] **Step 3: Run full suite**

Run: `pytest tests/kernel/ tests/integration/test_squad_controller.py -q`
Expected: all passing

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_squad_controller.py
git commit -m "test: verify phase1-constitution dispatches CHIEF agent"
```

---

## Self-Review

**Spec coverage check:**
- ✓ `chief.md` created with ALWAYS/NEVER pairs, Creation + Amendment modes
- ✓ `extension.yml` registration (Task 2)
- ✓ `definition.yaml` wired to `speckit-echelon-chief` (Task 3)
- ✓ `phase1-constitution.md` thinned to dispatcher/contract (Task 4)
- ✓ `commander.md` governance line updated (Task 5)
- ✓ `CLAUDE.md` patterns documented (Task 6)
- ✓ Integration tests for all four contract points (Task 7)
- ✓ Amendment mode protocol in `chief.md` (spec requires both modes)
- ✓ Placeholder fix fallback in Creation protocol

**Placeholder scan:** No TBD, TODO, or vague steps. Every step has exact file paths, exact content, and exact test commands.

**Type consistency:** `speckit-echelon-chief` used consistently across all tasks. `constitution_status` state key used consistently. `verdict: DONE` consistent with other non-WHY agents.

**Out-of-scope preserved:** Amendment wiring into `echelon change` and banzai escalation deferred per spec.
