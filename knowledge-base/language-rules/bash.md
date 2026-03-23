# Bash Code Review Rules

## Strict Mode

- **Every script MUST start with `set -euo pipefail`** after the shebang line.
  - `-e`: Exit on any command failure.
  - `-u`: Treat unset variables as errors.
  - `-o pipefail`: Pipe fails if any command in the pipeline fails (not just the last).
- **Shebang must be `#!/usr/bin/env bash`** — not `#!/bin/bash` (portability).
- **No `set +e` to suppress errors** unless wrapped around a specific command with documented justification.

## Variable Quoting

- **All variable expansions MUST be double-quoted.** `"$var"`, not `$var`. This prevents word splitting and globbing.
- **Exception:** Inside `[[ ]]` tests, quoting is optional (but still recommended for consistency).
- **Array expansions use `"${array[@]}"`** — never `${array[*]}` unquoted.
- **No unquoted command substitutions.** Use `"$(command)"`, not `$(command)`.

## Variable Naming

- **Local variables in functions must use `local`.** No leaking variables into the global scope.
- **Constants use UPPER_SNAKE_CASE.** `readonly MAX_RETRIES=3`.
- **Local variables use lower_snake_case.** `local file_count=0`.
- **Use `readonly`** for variables that should not change after assignment.

## Error Handling

- **Check return codes explicitly** for critical commands: `if ! command; then handle_error; fi`.
- **Use `trap` for cleanup.** `trap cleanup EXIT` ensures temporary files are removed on exit, error, or signal.
- **Provide meaningful error messages** to stderr: `echo "ERROR: file not found: $path" >&2`.
- **Exit with non-zero codes** on failure. Use distinct exit codes for different failure modes when useful.

## ShellCheck Compliance

- **All scripts must pass `shellcheck`** with zero warnings. Address warnings with fixes, not `# shellcheck disable` directives.
- **If a directive is necessary**, add a comment explaining why: `# shellcheck disable=SC2034 # variable used by sourced script`.
- **Common ShellCheck issues to prevent:**
  - SC2086: Double-quote variables to prevent globbing/splitting.
  - SC2046: Quote command substitutions.
  - SC2002: Useless use of `cat`. Use `< file` instead.
  - SC2155: Declare and assign separately: `local var; var=$(command)`.

## Command Usage

- **Use `[[ ]]`** instead of `[ ]` for conditionals (safer, supports regex, no word splitting).
- **Use `$(command)`** instead of backticks for command substitution.
- **Use `printf`** instead of `echo` for portable, formatted output.
- **Use `mktemp`** for temporary files. Never hardcode `/tmp/myfile`.
- **No `cd` without error checking.** Use `cd "$dir" || exit 1` or `pushd`/`popd`.

## Functions

- **Use `function_name() {}`** syntax (POSIX-compatible), not `function function_name {}`.
- **All functions must be defined before use.** No forward references.
- **Functions should be short** (under 50 lines). Extract helpers for complex logic.
- **Return values via stdout** (for data) or return codes (for success/failure). Do not use global variables for return values.

## Input Validation

- **Validate all external inputs** (arguments, environment variables, file contents) before use.
- **Use `${var:?error message}`** to enforce required variables with a descriptive error.
- **Check file existence** before reading: `[[ -f "$file" ]] || { echo "ERROR: missing $file" >&2; exit 1; }`.

## Security

- **No `eval`** with user-supplied input. Ever.
- **No unvalidated paths** in `rm`, `mv`, or `cp` commands. Especially no `rm -rf "$var/"` where `$var` could be empty.
- **Use `--` to separate options from arguments** when passing variables to commands: `grep -- "$pattern" "$file"`.
- **Do not store secrets in scripts.** Use environment variables or secret managers.

## Portability

- **Target Bash 4.0+** unless the project requires older compatibility.
- **Avoid GNU-specific flags** without checking platform: macOS uses BSD utilities by default.
- **Use `command -v`** instead of `which` to check for command availability.
