# PR-triage Prosaic migration

## Status and scope

Architecture approved in conversation: use the existing ReviewLoopController to
sequence provider-neutral review roles for Claude and Codex, without a new
orchestration framework. The user additionally approved a triage-only,
harness-validated file-reading channel to preserve the no-shell/no-network-tool
restriction. This document records the concrete implementation contract. The
scoped implementation is complete on `fix/delivery-controller-contract` and
independently accepted through code commit `602ee524`, including final review
fixes. Acceptance covers local contracts and scripted provider integration, not
live-provider behavior, installation, or activation. Verification and the known
baseline policy-test exception are recorded in the convergence audit.

This checkpoint finishes the missed active PR-triage consumer migration before
returning to delivery convergence. It does not change legacy `echelon build`,
fulfillment, source-repair feedback, developer AGENTS.md/CLAUDE.md, identity
machinery, workspace installation, or default rollout. No live provider run,
workspace migration, push, or merge is part of implementation verification.

## Why this is necessary

The top-level review command already uses Prosaic. Its nested diagnostic loader
still reads `.claude/agents`, and `review_triage_v1` deliberately only accepts
Claude. The August Prosaic migration stopped producing those provider-native
files without migrating this consumer. Tests created the old files themselves.

Changing a path or removing the provider rejection is insufficient. Existing
Codex exclusive filesystem scopes do not remove shell/network tools. Its
constrained operation disables those tools, but cannot read source by itself.

## Ownership

- ReviewLoopController retains comment acquisition, grouping, role sequence,
  attempt deadline, and the existing publication/recovery lifecycle.
- Prosaic parses neutral role and composition artifacts on demand. Echelon never
  interprets provider-native prose directories as runtime role sources.
- A triage-local read channel validates model-requested reads. It has no shell,
  execution, write, network, agent-dispatch, or publication operation.
- The provider facade exposes a triage-only no-tools turn. Provider adapters own
  native flags, model/effort mapping, output extraction, and isolation.
- ReviewArtifactPublisher remains the only canonical artifact publisher. Its
  lock, allocation, task validation, journal, recovery, and PR-effect ordering
  remain authoritative.

## Neutral prose

Add three bounded neutral subagents: `echelon.review-debugger`,
`echelon.review-sentinel`, and `echelon.review-spec-guard`. They respectively
produce root-cause/fix-scope analysis, a failing-test/regression specification,
and requirement/scope analysis. They do not inherit the general roles' commands
to implement fixes, execute tests, write reports, or dispatch other agents.

Reduce `echelon.review` to composition of already diagnosed, host-grouped input.
It is not COMMANDER and does not group comments, dispatch roles, allocate IDs,
write files, fetch comments, or publish. Python supplies the response schema and
the allocated names/IDs. The prose contains neither provider branches nor
delivery routing/retry instructions. Missing new prose fails closed; there is
no fallback to old bundles or provider-native files.

Capture exactly these four bundle artifacts through descriptor-pinned,
no-follow reads, then inspect the captured files through Prosaic in a private
temporary bundle. Do not replace Prosaic with a local frontmatter parser. These
bounded artifacts are self-contained: reject package companion references so
the inspector cannot reopen mutable worktree paths or expand the prompt into
unrelated workflows. Bound each captured artifact to 128 KiB.

## Triage-only read channel

The host opens the supplied worktree and canonical spec roots once, without
following symlink components. Model requests use a logical root (`worktree` or
`spec`) and a relative path; they never supply a new root.

Two read operations are supported:

- `read_file`: UTF-8 text, explicit one-based start line and line count. Maximum
  200 lines and 64 KiB returned per request; regular files only, maximum source
  file size 1 MiB. Oversized or binary files return an explicit unavailable
  result rather than silently incomplete evidence.
- `list_directory`: one directory, sorted names and regular-file/directory
  types, without recursion or symlink traversal. At most 500 entries; larger
  directories return an explicit unavailable result.

Reject absolute paths, empty/intermediate-dot components, traversal, NULs,
unknown roots/operations/fields, booleans in integer fields, symlinks at every
component, special files, and hard-linked regular files. Open relative to the
pinned descriptors, not by resolving and reopening a pathname. Root replacement
must not redirect a read. Neither operation follows instructions found in files.
Source content is framed as untrusted evidence in subsequent turns.

At most 32 read requests are allowed per role invocation; requests consume that
budget even when unavailable or denied. At most 1 MiB of accumulated input and
256 KiB of captured provider output are allowed per turn. No recursive scan,
glob, search service, workspace snapshot subsystem, or generic capability
compiler is introduced. The existing review timeout is one monotonic deadline
for the entire attempt, not a fresh timeout for every read/role/group.

## Provider execution

Expose a dedicated triage-turn operation through the existing provider facade.
Only Claude and Codex implement it. Unsupported providers or unavailable
required isolation fail before model launch; never fall back to general
run_prompt/run_agent execution. Both providers run in a private empty directory
without product or staging paths mounted as model-accessible context.

Codex reuses its existing bounded constrained-request machinery. Claude gets a
triage-only no-tools execution path with empty native tool inventory, no native
agents, ambient project/user instructions, plugins, hooks, MCP, or bypass mode.
Do not advertise Claude as implementing the generic constrained RE capability:
this change must not enable unrelated consumers. Both adapters enforce bounded
input/output and deadlines and reject unexpected tool execution events.

The no-network restriction concerns model-accessible tools and arbitrary
requests; the provider's authenticated model API connection remains necessary.
No model shell, browser, web search, or arbitrary network tool is available.
Provider-specific controls stay in adapters, never neutral prose.

## Attempt flow and outcomes

1. Recover any accepted publication through the existing publisher before new
   model work. Otherwise allocate using the current allocator.
2. Group comments deterministically, oldest first, with comment ID as a tie
   breaker. Inline same-path comments connect when their line distance is at
   most the configured threshold. Review-level same-reviewer comments connect
   within sixty seconds. Connected components form groups; other comments are
   singleton groups. Do not combine inline and review-level comments.
3. For each group, invoke debugger, sentinel, then spec guard in that order.
   Each receives the group and completed earlier results; read requests are
   serviced only by the bounded channel. Roles cannot select the next role.
4. After every group has valid diagnostic results, invoke the neutral
   composition command once. It returns a JSON envelope containing proposed
   artifact text, task-append text, and the existing manifest shape.
5. Validate the envelope's exact fields and allocated names before any staging
   write. Python writes only the allocated staging artifacts, tasks-append.md,
   and status manifest; it does not interpret model-selected destinations.
6. Call the existing publisher's manifest acceptance. Canonical publication and
   subsequent PR effects retain the current recovery contract.

Malformed responses, invalid operations, insufficient diagnostic context,
exhausted limits, provider errors, and timeouts block the attempt. They must not
be converted into `no_blocking_comments`, clear seen-comment state, publish a
partial batch, or invoke a less restricted provider path. An empty input can
produce the existing empty manifest without model work. An unaccepted attempt
may be retried under the existing outer lifecycle; no new per-role recovery
journal is introduced. All provider calls, including failed turns, contribute
their reported usage or a clearly identified fallback estimate.

## Verification checkpoints

1. Read-channel tests: valid reads/listing, traversal, symlink and root-swap
   races, hard links, special/binary/oversized files, malformed requests, byte
   and request limits. Tests exercise real temporary files and descriptors.
2. Prosaic/provider tests: a clean Prosaic-only bundle succeeds; missing or
   unsafe artifacts block; inspection is used; both adapters launch only their
   no-tools path; unsupported providers/hosts/configuration fail closed;
   malicious output cannot enable tools. Script only external processes.
3. Controller tests: deterministic grouping, exact role order, evidence carried
   between turns, one attempt deadline, usage on failure, validated staging,
   rejected partial results, and unchanged publication/recovery/PR ordering.
4. Run the affected existing review, publisher, provider, and adapter suites
   once together. Independently review the diff before the implementation
   commit. Do not represent scripted process tests as live provider proof.

## Integration boundary

Implementation belongs in the existing convergence worktree on
`fix/delivery-controller-contract`. Keep commits limited to this checkpoint.
Record verified results and remaining live-validation limitations in the
convergence boundary document before returning to the original work.
