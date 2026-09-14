# Host-serviced inspection boundary

Status: reuse-based approach approved in conversation; recorded design and
implementation plan prepared for the next execution checkpoint.
Baseline: `bfd722cb`, `fix/delivery-controller-contract`.

## Purpose and decision

Unblock controlled fulfillment Phase 2 without weakening its inspect-only
contract. The current generic Codex read-only review path limits filesystem
writes but enables network and does not disable shell/agent tools. It is not
the capability required by fulfillment mapper/judge roles.

The approved choice is to reuse PR triage's existing no-tools provider turns
and descriptor-pinned host read channel. Models receive evidence as data and
request further bounded reads as structured replies. Python validates and
performs those reads. Provider-neutral role prose never contains native CLI
flags or provider branches.

Alternatives considered: separate native read-tool profiles require different
execution surfaces for Claude and Codex; retaining a shell with prose-only
restrictions does not enforce the contract. Neither is selected.

## Scope and ownership

This checkpoint exposes two small reusable boundaries, not a workflow engine:

1. A neutral, optional `InspectionTurnBackend`/facade operation backed by the
   existing tool-disabled Claude and Codex execution paths.
2. A shared descriptor-pinned `BoundedReadChannel`, extracted from triage's
   existing implementation, accepting caller-named roots and explicit denied
   paths. The old `ReviewReadChannel(worktree, spec_dir)` remains a compatibility
   wrapper with its existing behavior.

The provider operation receives only an already-rendered prompt and neutral
model tier/effort. It never loads prose, dispatches roles, chooses evidence,
opens a source tree, or publishes artifacts. Prosaic loading remains with the
workflow caller. The read channel has only `read_file` and `list_directory`;
there is no command, test, network, write, search subprocess or delegation op.

Fulfillment's eventual controller owns role envelopes, allowed roots and denied
paths from its existing containment policy, read-request count, total deadline,
budget, evidence binding and cumulative usage. This boundary returns existing
`CliRunResult` per turn. It does not borrow triage's diagnostic schema, role
names, publisher, journal, or result semantics.

## Provider contract

Expose `run_inspection_turn(private_cwd, prompt, *, frontmatter, timeout_ms)`
through the existing provider facade. Require an empty, nonsymlink private
invocation directory and positive timeout; no source checkout is the model's
working directory. Accept exactly neutral `model_tier` and `effort` values,
using existing supported values and adapter mapping. Do not accept execution
profiles, filesystem scopes, native models or permission overrides here.

Reuse existing no-tools controls, bounded stdin/capture and parser rejection of
unexpected tool events. Claude keeps its existing isolated macOS execution;
Codex reuses constrained request preparation and capture. The new capability
is supported only on the accepted macOS host boundary for both providers and
fails closed before launch when unsupported. No fallback to `run_agent_result`,
generic prompt execution, another provider or COMMANDER is permitted.

Keep existing `run_review_triage_turn` and generic constrained capability
contracts unchanged. Do not advertise Claude as implementing generic constrained
RE execution. Existing generic read-only review users are not migrated.

No model-accessible shell, tests, web/network tools, writes or delegation are
available. Provider authentication and model API transport necessarily retain
network access; this is not a claim that the entire CLI process is offline.
Unsupported native controls and unexpected tool events fail closed rather than
being silently ignored. This checkpoint adds no unverified CLI switches.

## Read contract and compatibility

Preserve the existing closed read/list schemas, no-follow descriptor traversal,
single-link regular-file checks, per-read mutation checks and literal output
formats. Copy caller roots at construction; the model can select only a supplied
alias. Fulfillment can later supply `worktree`, `spec` and `evidence` aliases;
the model cannot register another root or reinterpret an absolute path.

Explicit denied paths are host inputs, matched on path components against the
captured root paths before a read/list. Reject a root contained in a denied
path. A separately supplied alias cannot reopen denied content. Denied children
are not returned by directory listing. Symlink and hard-link aliases cannot
bypass the existing reader's checks. Do not add new globally inferred exclusions
or change triage's current root policy. Fulfillment must supply its containment
policy when it adopts this interface.

Preserve existing bounds: 1 MiB source file, 200 requested lines, 64 KiB encoded
read/list output, 500 directory entries; a provider turn accepts 1 MiB input and
captures at most 256 KiB output. Existing triage retains its 32-read limit.
The new primitive does not create a second workflow budget. Oversized/unavailable
text remains explicit evidence unavailability, not truncated success. Retained
descriptors do not provide an immutable snapshot across multiple reads; future
fulfillment input binding/recovery remains required.

## Acceptance and limits

Test both real adapter paths with scripted external model processes and actual
temporary source/spec/evidence files. Show a model reply requesting a read,
Python returning the requested lines, and the next turn consuming that evidence.
Inspect native no-tools controls, reject tool-event output, verify invalid input
never launches, and retain failed-turn usage. Run existing triage/provider/read
and delivery regression tests without changing their expected behavior.

No semantic fulfillment roles, controller loop, full/scoped refresh, durable
recovery, publication, mode/default change, native entry migration, installation,
live model call, push or merge belongs to this checkpoint. No AGENTS.md/CLAUDE.md
or provider-specific Prosaic changes. Baseline evidence before this design:
97 existing triage provider/read tests passed in 1.49s; this is not acceptance
of the new interface or a live-provider claim.
