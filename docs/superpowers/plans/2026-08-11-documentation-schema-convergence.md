# Documentation Schema Convergence Plan

- [x] Confirm the deployed TECH WRITER prose contains the canonical version-2
  frontmatter examples.
- [x] Inspect the retained repair invocation and identify which context it read.
- [x] Preserve canonical `not_applicable_reason`; do not accept the invented
  `reason` alias.
- [x] Make deterministic gate failures name exact YAML keys and values.
- [x] Add a one-cycle no-documentation-change repair regression.
- [x] Redeploy and prove the retained greenfield delivery passes verification in
  one schema repair cycle; later landing failures were isolated as EGR-160.
