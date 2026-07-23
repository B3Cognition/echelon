# Phase A Provider-Neutral Capability Language

**Tracking:** GitHub issue #177

## Goal

Keep canonical Phase A agent prompts independent of Claude-native tool names while
preserving their artifact, research, and delegation responsibilities across CLI and
OpenAI-compatible providers.

## Boundary

Canonical Phase A agent bodies and phase specifications may describe what capability is
required, such as workspace artifact inspection, targeted artifact amendment,
public-web search, URL retrieval, isolated experimentation, or delegated-agent
dispatch. They must not name provider-native interfaces such as `WebSearch`,
`WebFetch`, `ToolSearch`, `Bash tool`, `Agent tool`, or the
`Read`/`Write`/`Edit` tool APIs and their arguments. Phase specifications are included
because the harness appends them to the executing agent's runtime prompt.

Ordinary verbs remain valid: prompts still say to read evidence, write an artifact, or
edit a requirement. Frontmatter remains runtime metadata and is outside this prose
contract. Shell-based controller timing and preflight migration remains issue #178.

## Behavior

- CARTOGRAPHER and SAGE inspect an existing artifact before amendment and identify a
  unique target span without referring to provider-specific mutation APIs.
- SCOUT and INVESTIGATOR use the public-web research capabilities exposed for the
  dispatch and report unavailable capabilities instead of inventing evidence.
- INVESTIGATOR runs a spike only when the dispatch exposes an isolated experiment
  capability; otherwise it skips the remaining experiment steps and does not imply
  measurements. It returns a structured `BLOCKED` result when missing research
  capabilities leave insufficient evidence for a defensible conclusion.
- COMMANDER requests delegated evidence only through a runtime-exposed delegation
  capability and fails closed when it is unavailable.
- ARCHITECT describes forbidden provider connector discovery generically rather than
  naming a provider's discovery tool.
- Phase specifications describe runtime dispatch without embedding a provider-native
  dispatch API in the effective agent prompt.

## Regression Contract

A static scanner checks the Markdown body of every canonical Phase A agent under
`control`, `exploration`, `feasibility`, `learning`, `solution`, and `specialists`,
plus the `phase1-*`, `phase2-*`, `phase3-*`, `phase4-*`, and `phase-exp-*`
specifications that the harness can append at runtime. It rejects provider-native
identifiers and API-shaped phrases, including direct invocation syntax, while
deliberately accepting ordinary artifact verbs and ignoring YAML frontmatter.

## Verification

Focused scanner unit tests prove positive and negative cases. The repository-wide
prompt contract test proves the current Phase A prompt set is neutral, followed by the
existing prompt, workflow, and full Python suites.
