from __future__ import annotations

from pathlib import Path

import pytest

from harness.stacks.errors import StackValidationError
from harness.stacks.schema import StackRunnability, parse_stack_definition


VALID_STACK = {
    "schema_version": "1.0",
    "stack": {
        "id": "example-web",
        "name": "Example Web",
        "version": "1.0.0",
        "kind": "capability",
        "owner": "example",
        "description": "Example stack",
    },
    "applies_to": {"archetypes": ["web_app"]},
    "provides": {"ui.components": "example"},
    "requires": {"commands": ["npx"], "registries": ["example-registry"]},
    "tools": {
        "example_cli": {
            "type": "cli",
            "command": "npx",
            "args": ["-y", "example"],
            "phase_scope": ["spec", "delivery"],
            "purpose": "lookup",
            "commands": {
                "list": {
                    "args": ["list", "--json"],
                    "output": "json",
                    "gate": False,
                }
            },
        }
    },
    "context": {"files": ["context.md"]},
    "implies": [],
    "conflicts": [],
}


def _postgres_stack_raw() -> dict:
    return {
        **VALID_STACK,
        "schema_version": "1.1",
        "provisioning": [
            {
                "id": "postgres-verify",
                "scope": "verification",
                "services": ["postgres"],
                "environment": {"required": ["DATABASE_URL"]},
                "readiness": {"command": "pg_isready"},
                "satisfiers": [
                    {"kind": "environment", "variable": "DATABASE_URL"},
                    {
                        "kind": "compose-template",
                        "output": "docker-compose.echelon-verify.yml",
                        "env_example": ".env.echelon-verify.example",
                    },
                ],
            }
        ],
    }


@pytest.mark.unit
def test_parse_valid_stack_definition() -> None:
    stack = parse_stack_definition(VALID_STACK, Path("stack.yml"))

    assert stack.id == "example-web"
    assert stack.kind == "capability"
    assert stack.applies_to_archetypes == ["web_app"]
    assert stack.provides == {"ui.components": "example"}
    assert stack.tools["example_cli"].command == "npx"
    assert stack.tools["example_cli"].commands["list"].output == "json"


@pytest.mark.unit
def test_stack_schema_parses_required_linux_runnability() -> None:
    raw = {
        **VALID_STACK,
        "schema_version": "1.2",
        "runnability": {
            "classification": "user_facing",
            "policy": "required",
            "runner": "linux_container",
            "capabilities": ["install", "start", "primary_journey", "stop"],
            "required_observations": ["browser_dom"],
        },
    }

    parsed = parse_stack_definition(raw, Path("stack.yml"))

    assert parsed.runnability == StackRunnability(
        classification="user_facing",
        policy="required",
        runner="linux_container",
        capabilities=("install", "start", "primary_journey", "stop"),
        required_observations=("browser_dom",),
    )


@pytest.mark.unit
def test_stack_schema_rejects_runnability_before_schema_1_2() -> None:
    raw = {
        **VALID_STACK,
        "runnability": {
            "classification": "user_facing",
            "policy": "required",
            "runner": "linux_container",
        },
    }

    with pytest.raises(
        StackValidationError,
        match="runnability requires stack schema_version 1.2",
    ):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("classification", "application", "classification"),
        ("policy", "optional", "policy"),
        ("runner", "host", "runner"),
        ("capabilities", ["start", "start"], "duplicate"),
        ("required_observations", ["browser_dom", "shell_text"], "observation"),
        ("unknown", True, "unknown runnability key"),
    ],
)
def test_stack_schema_rejects_invalid_runnability_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    runnability = {
        "classification": "user_facing",
        "policy": "required",
        "runner": "linux_container",
        "capabilities": ["start"],
        "required_observations": ["browser_dom"],
    }
    runnability[field] = value
    raw = {**VALID_STACK, "schema_version": "1.2", "runnability": runnability}

    with pytest.raises(StackValidationError, match=message):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_stack_schema_parses_postgres_verification_provisioner(tmp_path: Path) -> None:
    definition = parse_stack_definition(_postgres_stack_raw(), tmp_path / "stack.yml")

    provisioner = definition.provisioners[0]
    assert provisioner.id == "postgres-verify"
    assert provisioner.required_environment == ["DATABASE_URL"]
    assert provisioner.satisfiers[1].output == "docker-compose.echelon-verify.yml"


@pytest.mark.unit
def test_stack_schema_rejects_output_outside_target(tmp_path: Path) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0]["satisfiers"][1]["output"] = "../compose.yml"

    with pytest.raises(StackValidationError, match="target-relative"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
def test_stack_schema_rejects_env_example_outside_target(tmp_path: Path) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0]["satisfiers"][1]["env_example"] = "../.env"

    with pytest.raises(StackValidationError, match="target-relative"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
def test_stack_schema_rejects_partial_compose_artifact_pair(tmp_path: Path) -> None:
    raw = _postgres_stack_raw()
    del raw["provisioning"][0]["satisfiers"][1]["env_example"]

    with pytest.raises(StackValidationError, match="fixed artifact pair"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
def test_stack_schema_rejects_unsupported_satisfier_kind(tmp_path: Path) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0]["satisfiers"][0]["kind"] = "shell"

    with pytest.raises(StackValidationError, match="unsupported satisfier kind"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("variable", None, "must declare variable"),
        ("output", "unexpected.yml", "does not support output"),
    ],
)
def test_stack_schema_rejects_malformed_environment_satisfier(
    tmp_path: Path,
    field: str,
    value: str | None,
    message: str,
) -> None:
    raw = _postgres_stack_raw()
    satisfier = raw["provisioning"][0]["satisfiers"][0]
    if value is None:
        satisfier.pop(field)
    else:
        satisfier[field] = value

    with pytest.raises(StackValidationError, match=message):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
def test_stack_schema_rejects_environment_variable_not_declared_by_provisioner(
    tmp_path: Path,
) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0]["satisfiers"][0]["variable"] = "OTHER_URL"

    with pytest.raises(StackValidationError, match="environment.required"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
def test_stack_schema_rejects_compose_satisfier_variable(tmp_path: Path) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0]["satisfiers"][1]["variable"] = "DATABASE_URL"

    with pytest.raises(StackValidationError, match="does not support variable"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("services", ["postgres\n  injected: {}"]),
        ("readiness", {"command": "pg_isready\n# injected"}),
    ],
)
def test_stack_schema_rejects_non_allowlisted_compose_contract(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    raw = _postgres_stack_raw()
    raw["provisioning"][0][field] = value

    with pytest.raises(StackValidationError, match="supported PostgreSQL contract"):
        parse_stack_definition(raw, tmp_path / "stack.yml")


@pytest.mark.unit
def test_parse_optional_detection_rules() -> None:
    raw = {
        **VALID_STACK,
        "detection": {
            "positive": {
                "technologies": ["react", "nx"],
                "dependencies": ["@statsperform/react-playbook"],
                "files": ["package.json"],
            },
            "negative": {
                "technologies": ["nestjs"],
            },
            "modernization": {
                "technologies": ["nextjs"],
                "dependencies": ["legacy-ui"],
                "files": ["webpack.config.js"],
            },
        },
    }

    stack = parse_stack_definition(raw, Path("stack.yml"))

    assert stack.detection.positive.technologies == ["react", "nx"]
    assert stack.detection.positive.dependencies == ["@statsperform/react-playbook"]
    assert stack.detection.positive.files == ["package.json"]
    assert stack.detection.negative.technologies == ["nestjs"]
    assert stack.detection.modernization.dependencies == ["legacy-ui"]
    assert stack.detection.modernization.files == ["webpack.config.js"]


@pytest.mark.unit
def test_detection_defaults_to_empty_rule_groups() -> None:
    stack = parse_stack_definition(VALID_STACK, Path("stack.yml"))

    assert stack.detection.positive.technologies == []
    assert stack.detection.negative.dependencies == []
    assert stack.detection.modernization.files == []


@pytest.mark.unit
def test_rejects_invalid_detection_list_entry() -> None:
    raw = {
        **VALID_STACK,
        "detection": {
            "positive": {
                "technologies": ["react", 7],
            },
        },
    }

    with pytest.raises(StackValidationError, match="detection.positive.technologies"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_unknown_core_namespace() -> None:
    raw = {**VALID_STACK, "provides": {"unknown.capability": "value"}}

    with pytest.raises(StackValidationError, match="unknown capability namespace"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_allows_extension_namespace() -> None:
    raw = {**VALID_STACK, "provides": {"x.example.capability": "value"}}

    stack = parse_stack_definition(raw, Path("stack.yml"))

    assert stack.provides == {"x.example.capability": "value"}


@pytest.mark.unit
def test_rejects_invalid_kind() -> None:
    raw = {
        **VALID_STACK,
        "stack": {**VALID_STACK["stack"], "kind": "template"},
    }

    with pytest.raises(StackValidationError, match="kind"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_missing_context_files() -> None:
    raw = {**VALID_STACK, "context": {"files": []}}

    with pytest.raises(StackValidationError, match="context.files"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_invalid_phase_scope() -> None:
    raw = {
        **VALID_STACK,
        "tools": {
            "example_cli": {
                "type": "cli",
                "command": "npx",
                "phase_scope": ["spec", "qa"],
            }
        },
    }

    with pytest.raises(StackValidationError, match="phase_scope"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_unsupported_schema_version() -> None:
    raw = {**VALID_STACK, "schema_version": "2.0"}

    with pytest.raises(StackValidationError, match="unsupported stack schema_version"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_schema_version() -> None:
    raw = {**VALID_STACK, "schema_version": 1.0}

    with pytest.raises(StackValidationError, match="schema_version must be a string"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_stack_id() -> None:
    raw = {**VALID_STACK, "stack": {**VALID_STACK["stack"], "id": 123}}

    with pytest.raises(StackValidationError, match="stack.id"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_archetype_entry() -> None:
    raw = {**VALID_STACK, "applies_to": {"archetypes": [False]}}

    with pytest.raises(StackValidationError, match="applies_to.archetypes"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_requires_command_entry() -> None:
    raw = {**VALID_STACK, "requires": {"commands": [7]}}

    with pytest.raises(StackValidationError, match="requires.commands"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_empty_applies_to_archetypes() -> None:
    raw = {**VALID_STACK, "applies_to": {"archetypes": []}}

    with pytest.raises(StackValidationError, match="at least one archetype"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_empty_provides() -> None:
    raw = {**VALID_STACK, "provides": {}}

    with pytest.raises(StackValidationError, match="at least one capability"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_capability_value() -> None:
    raw = {**VALID_STACK, "provides": {"ui.components": 123}}

    with pytest.raises(StackValidationError, match="provides.ui.components"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_owner() -> None:
    raw = {**VALID_STACK, "stack": {**VALID_STACK["stack"], "owner": 123}}

    with pytest.raises(StackValidationError, match="stack.owner"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_description() -> None:
    raw = {
        **VALID_STACK,
        "stack": {**VALID_STACK["stack"], "description": {"text": "value"}},
    }

    with pytest.raises(StackValidationError, match="stack.description"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_tool_type() -> None:
    raw = {**VALID_STACK, "tools": {"example_cli": {"type": 1, "command": "npx"}}}

    with pytest.raises(StackValidationError, match="tools.example_cli.type"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_tool_purpose() -> None:
    raw = {
        **VALID_STACK,
        "tools": {
            "example_cli": {
                "type": "cli",
                "command": "npx",
                "purpose": [],
            }
        },
    }

    with pytest.raises(StackValidationError, match="tools.example_cli.purpose"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_command_output() -> None:
    raw = {
        **VALID_STACK,
        "tools": {
            "example_cli": {
                "type": "cli",
                "command": "npx",
                "commands": {"list": {"output": 5}},
            }
        },
    }

    with pytest.raises(StackValidationError, match="tools.example_cli.commands.list.output"):
        parse_stack_definition(raw, Path("stack.yml"))
