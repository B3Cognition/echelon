# Reference Architectures — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SCOUT (DISCOVER) | **Date**: 2026-04-03 | **Spec**: 018-soar-overlay

---

## SoarGroup/Soar (Official C++ Implementation)
- **Source:** https://github.com/SoarGroup/Soar (BSD license); https://soar.eecs.umich.edu/soar_manual/02_TheSoarArchitecture/; Laird 2022, arxiv:2205.03854
- **Relevance:** The canonical reference implementation of the SOAR cognitive architecture by its original creators (Laird, Newell, Rosenbloom, CMU → University of Michigan). Defines all SOAR terms precisely and is the ground truth for the match-select-apply cycle, impasse mechanics, and chunking semantics.
- **Key entities:** Working Memory (WME graph), Procedural Memory (production rules in Rete), Decision Procedure (preference-based operator selection), Chunking (episodic compilation to production rules), Episodic Memory (temporal experience store, separate subsystem), Semantic Memory (declarative long-term store, separate subsystem), Input/Output Links (environment interface).
- **Boundaries:** Core cognitive cycle (Rete match + decision + application) is isolated from I/O. Episodic and semantic memories are separate modules added in later versions. Python interface is via SWIG-generated SML bindings — a thin wrapper around the C++ kernel, not a reimplementation.
- **Patterns used:** Rete network for efficient production rule matching; parallel rule firing (all matching rules fire per elaboration cycle, not one-at-a-time); preference calculus for operator selection; automatic substate creation on impasse.
- **Lessons:**
  - The Rete algorithm is the performance-critical component. Without it, naive rule matching is O(rules × WMEs) per elaboration cycle. For small rule sets (<50 rules, <100 WMEs) in Echelon's context, naive matching is acceptable.
  - Impasse is a first-class architectural construct, not an error handler. Designing the overlay to treat impasse as a signal (not a failure) is the correct approach.
  - Chunking requires dependency tracing to identify which WMEs were causally relevant to the result. Without dependency tracing, chunked rules generalize incorrectly (too specific or too general). This is the hardest aspect to approximate without the full SOAR kernel.
  - The full preference calculus (8 preference types) enables nuanced multi-operator scenarios but adds significant complexity. For a single-step context enrichment overlay, argmax-confidence is a reasonable simplification.
- **Differences from our project:** Official SOAR is a full cognitive architecture for building autonomous agents (robots, game AI, tutoring systems). Echelon's SOAR overlay is a lightweight Python-native context enrichment step that borrows SOAR concepts without implementing the full kernel. No C extensions, no Rete network, no SML protocol, no full preference calculus.

---

## pysoarlib (amininger/pysoarlib)
- **Source:** https://github.com/amininger/pysoarlib
- **Relevance:** A Python convenience wrapper around the official SOAR SML interface. Provides `SoarClient`, `WorkingMemoryElement`, and `AgentConnector` classes that simplify the Python ↔ SOAR bridge. Shows how Python developers conventionally interact with SOAR's working memory from outside the C++ kernel.
- **Key entities:** `SoarClient` (manages SOAR kernel lifecycle), `WorkingMemoryElement` (WME object with id/attr/value), `AgentConnector` (handles input-link and output-link events), `SoarWME` (wrapper for adding/removing WMEs via SML).
- **Boundaries:** pysoarlib is a wrapper, not a reimplementation. It requires the C++ SOAR kernel installed separately and communicates via SML. The Python layer handles I/O link management; the kernel handles all cognitive cycle processing.
- **Patterns used:** Observer pattern for output-link events; SML command strings for kernel communication; WME lifecycle management (create → update → destroy) via kernel handles.
- **Lessons:**
  - WMEs in practice have handles (kernel-managed objects), not just dicts. The overlay's dict-based WME representation is a reasonable simplification for a non-kernel implementation.
  - pysoarlib's `AgentConnector` pattern (input events in, output events out) maps well to Echelon's `enrich_context(in) -> out` interface. The overlay is essentially a stateless AgentConnector where the "input link" is context_pack and the "output link" is the enriched context_pack.
  - pysoarlib shows that the key challenge in Python-SOAR integration is WME lifecycle management — specifically, knowing when to add and remove WMEs. Echelon's overlay sidesteps this by recreating WMEs fresh from context_pack on each call (stateless working memory).
- **Differences from our project:** pysoarlib requires the C++ kernel (hard excluded by ADR-005 stdlib constraint). Echelon's overlay does not use SML, handles, or kernel communication. The dict-based WME representation in the overlay is a deliberate simplification.

---

## soar-sml (PyPI package)
- **Source:** https://pypi.org/project/soar-sml/
- **Relevance:** The official PyPI-distributed SML bindings for the SOAR kernel. Provides Python access to SOAR's full cognitive cycle via SWIG-generated C extension. Most directly comparable to what Echelon's overlay would be if it used the full SOAR kernel.
- **Key entities:** Kernel class, Agent class, Identifier (WME graph nodes), SML events (RunEvent, ProductionEvent, etc.).
- **Boundaries:** C extension hard dependency. Platform-specific wheels. Kernel process lifecycle (create kernel → create agent → run → destroy). Production rules must be written in Soar Rule Language (.soar files), not Python dicts.
- **Patterns used:** Callback registration for SOAR events; `.soar` file format for production rules; run-loop control (run-forever, run-by-decision, etc.).
- **Lessons:**
  - Production rules in canonical SOAR are written in Soar Rule Language (`.soar` files), which has its own syntax distinct from Python. Translating production rules to Python dicts (as Echelon's overlay does) is a representation simplification that breaks the `.soar` file format convention. This is acceptable because the overlay has no `.soar` parser requirement.
  - The `soar-sml` package's platform-specific wheel requirement (separate wheels for Linux/macOS/Windows) is exactly the kind of deployment complexity that the stdlib-only constraint avoids.
  - SOAR's run modes (run-by-decision, run-until-output) do not map cleanly to a single `enrich_context` function call. The overlay must adapt SOAR's loop-based run model to a stateless single-call pattern.
- **Differences from our project:** soar-sml is explicitly excluded (C extension; requires kernel installation). Echelon's overlay reimplements SOAR concepts in Python dicts.

---

## KRaizer/Soar-Python-Minimum-Working-Example
- **Source:** https://github.com/KRaizer/Soar-Python-Minimum-Working-Example
- **Relevance:** A minimal working example of SOAR + Python integration, showing how to wire SOAR's input-output links from Python. Demonstrates the minimum boilerplate required to get a SOAR agent running from Python.
- **Key entities:** SML Kernel, Agent, Input Link (structured WME tree), Output Link (operator proposals from SOAR → Python callback).
- **Patterns used:** Input link as structured WME tree; output link events as operator proposals; run-one-decision as the per-cycle control primitive.
- **Lessons:**
  - The input-link → cognitive cycle → output-link pattern is structurally equivalent to context_pack → enrich_context → enriched context_pack. This validates Echelon's interface design as analogous to a SOAR I/O cycle.
  - The minimum working example requires only ~50 lines of Python + SOAR kernel + a .soar rule file. The Echelon overlay will require similar lines of Python but with no external dependencies.
  - WME tree construction (adding child identifiers to build a graph) is more expressive than Echelon's flat WME list. The flat list is a deliberate simplification (no nested identifier support needed for context enrichment).
- **Differences from our project:** Requires SOAR kernel binary and .soar rule files. Echelon's overlay replaces all of this with Python dicts and a JSON rule store.

---

## Rule-Based Symbolic Reasoning (Taseer 2024, Medium)
- **Source:** https://medium.com/@mateeb.ce41ceme/rule-based-symbolic-reasoning-cognitive-architecture-for-knowledge-growth-and-decision-based-f9ca864a8b12
- **Relevance:** A Python-native educational implementation of SOAR-inspired symbolic rule-based reasoning without the C++ kernel. Shows how SOAR concepts can be approximated in pure Python for lightweight agents.
- **Key entities:** Fact Store (analogous to Working Memory), Rule (IF-THEN with Python lambda conditions and actions), Inference Engine (forward-chaining rule firing).
- **Patterns used:** Forward chaining (match all rules whose conditions hold, fire all, repeat until fixed point); Python dicts as facts; lambda functions as rule conditions; list append as rule actions.
- **Lessons:**
  - A pure Python forward-chaining rule engine can be implemented in <100 lines of stdlib code. The key simplification vs SOAR: (a) Python functions as conditions (no Rete), (b) dict mutation as action (not WME add/remove), (c) no operator selection layer (rules fire their own actions directly).
  - The forward-chaining approach (fire all matching rules, iterate to fixed point) maps to SOAR's elaboration cycle. For Echelon's single-pass approximation, one iteration is sufficient.
  - The critical missing piece in simplified Python implementations: no preference-based operator selection, no impasse detection, no chunking. Echelon's overlay adds all three (in simplified form) beyond what this reference architecture provides.
- **Differences from our project:** No operator selection layer (rules fire directly, not through a selection procedure). No impasse event. No chunking. Echelon's overlay is architecturally richer than this reference.

---

## Common Patterns Across References

All reference architectures agree on:
1. **WME as the atomic data unit:** Subject-attribute-value triples are universal across all SOAR implementations.
2. **Parallel rule firing in the match phase:** All matching rules fire simultaneously, not one at a time.
3. **Separation of match (elaboration) from selection (decision):** The decision procedure is always a distinct layer from rule matching.
4. **Impasse as a first-class architectural event:** Not an error — a deliberate mechanism. All implementations model it explicitly.
5. **I/O link as the environment interface:** Input state goes in; operator proposals come out. Maps cleanly to Echelon's `enrich_context(in) -> out` pattern.

---

## Divergence Points

| Dimension | Full SOAR (C++) | pysoarlib / soar-sml | Taseer Python | Echelon SOAR Overlay |
|-----------|-----------------|---------------------|----------------|----------------------|
| Rete network | Yes (full Rete) | Yes (via kernel) | No (linear scan) | No (linear scan) |
| Preference calculus | Full (8 types) | Full (via kernel) | None | Simplified (confidence scalar) |
| Chunking | Full (dependency-traced) | Full (via kernel) | None | Approximated (WME snapshot) |
| Rule language | Soar Rule Language | .soar files | Python lambdas | Python dicts (JSON) |
| C extension dependency | Required | Required | None | None (ADR-005) |
| Impasse → substate | Full substates | Full substates | None | ImpasseEvent + DefaultOperator |
| Elaboration cycles | Multiple until quiescence | Multiple until quiescence | Multiple (configurable) | Single pass |
| Cross-run persistence | None (kernel is stateless) | None | None | None (v1) |

The divergence points define Echelon's design space: stdlib-only, single-pass, confidence-scalar selection, snapshot-based chunking, ImpasseEvent without true substate creation.
