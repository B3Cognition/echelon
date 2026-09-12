# SDD ledger — plan: docs/superpowers/plans/2026-09-13-captured-graph-input-parsers.md

## Preflight

| Tasks | Shared interface or self-check | Result |
| --- | --- | --- |
| 1 / requirement extraction | Current inventory reads spec/plan/coverage/tasks and uses definition precedence plus task fallback. | Extract one shared text loop per existing reader, preserve source names/lines/order and wide-ID sorting. No new definition grammar. |
| 1 / deferred ledger | Existing read owns missing-file default and read/decode error wrapping; entries already have a shared from_dict. | Pure text entry cannot infer absence; wrapper retains missing behavior and delegates parsing. Empty text still malformed JSON. |
| 1 / verified ledger | Existing conversion is deliberately permissive and returns mapping-valued dataclasses. | Preserve normalization/skipped rows/defaults/order and fresh maps; do not market compatibility parsing as managed validation or current verification. |
| 1 / shared files/interfaces | Three independent same-shaped extractions serve one graph-input seam; their outputs do not depend on one another. | Batch in one implementer/review with three separately witnessed RED cases, no parallel implementation or task-per-helper overhead. |
| 1 / captured sources | A parsed supplied string has no source provenance or current filesystem lease. | Pure results retain captured bytes' interpretation after actual source edits; caller must authenticate source selection and identity separately. |
| 1 / legacy and managed grammar | Canonical inventory accepts extra legacy families/range endpoints while managed candidate adapters enforce a separate typed grammar. | Keep compatibility semantics unchanged; graph activation/managed acceptance is not part of this extraction. No contradictory strict-schema test is mandated. |
| 1 / I/O and errors | Existing canonical read uses UTF8 replacement; deferred and verified read use strict UTF8. | Preserve those exact wrapper distinctions; new pure APIs require exact supplied strings and access no filesystem. |
| 1 / test behavior | Real current readers and literal expected complete records must pass before new-entry calls fail. | Three target AttributeErrors before production, not imports/setup errors. Strong post-capture-change/purity/full-record tests and once-only seven-module covering set. |
| 1 / broader design | Current graph builder also reads mutable policy/traceability/amendment/memory/RE/topology sources. | This closes three parsing prerequisites only, not complete graph construction/source authorization/runtime/producer/completion/repair. No next API beyond these parsers selected. |

No conflicting plan pair or additional product-policy ruling identified. Root read approved design, the existing canonical extraction and private collectors, deferred reader/entry conversion, verified reader/conversion and relevant existing tests. Original publication-history binding completed with clean review and576 covering tests at554f83c9/563665a3; checkpoint19c51db0. Current plan is a compatibility extraction within approved architectural work. Sol/high implementer and reviewer are sufficient for the bounded multi-file/shared-reader work. Root owns plan/ledger; retain artifacts through final whole-branch review and exhaustive rulings handoff.
