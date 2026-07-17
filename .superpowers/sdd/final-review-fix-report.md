# Final Review Fix Report

## RED Evidence

- `PYTHONPATH=src .venv/bin/pytest tests/unit/test_kb_schema_validator.py tests/unit/test_kb_proposals.py tests/unit/test_kb_proposal_templates.py tests/unit/test_kb_proposal_prompt_contracts.py tests/integration/test_kb_proposals_cli.py -q` initially reported 21 failures covering missing learning IDs, missing SAGE correctness/schema checks, shallow provenance validation, duplicate proposal IDs, mixed apply status, lock/atomic safety, and prompt/template contracts.
- Added the empty-suffix agent identity regression and observed the expected failure for `speckit-echelon-` before tightening validation.
- Added the SAGE template-to-canonical-schema regression and observed expected invalid `challenge_type` and `outcome` failures before correcting the template.
- Added the FINALIZE non-blocking capture contract and observed the expected failure before wrapping command substitutions in conditional capture.

## GREEN Evidence

- `PYTHONPATH=src .venv/bin/pytest tests/unit/test_kb_schema_validator.py tests/unit/test_kb_proposals.py tests/unit/test_kb_proposal_templates.py tests/unit/test_kb_proposal_prompt_contracts.py tests/integration/test_kb_proposals_cli.py -q` - 67 passed.
- `bash tests/unit/test-kb-write.sh` - 9 passed, 0 failed.
- `bash tests/integration/test-pending-merge.sh` - 12 passed, 0 failed.
- `bash -n extension/scripts/bash/finalize-run.sh` - passed.
- `git diff --check` - passed.

## Files Changed

- `src/echelon/kb_proposals.py`
- `src/codegen/memory/kb_schema_validator.py`
- `knowledge-base/kb-schema.md`
- `extension/templates/kb-proposals/sage-decision-proposal-template.yaml`
- `extension/agents/exploration/appendices/sage-decision-calibration-reference.md`
- `extension/agents/learning/internalizer.md`
- `extension/workflow/phases/phase4-document.md`
- `tests/unit/test_kb_schema_validator.py`
- `tests/unit/test_kb_proposals.py`
- `tests/unit/test_kb_proposal_templates.py`
- `tests/unit/test_kb_proposal_prompt_contracts.py`
- `tests/integration/test_kb_proposals_cli.py`

## Concerns

- Aggregate calibration and internalization proposal appliers remain intentionally unimplemented. They produce `needs_review`; any run containing that outcome is now reported as degraded rather than applied.
- Target locking uses a simple adjacent exclusive lock file, as requested. A stale lock requires external cleanup rather than automatic recovery.
