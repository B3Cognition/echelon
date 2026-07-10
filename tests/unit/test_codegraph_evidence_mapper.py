import json
import os
from pathlib import Path
import subprocess
import sys

from harness.codegraph_evidence_mapper import write_codegraph_evidence_map


def _write_fixture(tmp_path: Path, codegraph_symbols: list[dict]) -> tuple[Path, Path, Path]:
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "\n".join(
            [
                "# Requirement Audit",
                "",
                "| ID | Category | Source | Requirement | Acceptance Signal |",
                "| --- | --- | --- | --- | --- |",
                "| FR-004 | functional | spec.md#requirements | Engine awards exactly one Key card per grid-line crossing in the order crossings occur along Route. | Deterministic Route with N crossings produces exactly N key_awarded events. |",
                "| FR-029 | functional | spec.md#requirements | Background saves write a Save State snapshot after mission state changes. | SaveStateRepository write is exercised by tests. |",
                "| FR-999 | functional | spec.md#requirements | Telemetry pipeline emits gameplay events. | telemetry_event is persisted. |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = tmp_path / "codegraph-analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "version": 1,
                "symbols": codegraph_symbols,
                "call_graph": [
                    {
                        "caller": "EngineWiringTests::test_routeResolver_drawsKeysFromDeck_FR004",
                        "callee": "RouteResolver::resolve",
                    }
                ],
                "impact_radius": [
                    {
                        "symbol": "RouteResolver::resolve",
                        "affected": [
                            "EngineWiringTests::test_routeResolver_drawsKeysFromDeck_FR004"
                        ],
                        "depth": 3,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "\n".join(
            [
                "# Tasks",
                "",
                "- [ ] T-004 complexity=standard phase=engine req=FR-004 depends=none",
                "  **Title:** Route resolver key award",
                "- [ ] T-029 complexity=standard phase=persistence req=FR-029 depends=none",
                "  **Title:** Save state repository writes",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return audit, analysis, tasks


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_codegraph_evidence_map_prefers_structural_evidence(tmp_path: Path):
    audit, analysis, tasks = _write_fixture(
        tmp_path,
        [
            {
                "kind": "file",
                "qualified_name": "Packages/Engine/Sources/RouteResolver.swift",
                "name": "RouteResolver.swift",
                "file_path": "Packages/Engine/Sources/RouteResolver.swift",
                "line_start": 1,
                "line_end": 90,
            },
            {
                "kind": "method",
                "qualified_name": "RouteResolver::resolve",
                "name": "resolve",
                "file_path": "Packages/Engine/Sources/RouteResolver.swift",
                "line_start": 12,
                "line_end": 44,
            },
            {
                "kind": "method",
                "qualified_name": "EngineWiringTests::test_routeResolver_drawsKeysFromDeck_FR004",
                "name": "test_routeResolver_drawsKeysFromDeck_FR004",
                "file_path": "Packages/Engine/Tests/EngineWiringTests.swift",
                "line_start": 51,
                "line_end": 70,
            },
            {
                "kind": "class",
                "qualified_name": "SaveStateRepository",
                "name": "SaveStateRepository",
                "file_path": "Packages/Engine/Sources/Persistence/SaveStateRepository.swift",
                "line_start": 1,
                "line_end": 48,
            },
        ],
    )
    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"

    result = write_codegraph_evidence_map(
        requirement_audit_path=audit,
        codegraph_analysis_path=analysis,
        tasks_path=tasks,
        out_json_path=out_json,
        out_md_path=out_md,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in payload["requirements"]}

    assert result.counts["high"] == 0
    assert result.counts["medium"] == 1
    assert payload["summary"]["fallback_requirement_ids"] == ["FR-029", "FR-999"]
    assert by_id["FR-004"]["confidence"] == "medium"
    assert by_id["FR-004"]["evidence_kind"] == "source_and_test"
    assert by_id["FR-004"]["evidence_strength"] == "moderate"
    assert by_id["FR-004"]["task_ids"] == ["T-004"]
    assert "RouteResolver::resolve" in by_id["FR-004"]["implementation_evidence"][0]["symbol"]
    assert (
        "EngineWiringTests::test_routeResolver_drawsKeysFromDeck_FR004"
        in by_id["FR-004"]["test_evidence"][0]["symbol"]
    )

    assert by_id["FR-029"]["confidence"] == "low"
    assert by_id["FR-029"]["implementation_evidence"]
    assert by_id["FR-029"]["test_evidence"] == []

    assert by_id["FR-999"]["confidence"] == "none"
    assert by_id["FR-999"]["implementation_evidence"] == []
    assert by_id["FR-999"]["negative_evidence"]

    markdown = out_md.read_text(encoding="utf-8")
    assert "| FR-004 | medium | source_and_test | moderate | False |" in markdown
    assert "| FR-999 | none | none | none | False |" in markdown


def test_codegraph_evidence_map_does_not_substring_match_short_acronyms(tmp_path: Path):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "\n".join(
            [
                "# Requirement Audit",
                "",
                "| ID | Category | Source | Requirement | Acceptance Signal |",
                "| --- | --- | --- | --- | --- |",
                "| FR-042 | functional | spec.md#requirements | AR overlay renders portal alignment. | ARKit view is visible. |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    analysis = tmp_path / "codegraph-analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "kind": "class",
                        "qualified_name": "StarArrivalView",
                        "name": "StarArrivalView",
                        "file_path": "NavigationalPortal/Features/Flight/StarArrivalView.swift",
                    },
                    {
                        "kind": "struct",
                        "qualified_name": "CardView",
                        "name": "CardView",
                        "file_path": "NavigationalPortal/Features/GameSession/CardView.swift",
                    },
                ],
                "call_graph": [],
                "impact_radius": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "- [ ] T-042 complexity=standard phase=ui req=FR-042 depends=none\n",
        encoding="utf-8",
    )

    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"
    write_codegraph_evidence_map(
        requirement_audit_path=audit,
        codegraph_analysis_path=analysis,
        tasks_path=tasks,
        out_json_path=out_json,
        out_md_path=out_md,
    )

    entry = json.loads(out_json.read_text(encoding="utf-8"))["requirements"][0]
    assert entry["id"] == "FR-042"
    assert entry["confidence"] == "none"
    assert entry["implementation_evidence"] == []


def test_term_match_only_source_and_test_stays_in_fallback_queue(tmp_path: Path):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "\n".join(
            [
                "# Requirement Audit",
                "",
                "| ID | Category | Source | Requirement | Acceptance Signal |",
                "| --- | --- | --- | --- | --- |",
                "| FR-064 | functional | spec.md#requirements | Animation loop maintains stable frame timing while rendering theme sprites. | Measured runtime artifact shows frame intervals remain within tolerance. |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    analysis = tmp_path / "codegraph-analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "kind": "class",
                        "qualified_name": "Frame",
                        "name": "Frame",
                        "file_path": "src/asciianim/frame.py",
                    },
                    {
                        "kind": "method",
                        "qualified_name": "ThemeTests::test_frame_theme_rendering",
                        "name": "test_frame_theme_rendering",
                        "file_path": "tests/test_theme_frame.py",
                    },
                ],
                "call_graph": [],
                "impact_radius": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "- [ ] T-064 complexity=standard phase=runtime req=FR-064 depends=none\n",
        encoding="utf-8",
    )

    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"
    write_codegraph_evidence_map(
        requirement_audit_path=audit,
        codegraph_analysis_path=analysis,
        tasks_path=tasks,
        out_json_path=out_json,
        out_md_path=out_md,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    entry = payload["requirements"][0]
    assert entry["evidence_kind"] == "source_and_test"
    assert entry["confidence"] == "low"
    assert entry["id"] in payload["summary"]["fallback_requirement_ids"]


def test_requirement_anchored_test_lifts_called_implementation_symbol(tmp_path: Path):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "\n".join(
            [
                "# Requirement Audit",
                "",
                "| ID | Category | Source | Requirement | Acceptance Signal |",
                "| --- | --- | --- | --- | --- |",
                "| FR-021 | functional | spec.md#requirements | Piped input duration remains deterministic. | `tests/test_cli.py::test_FR021_piped_duration` exercises replay timing. |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    analysis = tmp_path / "codegraph-analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "kind": "method",
                        "qualified_name": "asciianim.engine.Engine::run",
                        "name": "run",
                        "file_path": "src/asciianim/engine.py",
                    },
                    {
                        "kind": "function",
                        "qualified_name": "tests.test_cli::test_FR021_piped_duration",
                        "name": "test_FR021_piped_duration",
                        "file_path": "tests/test_cli.py",
                    },
                ],
                "call_graph": [
                    {
                        "caller": "tests.test_cli::test_FR021_piped_duration",
                        "callee": "asciianim.engine.Engine::run",
                    }
                ],
                "impact_radius": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "- [ ] T-021 complexity=standard phase=runtime req=FR-021 depends=none\n",
        encoding="utf-8",
    )
    coverage = tmp_path / "coverage-map.md"
    coverage.write_text(
        "| ID | Test Evidence |\n"
        "| --- | --- |\n"
        "| FR-021 | tests/test_cli.py::test_FR021_piped_duration |\n",
        encoding="utf-8",
    )

    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"
    write_codegraph_evidence_map(
        requirement_audit_path=audit,
        codegraph_analysis_path=analysis,
        tasks_path=tasks,
        out_json_path=out_json,
        out_md_path=out_md,
        coverage_map_path=coverage,
    )

    entry = json.loads(out_json.read_text(encoding="utf-8"))["requirements"][0]
    assert entry["confidence"] == "medium"
    assert entry["evidence_kind"] == "source_and_test"
    assert entry["implementation_evidence"][0]["symbol"] == "asciianim.engine.Engine::run"
    assert entry["implementation_evidence"][0]["reasons"] == [
        "call_graph_from_test:tests.test_cli::test_FR021_piped_duration"
    ]


def test_runtime_threshold_assertion_only_evidence_is_not_high_confidence(tmp_path: Path):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "\n".join(
            [
                "# Requirement Audit",
                "",
                "| ID | Category | Source | Requirement | Acceptance Signal |",
                "| --- | --- | --- | --- | --- |",
                "| NFR-001 | non-functional | spec.md#nfr | Map renderer maintains 60 fps during route animation. | CI artifact records measured frame-rate p95 >= 60 fps on device matrix. |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    analysis = tmp_path / "codegraph-analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "kind": "method",
                        "qualified_name": "ReleaseCandidateGate::assertNFR001FrameRate60fps",
                        "name": "assertNFR001FrameRate60fps",
                        "file_path": "Packages/Engine/Sources/Telemetry/ReleaseCandidateGate.swift",
                    },
                    {
                        "kind": "method",
                        "qualified_name": "ReleaseCandidateGateTests::test_NFR001_FrameRate60fps_releaseCandidateGate",
                        "name": "test_NFR001_FrameRate60fps_releaseCandidateGate",
                        "file_path": "Packages/Engine/Tests/ReleaseCandidateGateTests.swift",
                    },
                ],
                "call_graph": [],
                "impact_radius": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "- [ ] T-001 complexity=standard phase=quality req=NFR-001 depends=none\n",
        encoding="utf-8",
    )

    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"
    write_codegraph_evidence_map(
        requirement_audit_path=audit,
        codegraph_analysis_path=analysis,
        tasks_path=tasks,
        out_json_path=out_json,
        out_md_path=out_md,
    )

    entry = json.loads(out_json.read_text(encoding="utf-8"))["requirements"][0]
    assert entry["evidence_kind"] == "assertion_only"
    assert entry["evidence_strength"] == "weak"
    assert entry["confidence"] == "low"
    assert entry["runtime_threshold"] is True
    assert entry["id"] in json.loads(out_json.read_text(encoding="utf-8"))["summary"]["fallback_requirement_ids"]


def test_write_codegraph_evidence_map_cli(tmp_path: Path):
    audit, analysis, tasks = _write_fixture(
        tmp_path,
        [
            {
                "kind": "method",
                "qualified_name": "RouteResolver::resolve",
                "name": "resolve",
                "file_path": "Packages/Engine/Sources/RouteResolver.swift",
            },
            {
                "kind": "method",
                "qualified_name": "EngineWiringTests::test_routeResolver_drawsKeysFromDeck_FR004",
                "name": "test_routeResolver_drawsKeysFromDeck_FR004",
                "file_path": "Packages/Engine/Tests/EngineWiringTests.swift",
            },
        ],
    )
    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"
    (tmp_path / "state.json").write_text("{}\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness",
            "write-codegraph-evidence-map",
            str(audit),
            str(analysis),
            str(tasks),
            str(out_json),
            str(out_md),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "OK: wrote CodeGraph evidence map" in completed.stdout
    assert out_json.is_file()
    assert out_md.is_file()


def test_write_codegraph_evidence_map_cli_stamps_success_state(tmp_path: Path):
    audit, analysis, tasks = _write_fixture(
        tmp_path,
        [
            {
                "kind": "method",
                "qualified_name": "RouteResolver::resolve",
                "name": "resolve",
                "file_path": "Packages/Engine/Sources/RouteResolver.swift",
            }
        ],
    )
    (tmp_path / "state.json").write_text(
        '{"structural_evidence":"ready"}\n',
        encoding="utf-8",
    )
    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"

    completed = _run_harness(
        [
            "write-codegraph-evidence-map",
            str(audit),
            str(analysis),
            str(tasks),
            str(out_json),
            str(out_md),
        ]
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["codegraph_evidence_map"] == "ready"


def test_write_codegraph_evidence_map_cli_reports_missing_audit_without_traceback(
    tmp_path: Path,
):
    analysis = tmp_path / "codegraph-analysis.json"
    analysis.write_text('{"symbols":[],"call_graph":[]}\n', encoding="utf-8")
    tasks = tmp_path / "tasks.md"
    tasks.write_text("# Tasks\n", encoding="utf-8")

    completed = _run_harness(
        [
            "write-codegraph-evidence-map",
            str(tmp_path / "requirement-audit.md"),
            str(analysis),
            str(tasks),
            str(tmp_path / "codegraph-evidence-map.json"),
            str(tmp_path / "codegraph-evidence-map.md"),
        ]
    )

    assert completed.returncode == 2
    assert "missing required input:" in completed.stderr
    assert "requirement-audit.md" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_write_codegraph_evidence_map_cli_skips_when_codegraph_degraded(
    tmp_path: Path,
):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | functional | spec.md:1 | Build one thing | Observe one thing |\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.md"
    tasks.write_text("- [ ] T-001 req=FR-001\n", encoding="utf-8")
    (tmp_path / "state.json").write_text(
        '{"structural_evidence":"degraded"}\n',
        encoding="utf-8",
    )
    out_json = tmp_path / "codegraph-evidence-map.json"
    out_md = tmp_path / "codegraph-evidence-map.md"

    completed = _run_harness(
        [
            "write-codegraph-evidence-map",
            str(audit),
            str(tmp_path / "codegraph-analysis.json"),
            str(tasks),
            str(out_json),
            str(out_md),
        ]
    )

    assert completed.returncode == 0, completed.stderr
    assert "skipped degraded CodeGraph evidence map" in completed.stdout
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped_degraded_codegraph"
    assert "CodeGraph evidence was degraded" in out_md.read_text(encoding="utf-8")
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["codegraph_evidence_map"] == "skipped_degraded_codegraph"


def test_write_codegraph_evidence_map_cli_requires_state_when_analysis_absent(
    tmp_path: Path,
):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | functional | spec.md:1 | Build one thing | Observe one thing |\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.md"
    tasks.write_text("- [ ] T-001 req=FR-001\n", encoding="utf-8")

    completed = _run_harness(
        [
            "write-codegraph-evidence-map",
            str(audit),
            str(tmp_path / "codegraph-analysis.json"),
            str(tasks),
            str(tmp_path / "codegraph-evidence-map.json"),
            str(tmp_path / "codegraph-evidence-map.md"),
        ]
    )

    assert completed.returncode == 1
    assert "state.json missing for verify-spec run:" in completed.stderr
    assert "Traceback" not in completed.stderr
