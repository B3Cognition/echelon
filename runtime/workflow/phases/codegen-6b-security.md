# Phase: codegen-6b-security
# Source: echelon.codegen.md §Phase 6b — SECURITY Scan and License Gate
# Read by: echelon.orchestrator (ORCHESTRATOR) before Phase 6b SECURITY execution (echelon.codegen only)

## Phase 6b: SECURITY — Security Scan and License Gate

**Print:** `[CODEGEN] Phase SECURITY — Running security scan + license check...`

Detect the project ecosystem from build manifests (same detection as Phase RE).
Run the appropriate commands for each detected ecosystem. For polyglot projects,
run all applicable blocks.

**Security scan** (run first — fail fast on vulnerabilities):

| Ecosystem | Command |
| --- | --- |
| Node.js (npm/pnpm/yarn/bun) | `npm audit --audit-level=high 2>&1 \| tee /tmp/codegen-audit.txt \|\| { echo "✗ Security audit failed — see /tmp/codegen-audit.txt"; exit 1; }` |
| Python | `pip install pip-audit --quiet && pip-audit 2>&1 \| tee /tmp/codegen-audit.txt \|\| { echo "✗ pip-audit found vulnerabilities"; exit 1; }` |
| Go | `go install golang.org/x/vuln/cmd/govulncheck@latest 2>/dev/null && govulncheck ./... 2>&1 \| tee /tmp/codegen-audit.txt \|\| { echo "✗ govulncheck found vulnerabilities"; exit 1; }` |
| Rust | `cargo install cargo-audit --quiet 2>/dev/null && cargo audit 2>&1 \| tee /tmp/codegen-audit.txt \|\| { echo "✗ cargo audit found vulnerabilities"; exit 1; }` |
| Ruby | `gem install bundler-audit --quiet 2>/dev/null && bundle-audit check --update 2>&1 \| tee /tmp/codegen-audit.txt \|\| { echo "✗ bundle-audit found vulnerabilities"; exit 1; }` |

**License check** (run after security scan passes):

Permitted: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `Unlicense`, `CC0-1.0`, `Python-2.0`, `BlueOak-1.0.0`.

| Ecosystem | Command |
| --- | --- |
| Node.js | `npx --yes license-checker --onlyAllow "MIT;Apache-2.0;BSD-2-Clause;BSD-3-Clause;ISC;Unlicense;CC0-1.0;BlueOak-1.0.0" 2>&1 \| tee /tmp/codegen-licenses.txt \|\| { echo "✗ License check failed — see /tmp/codegen-licenses.txt"; exit 1; }` |
| Python | `pip install pip-licenses --quiet && pip-licenses --allow-only="MIT;Apache Software License;BSD License;ISC License (ISCL);Public Domain;Python Software Foundation License" 2>&1 \|\| { echo "✗ pip-licenses check failed"; exit 1; }` |
| Go | `go install github.com/google/go-licenses@latest 2>/dev/null && go-licenses check --allowed_licenses=MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC,Unlicense,CC0-1.0 ./... 2>&1 \| tee /tmp/codegen-licenses.txt \|\| { echo "✗ go-licenses check failed"; exit 1; }` |
| Rust | `cargo install cargo-license --quiet 2>/dev/null; cargo license 2>&1 \| grep -vE "^(name\|MIT\|Apache-2.0\|BSD-2-Clause\|BSD-3-Clause\|ISC\|Unlicense\|CC0-1.0)" \| grep -v "^$" > /tmp/codegen-licenses.txt; [ ! -s /tmp/codegen-licenses.txt ] \|\| { echo "✗ Non-permissive license detected — see /tmp/codegen-licenses.txt"; exit 1; }` |
| Ruby | `gem install license_finder --quiet 2>/dev/null && license_finder 2>&1 \| tee /tmp/codegen-licenses.txt \|\| { echo "✗ License check failed — see /tmp/codegen-licenses.txt"; exit 1; }` |

> Note: `pip-licenses` reports license names in its own format (e.g. "Apache Software License", "BSD License") rather than SPDX identifiers.

**Gate outcome:**

- All checks pass → `security_gate: "pass"` → ADVANCE to RUNNABLE
- Any vulnerability found → `security_gate: "fail"` → record in `codegen-state.json`, print the finding, HALT. Always escalate security vulnerabilities or license violations to human. Do not auto-fix them.
- Any non-permissive license found → `security_gate: "license_fail"` → same: HALT and escalate. Document exception in `{spec_dir}/license-exceptions.md` if approved.

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_deliver" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase SECURITY — COMPLETE ✓ (security gate PASSED)`
