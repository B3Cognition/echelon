# Build 8 Verify Gates Appendix

Load this appendix before ENGINEERING MANAGER sign-off, when `verify.sh` is missing or incomplete, or when IMPLEMENTER needs exact smoke/security/license gate requirements.

## Smoke Test Requirement

Every build must produce a `verify.sh` in the repo root. This script is what the harness runs in Docker to verify the build.

`verify.sh` MUST include a smoke test that starts the application and verifies it responds. Unit tests alone are not sufficient.

Minimum smoke test pattern for web applications:

```sh
npm run build
npx vite preview --port 4173 &
PREVIEW_PID=$!
sleep 3
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:4173)
kill $PREVIEW_PID 2>/dev/null || true
if [ "$STATUS" != "200" ]; then
  echo "Smoke test FAILED: app returned HTTP $STATUS (expected 200)"
  exit 1
fi
echo "Smoke test PASSED: app served HTTP 200"
```

Adapt for other stacks:

| Stack | Smoke check |
| --- | --- |
| Node/Express | `node server.js & sleep 2 && curl -s http://localhost:3000` |
| Python/FastAPI | `uvicorn main:app & sleep 2 && curl -s http://localhost:8000/health` |
| Static site | `npx serve dist & sleep 2 && curl -s http://localhost:3000` |
| CLI/library | Run the built artifact, for example `node dist/index.js --version` |

## Next.js Smoke Test Rules

Next.js apps require stricter smoke testing because `next build` can exit 0 while producing a broken production bundle.

For Next.js, `verify.sh` MUST:

1. Capture build output and fail on SSG/runtime initialization errors.

```sh
next build 2>&1 | tee /tmp/nextbuild.log
if grep -qE "(TypeError|ReferenceError|Error:.*is not a function|Error:.*Cannot read)" /tmp/nextbuild.log; then
  echo "Next.js build contains SSG errors; pages may crash at runtime"
  echo "Fix: add 'export const dynamic = \"force-dynamic\"' to affected pages"
  cat /tmp/nextbuild.log >&2
  exit 1
fi
```

2. Start the server and test a health endpoint with strict 2xx status.

```sh
PORT=3099 node server.js &
SERVER_PID=$!
sleep 4
STATUS=$(curl -so /dev/null -w '%{http_code}' http://localhost:3099/api/health 2>/dev/null)
kill $SERVER_PID 2>/dev/null || true
if [[ ! "$STATUS" =~ ^2 ]]; then
  echo "Health check failed: /api/health returned HTTP $STATUS (expected 2xx)"
  exit 1
fi
echo "Smoke test PASSED: /api/health returned HTTP $STATUS"
```

Pages that import provider-dependent modules must usually be `force-dynamic`. This includes auth providers, i18n libraries, ORMs, and modules that read React context or perform async work at module scope. IMPLEMENTER audits for this pattern; SENTINEL includes render tests for affected pages.

If `verify.sh` does not contain a smoke test, ENGINEERING MANAGER requests IMPLEMENTER to add one before sign-off.

## Security And License Gates

Every `verify.sh` must run security and dependency license checks after the smoke test, inside the same Docker sandbox.

Security scan commands:

| Ecosystem | Command |
| --- | --- |
| Node.js | `npm audit --audit-level=high 2>&1 \| tee /tmp/audit.txt \|\| { echo "Security audit failed; see /tmp/audit.txt"; exit 1; }` |
| Python | `pip install pip-audit --quiet && pip-audit 2>&1 \| tee /tmp/audit.txt \|\| { echo "pip-audit found vulnerabilities; see /tmp/audit.txt"; exit 1; }` |
| Go | `go install golang.org/x/vuln/cmd/govulncheck@latest 2>/dev/null && govulncheck ./... 2>&1 \| tee /tmp/audit.txt \|\| { echo "govulncheck found vulnerabilities; see /tmp/audit.txt"; exit 1; }` |
| Rust | `cargo install cargo-audit --quiet 2>/dev/null && cargo audit 2>&1 \| tee /tmp/audit.txt \|\| { echo "cargo audit found vulnerabilities; see /tmp/audit.txt"; exit 1; }` |
| Ruby | `gem install bundler-audit --quiet 2>/dev/null && bundle-audit check --update 2>&1 \| tee /tmp/audit.txt \|\| { echo "bundle-audit found vulnerabilities; see /tmp/audit.txt"; exit 1; }` |

Permitted licenses: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `Unlicense`, `CC0-1.0`, `Python-2.0`, `BlueOak-1.0.0`.

License check commands:

| Ecosystem | Command |
| --- | --- |
| Node.js | `npx --yes license-checker --onlyAllow "MIT;Apache-2.0;BSD-2-Clause;BSD-3-Clause;ISC;Unlicense;CC0-1.0;BlueOak-1.0.0" 2>&1 \| tee /tmp/licenses.txt \|\| { echo "License check failed; review /tmp/licenses.txt"; exit 1; }` |
| Python | `pip install pip-licenses --quiet && pip-licenses --allow-only="MIT;Apache Software License;BSD License;ISC License (ISCL);Public Domain;Python Software Foundation License" 2>&1 \|\| { echo "pip-licenses check failed"; exit 1; }` |
| Go | `go install github.com/google/go-licenses@latest 2>/dev/null && go-licenses check --allowed_licenses=MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC,Unlicense,CC0-1.0 ./... 2>&1 \| tee /tmp/licenses.txt \|\| { echo "go-licenses check failed; see /tmp/licenses.txt"; exit 1; }` |
| Rust | `cargo install cargo-license --quiet 2>/dev/null; cargo license 2>&1 \| grep -vE "^(name\|MIT\|Apache-2.0\|BSD-2-Clause\|BSD-3-Clause\|ISC\|Unlicense\|CC0-1.0)" \| grep -v "^$" > /tmp/licenses.txt; [ ! -s /tmp/licenses.txt ] \|\| { echo "Non-permissive license detected; see /tmp/licenses.txt"; exit 1; }` |
| Ruby | `gem install license_finder --quiet 2>/dev/null && license_finder 2>&1 \| tee /tmp/licenses.txt \|\| { echo "License check failed; see /tmp/licenses.txt"; exit 1; }` |

`pip-licenses` reports display names rather than SPDX identifiers, so its allow list must use pip-licenses names.

For polyglot projects, run checks for every detected ecosystem. If a vulnerability or non-permissive license is found, print the finding, exit 1, and require the squad to update the dependency or document an exception in `specs/{NNN}-{feature}/license-exceptions.md` before the build can proceed.
