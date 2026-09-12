# SDD ledger — plan: docs/superpowers/plans/2026-09-13-projected-source-images.md

## Preflight

| Tasks | Shared interface or self-check | Result |
| --- | --- | --- |
| 1 / existing projection | _transform_selected_sources already constructs complete typed final images and then discards bytes into a manifest. | Expose those values through one shared transformer, not a new projection policy or mutable-file reread. |
| 1 / public manifest API | Existing source registry and journal derive accepted source hashes from project_publication_source_manifest. | Keep its signature, canonical bytes and failures unchanged; it returns the new result's existing-format manifest. |
| 1 / private guard interface | squad_source_guard imports _transform_selected_sources(initial,prefix,new_directories=...) for interrupted progress and contiguous next-write parents. | Preserve exact private signature/manifest result; only delegate shared image construction. No new public partial-prefix permission or guard change. |
| 1 / projected versus observed | PublicationSourcesSnapshot includes actual capture marker/promoted-prefix, which predicted final tuples cannot honestly supply. | Separate frozen DTO with trees/files/manifest only. Original-baseline codec must reject it, so no fabricated capture or recovery authority. |
| 1 / nested ownership | Existing transformation reuses unchanged frozen records because it currently only returns detached manifest bytes. | New byte-image return needs fresh nested records/descriptors; immutable bytes and strings may be shared. Damage to original input records after return cannot rewrite result. |
| 1 / manifest consistency | Source manifest factory validates exact byte/hash/mode/layout and canonical ordering. | Generate/validate manifest from the exact output tuples once; independent full tuple/manifest expectations and actual final capture compare. |
| 1 / source selection | Existing initial validator permits operations outside declared selected sources and does not certify completeness. | Retain semantics, no automatic selection expansion or completeness claim. Graph's complete caller selection remains separate. |
| 1 / first RED and platform | Existing real seal/inspection/manifest projection precede missing public image API. | Actual AttributeError only after valid setup. Secure POSIX skip limited to physical cases; pure cases run independently. |
| 1 / verification | Shared private projection affects guard and source registry callers despite one changed production module. | Six named modules once, including actual guard/publication/source-store ownership coverage; no capacity/full-unit/live repeats. |
| 1 / broader design | Graph construction/logical source mapping and other policy/memory/RE inputs still need integration. | Byte projection is only a deterministic source input seam, not graph/semantic/runtime/completion/repair activation. |

No additional product-policy ruling or conflicting requirement found. Root read existing source projection fully, private guard caller fully, source snapshot record types/capture definitions, real projection fixture/setup and candidate source assembly's existing input seam. Captured graph-input parsers completed atf11c4f88/e78355b2 with clean review and112 covering tests; checkpoint71347157. Sol/high implementer and reviewer are sufficient for this one-production-module extraction with shared guard compatibility. Root owns plan/ledger; keep artifacts until final whole-branch review and exhaustive rulings handoff.
