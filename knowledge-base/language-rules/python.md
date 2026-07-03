# Python Code Review Rules

## Type Hints

- **All function signatures must have type hints** — parameters and return types. No untyped public functions.
- **Use `from __future__ import annotations`** for forward references and modern union syntax (`X | Y`).
- **Complex types use `typing` module.** `Optional[X]`, `Union[X, Y]`, `Dict[str, Any]`, `List[int]`, etc. For Python 3.10+, use built-in generics (`list[int]`, `dict[str, Any]`).
- **No `Any` unless unavoidable.** If used, add a comment explaining why the type cannot be narrowed.
- **Use `TypedDict` for dictionary shapes** that represent structured data (API responses, configs).
- **Use `Protocol` for structural subtyping** instead of ABCs when only method signatures matter.

## Docstrings

- **All public functions, classes, and modules must have docstrings.** Use Google style or NumPy style consistently within the project.
- **Docstrings describe behavior, not implementation.** "Returns the user's profile" not "Queries the database and maps rows to a User object."
- **Include `Args:`, `Returns:`, and `Raises:` sections** for functions with parameters, return values, or exceptions.
- **No redundant docstrings.** `def get_name(self) -> str: """Get the name."""` adds nothing — either make it meaningful or skip trivial getters.

## Error Handling

- **No bare `except:` or `except Exception:`.** Always catch specific exception types.
- **No silencing exceptions.** `except SomeError: pass` is almost always wrong. Log, re-raise, or handle explicitly.
- **Use custom exception classes** for domain-specific errors. Inherit from a project base exception, not `Exception` directly.
- **Context managers (`with`)** for resource management. No manual `open()`/`close()` patterns.
- **Use `raise ... from e`** to chain exceptions and preserve tracebacks.

## String Formatting

- **Use f-strings** for all string interpolation. No `str.format()`, no `%` formatting, no string concatenation for building messages.
- **Exception:** Logging calls use lazy formatting: `logger.info("User %s logged in", user_id)` — not f-strings (avoids formatting when log level is disabled).

## Code Style

- **Follow PEP 8.** Line length 88 (Black default) or 79 (PEP 8 strict) — match project config.
- **Formatter evidence is separate from lint evidence.** When Ruff is the project formatter, verify Python style claims with both `ruff check` and `ruff format --check`. Do not report Python style, lint, or formatting as clean from `ruff check` alone.
- **Use `pathlib.Path`** instead of `os.path` for filesystem operations.
- **Use list/dict/set comprehensions** over `map()`/`filter()` when they improve readability. Do not nest comprehensions deeper than 2 levels.
- **No mutable default arguments.** `def f(items: list = None)` — use `None` and initialize inside the function.
- **Use `dataclasses` or `attrs`** for data containers instead of plain classes with manual `__init__`.

## Imports

- **Standard library, third-party, local** — three groups separated by blank lines (isort/ruff default).
- **No wildcard imports** (`from module import *`). Always import specific names.
- **No circular imports.** Use `TYPE_CHECKING` guard for type-only imports that would create cycles.

## Testing

- **Use `pytest`** over `unittest` unless the project mandates otherwise.
- **Test names describe the scenario:** `test_user_login_with_expired_token_returns_401`.
- **No `assert True`/`assert False`.** Use specific assertions: `assert result == expected`.
- **Use fixtures** for setup/teardown, not `setUp`/`tearDown` methods.

## Security

- **No `eval()`, `exec()`, or `compile()`** with user input.
- **No `pickle` for untrusted data.** Use JSON or a safe serialization format.
- **Parameterized queries only.** No string interpolation in SQL or ORM raw queries.
