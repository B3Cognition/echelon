"""
harness.py — Test harness generator for IMPLEMENTER tasks.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-022: Generate language-appropriate test scaffolding per ADR-008-005.

Supported languages:
  - python  → pytest (test_<module>.py)
  - typescript / javascript → vitest/jest (<module>.test.ts)
  - go      → go test (<module>_test.go)
  - java    → JUnit 5 (<Module>Test.java)

FR-TEST-001: Every IMPLEMENTER task receives a test scaffold.
FR-IMPL-003: IMPLEMENTER uses scaffold as TDD basis.
NFR-PORT-001: Generator is language-agnostic at the call site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = frozenset({"python", "typescript", "javascript", "go", "java"})

# Standard greenfield test directory per language
_GREENFIELD_TEST_DIRS: dict[str, str] = {
    "python": "tests/unit",
    "typescript": "src",          # co-located .test.ts beside source
    "javascript": "src",
    "go": "",                      # co-located _test.go beside source
    "java": "src/test/java",
}

# File extension per language
_FILE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "typescript": ".ts",
    "javascript": ".js",
    "go": ".go",
    "java": ".java",
}

# Test file extensions (used when scanning brownfield repos)
_TEST_FILE_PATTERNS: dict[str, list[str]] = {
    "python": ["test_*.py", "*_test.py"],
    "typescript": ["*.test.ts", "*.spec.ts"],
    "javascript": ["*.test.js", "*.spec.js"],
    "go": ["*_test.go"],
    "java": ["*Test.java", "*Tests.java", "*Spec.java"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TestScaffold:
    """
    Generated test scaffold for one IMPLEMENTER task.

    FR-TEST-001: scaffold must import the implementation module and contain
    at least one stub test per public function/method.
    """
    task_id: str
    language: str
    test_file_path: Path               # absolute or repo-relative path
    content: str                       # generated file content
    source_module: str                 # inferred source module name
    stub_count: int = 0                # number of generated stub tests
    brownfield: bool = False           # True if test dir was inferred from existing files
    warnings: list[str] = field(default_factory=list)

    def to_wme_dict(self) -> dict:
        """Serialize as WME for SOAR Working Memory injection."""
        return {
            "wme_type": "test-scaffold",
            "task-id": self.task_id,
            "language": self.language,
            "test-file": str(self.test_file_path),
            "source-module": self.source_module,
            "stub-count": self.stub_count,
            "brownfield": self.brownfield,
            "warnings": self.warnings,
        }


@dataclass
class FunctionSignature:
    """Parsed public function/method signature for stub generation."""
    name: str
    params: list[str] = field(default_factory=list)
    return_type: str = ""
    is_async: bool = False
    is_method: bool = False           # True if inside a class
    class_name: str = ""


# ---------------------------------------------------------------------------
# Signature parsing (lightweight; not a full AST)
# ---------------------------------------------------------------------------

def _parse_python_signatures(description: str) -> list[FunctionSignature]:
    """
    Extract public function/method signatures from a task description.

    Matches patterns like:
      `calculate_risk(input: dict) -> float`
      `def process(x: int, y: str) -> bool`
    """
    sigs: list[FunctionSignature] = []

    # Match: optional `def ` + identifier + (params) + optional `-> return_type`
    pattern = re.compile(
        r"""
        (?:def\s+)?                           # optional 'def'
        ([a-z_][a-zA-Z0-9_]*)               # function name (snake_case)
        \(([^)]*)\)                          # params block
        (?:\s*->\s*([^\s,;`'"]+))?           # optional return type
        """,
        re.VERBOSE,
    )
    for m in pattern.finditer(description):
        name = m.group(1)
        if name.startswith("_"):             # skip private
            continue
        raw_params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        return_type = (m.group(3) or "").strip()
        sigs.append(FunctionSignature(name=name, params=raw_params, return_type=return_type))

    return sigs


def _parse_typescript_signatures(description: str) -> list[FunctionSignature]:
    """Extract function names from TypeScript-style descriptions."""
    sigs: list[FunctionSignature] = []
    # Match: function/const/export + name + (params)
    pattern = re.compile(
        r"""
        (?:(?:export\s+)?(?:function|const|async\s+function)\s+)?
        ([a-zA-Z_$][a-zA-Z0-9_$]*)          # function name
        \s*[=:]?\s*(?:async\s+)?            # optional async
        \(([^)]*)\)                          # params
        (?:\s*:\s*([^\{;]+?))?              # optional return type
        \s*(?:=>|\{|;)                       # body or end
        """,
        re.VERBOSE,
    )
    for m in pattern.finditer(description):
        name = m.group(1)
        if name[0].isupper() or name.startswith("_"):
            continue  # skip constructors and private
        is_async = "async" in description[max(0, m.start()-6):m.start()]
        raw_params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        return_type = (m.group(3) or "").strip()
        sigs.append(FunctionSignature(
            name=name, params=raw_params, return_type=return_type, is_async=is_async,
        ))
    return sigs


def _extract_function_names(description: str, language: str) -> list[FunctionSignature]:
    """Parse function signatures from the task description."""
    if language == "python":
        return _parse_python_signatures(description)
    elif language in ("typescript", "javascript"):
        return _parse_typescript_signatures(description)
    else:
        return []   # Go/Java: description-based parsing is unreliable; use generic stubs


# ---------------------------------------------------------------------------
# Source module inference
# ---------------------------------------------------------------------------

def _infer_source_module(task_id: str, description: str, language: str, scope: str) -> str:
    """
    Infer the source module name from the task description and scope.

    Strategy:
      1. Look for a snake_case identifier that matches a plausible module name.
      2. Fall back to sanitizing the scope or task_id.
    """
    # Try to find explicit module/file mention in description
    if language == "python":
        # Prefer backtick/quote-wrapped snake_case identifiers, then bare snake_case
        m = re.search(r"[`']([a-z][a-z0-9_]+)(?:\.py)?[`']", description)
        if not m:
            # Bare word boundary snake_case with underscore (e.g. calculate_risk)
            m = re.search(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?:\.py)?\b", description)
        if m and len(m.group(1)) > 3:
            return m.group(1)
    elif language in ("typescript", "javascript"):
        m = re.search(r"[`']([a-zA-Z][a-zA-Z0-9_-]+)(?:\.ts|\.js)?[`']", description)
        if not m:
            m = re.search(r"\b([a-z][a-zA-Z0-9]+)(?:\.ts|\.js)?\b", description)
        if m and len(m.group(1)) > 3:
            return m.group(1)
    elif language == "go":
        m = re.search(r"[`']([a-z][a-z0-9_]+)(?:\.go)?[`']", description)
        if not m:
            m = re.search(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?:\.go)?\b", description)
        if m and len(m.group(1)) > 3:
            return m.group(1)
    elif language == "java":
        m = re.search(r"[`']([A-Z][a-zA-Z0-9]+)(?:\.java)?[`']", description)
        if not m:
            m = re.search(r"\b([A-Z][a-zA-Z0-9]+)(?:\.java)?\b", description)
        if m:
            return m.group(1)

    # Fall back: sanitize scope
    module = re.sub(r"[^a-zA-Z0-9_]", "_", scope).strip("_")
    if not module:
        module = task_id.replace("-", "_").lower()
    return module


# ---------------------------------------------------------------------------
# Test directory inference (brownfield)
# ---------------------------------------------------------------------------

def _infer_test_dir_brownfield(project_root: Path, language: str) -> Optional[Path]:
    """
    Scan the project to find where existing test files live.

    Returns the most common test directory, or None if none found.
    """
    patterns = _TEST_FILE_PATTERNS.get(language, [])
    dirs: dict[Path, int] = {}
    for pattern in patterns:
        for test_file in project_root.rglob(pattern):
            # Skip .git, __pycache__, node_modules, vendor
            parts = test_file.parts
            if any(p in parts for p in (".git", "__pycache__", "node_modules", "vendor", ".specify")):
                continue
            parent = test_file.parent
            dirs[parent] = dirs.get(parent, 0) + 1

    if not dirs:
        return None
    # Return the directory with the most test files
    return max(dirs, key=lambda d: dirs[d])


# ---------------------------------------------------------------------------
# Scaffold content generators
# ---------------------------------------------------------------------------

def _generate_python_scaffold(
    source_module: str,
    task_id: str,
    description: str,
    sigs: list[FunctionSignature],
) -> tuple[str, int]:
    """Generate a pytest scaffold. Returns (content, stub_count)."""
    imports = f"from {source_module} import ("
    if sigs:
        func_list = ",\n    ".join(s.name for s in sigs)
        imports += f"\n    {func_list},\n)"
    else:
        imports += f"\n    # TODO: import public symbols from {source_module}\n)"

    stubs: list[str] = []
    for sig in sigs:
        return_annotation = f" -> {sig.return_type}" if sig.return_type else ""
        # Build a minimal call expression
        args = ", ".join(f"None" for _ in sig.params if "self" not in _)
        call = f"{sig.name}({args})"
        assertion = ""
        if sig.return_type:
            py_type = sig.return_type.split("[")[0].strip()  # e.g. list[int] → list
            assertion = f"\n    assert isinstance(result, {py_type})"
        stubs.append(f"""

def test_{sig.name}_returns_expected_type():
    \"\"\"Stub: {sig.name} — T-{task_id} acceptance criteria.\"\"\"
    result = {call}
    assert result is not None{assertion}
""")

    if not stubs:
        stubs.append(f"""

def test_{source_module}_placeholder():
    \"\"\"Stub: replace with real tests for T-{task_id}.\"\"\"
    pass
""")

    stub_count = max(len(sigs), 1)
    content = f'''"""
Tests for {source_module}.
Generated by SOAR codegen test harness — T-{task_id}.

Task: {description[:120]}
Framework: pytest
"""

from __future__ import annotations

import pytest

{imports}

# ---------------------------------------------------------------------------
# Generated stubs — fill in real implementations
# ---------------------------------------------------------------------------
{''.join(stubs)}
'''
    return content, stub_count


def _generate_typescript_scaffold(
    source_module: str,
    task_id: str,
    description: str,
    sigs: list[FunctionSignature],
) -> tuple[str, int]:
    """Generate a vitest/jest scaffold. Returns (content, stub_count)."""
    named_imports = ", ".join(s.name for s in sigs) if sigs else f"/* TODO: export from {source_module} */"
    import_line = f"import {{ {named_imports} }} from './{source_module}';" if sigs else \
                  f"// import {{ {named_imports} }} from './{source_module}';"

    stubs: list[str] = []
    for sig in sigs:
        args = ", ".join("undefined" for _ in sig.params)
        await_kw = "await " if sig.is_async else ""
        stubs.append(f"""
  it('{sig.name} returns expected value', async () => {{
    // Arrange
    // Act
    const result = {await_kw}{sig.name}({args});
    // Assert
    expect(result).toBeDefined();
  }});
""")

    if not stubs:
        stubs.append(f"""
  it('{source_module} placeholder', () => {{
    // TODO: implement test for T-{task_id}
    expect(true).toBe(true);
  }});
""")

    stub_count = max(len(sigs), 1)
    content = f"""/**
 * Tests for {source_module}.
 * Generated by SOAR codegen test harness — T-{task_id}.
 *
 * Task: {description[:120]}
 * Framework: vitest / jest
 */

import {{ describe, it, expect }} from 'vitest';
{import_line}

// ---------------------------------------------------------------------------
// Generated stubs — fill in real implementations
// ---------------------------------------------------------------------------

describe('{source_module}', () => {{
{''.join(stubs)}
}});
"""
    return content, stub_count


def _generate_go_scaffold(
    source_module: str,
    task_id: str,
    description: str,
) -> tuple[str, int]:
    """Generate a go test scaffold. Returns (content, stub_count)."""
    package_name = re.sub(r"[^a-z0-9]", "", source_module.lower()) or "module"
    content = f"""// Tests for {source_module}.
// Generated by SOAR codegen test harness — T-{task_id}.
//
// Task: {description[:120]}
// Framework: go test

package {package_name}_test

import (
\t"testing"
)

// ---------------------------------------------------------------------------
// Generated stubs — fill in real implementations
// ---------------------------------------------------------------------------

func Test{source_module.capitalize()}Placeholder(t *testing.T) {{
\t// TODO: implement test for T-{task_id}
\tt.Log("scaffold generated by SOAR codegen")
}}
"""
    return content, 1


def _generate_java_scaffold(
    source_module: str,
    task_id: str,
    description: str,
    module_boundary: str,
) -> tuple[str, int]:
    """Generate a JUnit 5 scaffold. Returns (content, stub_count)."""
    class_name = source_module if source_module[0].isupper() else source_module.capitalize()
    package = re.sub(r"[^a-z0-9.]", ".", module_boundary.lower()).strip(".")
    content = f"""/**
 * Tests for {class_name}.
 * Generated by SOAR codegen test harness — T-{task_id}.
 *
 * Task: {description[:120]}
 * Framework: JUnit 5
 */
package {package};

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

// ---------------------------------------------------------------------------
// Generated stubs — fill in real implementations
// ---------------------------------------------------------------------------

class {class_name}Test {{

    @Test
    void placeholder() {{
        // TODO: implement test for T-{task_id}
        assertTrue(true, "scaffold generated by SOAR codegen");
    }}
}}
"""
    return content, 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class TestHarnessGenerator:
    """
    Generates language-appropriate test scaffolding for IMPLEMENTER tasks.

    FR-TEST-001: Every IMPLEMENTER task receives a test scaffold.
    FR-IMPL-003: Scaffold is passed to IMPLEMENTER as TDD basis.
    NFR-PORT-001: Language is detected from CodeTask.language, not hardcoded.
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = project_root or Path.cwd()

    def generate(
        self,
        task_id: str,
        description: str,
        language: str,
        scope: str,
        module_boundary: str,
        brownfield: bool = False,
        output_dir: Optional[Path] = None,
    ) -> TestScaffold:
        """
        Generate a test scaffold for the given task.

        Args:
            task_id:          Task identifier (e.g. "T-001").
            description:      Task description — scanned for function signatures.
            language:         Target language ("python", "typescript", "go", "java").
            scope:            Source module scope (used for naming).
            module_boundary:  Module/package boundary (e.g. "api", "backend").
            brownfield:       If True, infer test directory from existing files.
            output_dir:       Explicit output directory (overrides inference).

        Returns:
            TestScaffold with generated content and file path.
        """
        lang = language.lower().strip()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. "
                f"Supported: {sorted(SUPPORTED_LANGUAGES)}"
            )

        warnings: list[str] = []
        source_module = _infer_source_module(task_id, description, lang, scope)

        # Determine output directory
        if output_dir is not None:
            test_dir = output_dir
        elif brownfield:
            inferred = _infer_test_dir_brownfield(self.project_root, lang)
            if inferred is not None:
                test_dir = inferred
            else:
                warnings.append(
                    f"Brownfield mode: no existing {lang} test files found in {self.project_root}. "
                    f"Using standard greenfield location."
                )
                test_dir = self.project_root / _GREENFIELD_TEST_DIRS[lang]
        else:
            test_dir = self.project_root / _GREENFIELD_TEST_DIRS[lang]

        # Generate scaffold content
        sigs = _extract_function_names(description, lang)
        content, stub_count = self._generate_content(
            lang, source_module, task_id, description, sigs, module_boundary,
        )

        # Build test file path
        test_filename = self._test_filename(lang, source_module)
        test_file_path = test_dir / test_filename

        return TestScaffold(
            task_id=task_id,
            language=lang,
            test_file_path=test_file_path,
            content=content,
            source_module=source_module,
            stub_count=stub_count,
            brownfield=brownfield and not bool(warnings),
            warnings=warnings,
        )

    def write(self, scaffold: TestScaffold) -> Path:
        """Write the scaffold to disk. Creates parent directories if needed."""
        scaffold.test_file_path.parent.mkdir(parents=True, exist_ok=True)
        scaffold.test_file_path.write_text(scaffold.content, encoding="utf-8")
        return scaffold.test_file_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_content(
        self,
        lang: str,
        source_module: str,
        task_id: str,
        description: str,
        sigs: list[FunctionSignature],
        module_boundary: str,
    ) -> tuple[str, int]:
        if lang == "python":
            return _generate_python_scaffold(source_module, task_id, description, sigs)
        elif lang in ("typescript", "javascript"):
            return _generate_typescript_scaffold(source_module, task_id, description, sigs)
        elif lang == "go":
            return _generate_go_scaffold(source_module, task_id, description)
        elif lang == "java":
            return _generate_java_scaffold(source_module, task_id, description, module_boundary)
        else:
            raise ValueError(f"No generator for language '{lang}'")

    def _test_filename(self, lang: str, source_module: str) -> str:
        """Return the test file name following language conventions."""
        if lang == "python":
            return f"test_{source_module}.py"
        elif lang in ("typescript", "javascript"):
            ext = _FILE_EXTENSIONS[lang]
            return f"{source_module}.test{ext}"
        elif lang == "go":
            return f"{source_module}_test.go"
        elif lang == "java":
            class_name = source_module if source_module[0].isupper() else source_module.capitalize()
            return f"{class_name}Test.java"
        return f"test_{source_module}.txt"
