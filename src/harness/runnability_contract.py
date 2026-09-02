"""Typed candidate-worktree contract for deterministic user-runnability checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


CONTRACT_PATH = Path(".echelon/runnability.yml")
ALLOWED_VARIABLES = frozenset(
    {
        "ECHELON_PORT",
        "ECHELON_BASE_URL",
        "ECHELON_MARKER",
        "ECHELON_SESSION_TOKEN",
    }
)
SUPPORTED_JOURNEY_KINDS = frozenset({"browser", "http", "exec"})
SUPPORTED_SERVICES = frozenset({"web", "api", "postgres"})
SUPPORTED_STEP_ACTIONS = frozenset({"goto", "click", "fill", "press", "expect", "exec"})
SUPPORTED_OBSERVATION_KINDS = frozenset(
    {"browser_dom", "http", "exec", "postgres_query"}
)


class RunnabilityContractError(ValueError):
    """Raised when a candidate runnability contract is unsafe or incomplete."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise RunnabilityContractError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class RunnabilityReadiness:
    url: str
    timeout_ms: int


@dataclass(frozen=True)
class RunnabilityIdentity:
    command: str
    stdout_json: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class JourneyStep:
    action: str
    path: str | None = None
    selector: str | None = None
    state: str | None = None
    key: str | None = None
    value: str | None = None
    command: str | None = None
    repeat: int = 1


@dataclass(frozen=True)
class Observation:
    id: str
    kind: str
    expectation: str
    selector: str | None = None
    statement: str | None = None
    parameters: tuple[str, ...] = ()
    url: str | None = None
    method: str | None = None
    command: str | None = None


@dataclass(frozen=True)
class PrimaryJourney:
    kind: str
    url: str | None
    requirements: tuple[str, ...]
    real_services_required: tuple[str, ...]
    session_storage: tuple[tuple[str, str], ...]
    steps: tuple[JourneyStep, ...]
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class PersistenceProbe:
    restart_commands: tuple[str, ...]
    observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class LocalUserJourney:
    prerequisites: tuple[str, ...]
    provision_commands: tuple[str, ...]
    readiness_commands: tuple[str, ...]
    prepare_commands: tuple[str, ...]
    verify_commands: tuple[str, ...]
    start_commands: tuple[str, ...]
    open_urls: tuple[str, ...]
    stop_commands: tuple[str, ...]
    cleanup_commands: tuple[str, ...]


@dataclass(frozen=True)
class RunnabilityContract:
    schema_version: int
    enabled: bool
    install_commands: tuple[str, ...]
    bootstrap_commands: tuple[str, ...]
    start_commands: tuple[str, ...]
    readiness: RunnabilityReadiness
    identity: RunnabilityIdentity | None
    primary_journey: PrimaryJourney
    persistence_probe: PersistenceProbe | None
    stop_commands: tuple[str, ...]
    local_journey: LocalUserJourney | None = None


_ROOT_FIELDS = {
    "schema_version",
    "enabled",
    "install_commands",
    "bootstrap_commands",
    "start_commands",
    "readiness",
    "identity",
    "primary_journey",
    "persistence_probe",
    "stop_commands",
    "local_journey",
}
_READINESS_FIELDS = {"url", "timeout_ms"}
_IDENTITY_FIELDS = {"command", "stdout_json"}
_JOURNEY_FIELDS = {
    "kind",
    "url",
    "requirements",
    "real_services_required",
    "session_storage",
    "steps",
    "observations",
}
_STEP_FIELDS = {"action", "path", "selector", "state", "key", "value", "command", "repeat"}
_OBSERVATION_FIELDS = {
    "id",
    "kind",
    "expectation",
    "selector",
    "statement",
    "parameters",
    "url",
    "method",
    "command",
}
_PERSISTENCE_FIELDS = {"restart_commands", "observations"}
_LOCAL_JOURNEY_FIELDS = {
    "prerequisites",
    "provision_commands",
    "readiness_commands",
    "prepare_commands",
    "verify_commands",
    "start_commands",
    "open_urls",
    "stop_commands",
    "cleanup_commands",
}
_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_runnability_contract(worktree: Path) -> RunnabilityContract | None:
    root = worktree.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise RunnabilityContractError(f"candidate worktree is not a directory: {root}")
    path = root / CONTRACT_PATH
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RunnabilityContractError(f"contract must be a regular file: {CONTRACT_PATH}")
    try:
        path.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise RunnabilityContractError("contract escapes candidate worktree") from exc
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RunnabilityContractError(f"cannot parse {CONTRACT_PATH}: {exc}") from exc
    root_raw = _mapping(raw, "root")
    _reject_unknown(root_raw, _ROOT_FIELDS, "root")
    _validate_variables(root_raw)

    schema_version = root_raw.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise RunnabilityContractError("schema_version must be integer 1")
    enabled = root_raw.get("enabled")
    if type(enabled) is not bool:
        raise RunnabilityContractError("enabled must be a boolean")
    if not enabled:
        return RunnabilityContract(
            schema_version=1,
            enabled=False,
            install_commands=(),
            bootstrap_commands=(),
            start_commands=(),
            readiness=RunnabilityReadiness(url="", timeout_ms=0),
            identity=None,
            primary_journey=PrimaryJourney(
                kind="",
                url=None,
                requirements=(),
                real_services_required=(),
                session_storage=(),
                steps=(),
                observations=(),
            ),
            persistence_probe=None,
            stop_commands=(),
            local_journey=None,
        )

    readiness = _parse_readiness(root_raw.get("readiness"))
    identity = _parse_identity(root_raw.get("identity"))
    journey = _parse_journey(root_raw.get("primary_journey"))
    persistence = _parse_persistence(
        root_raw.get("persistence_probe"),
        observation_ids={item.id for item in journey.observations},
    )
    local_journey = _parse_local_journey(root_raw.get("local_journey"))
    start_commands = _commands(root_raw.get("start_commands"), "start_commands")
    stop_commands = _commands(root_raw.get("stop_commands"), "stop_commands")
    if enabled and not start_commands:
        raise RunnabilityContractError("start_commands must contain at least one command")
    if enabled and not stop_commands:
        raise RunnabilityContractError("stop_commands must contain at least one command")
    return RunnabilityContract(
        schema_version=1,
        enabled=enabled,
        install_commands=_commands(
            root_raw.get("install_commands", []), "install_commands"
        ),
        bootstrap_commands=_commands(
            root_raw.get("bootstrap_commands", []), "bootstrap_commands"
        ),
        start_commands=start_commands,
        readiness=readiness,
        identity=identity,
        primary_journey=journey,
        persistence_probe=persistence,
        stop_commands=stop_commands,
        local_journey=local_journey,
    )


def runnability_contract_sha256(contract: RunnabilityContract) -> str:
    encoded = json.dumps(
        asdict(contract),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_readiness(value: Any) -> RunnabilityReadiness:
    raw = _mapping(value, "readiness")
    _reject_unknown(raw, _READINESS_FIELDS, "readiness")
    url = _string(raw.get("url"), "readiness.url")
    if not (
        url.startswith("http://127.0.0.1:")
        or url.startswith("http://localhost:")
    ):
        raise RunnabilityContractError("readiness.url must use a loopback HTTP origin")
    timeout_ms = raw.get("timeout_ms")
    if type(timeout_ms) is not int or not 1_000 <= timeout_ms <= 600_000:
        raise RunnabilityContractError("readiness.timeout_ms must be between 1000 and 600000")
    return RunnabilityReadiness(url=url, timeout_ms=timeout_ms)


def _parse_identity(value: Any) -> RunnabilityIdentity | None:
    if value is None:
        return None
    raw = _mapping(value, "identity")
    _reject_unknown(raw, _IDENTITY_FIELDS, "identity")
    exports_raw = _mapping(raw.get("stdout_json"), "identity.stdout_json")
    if not exports_raw:
        raise RunnabilityContractError("identity.stdout_json must declare an export")
    exports: list[tuple[str, str]] = []
    for key, variable in exports_raw.items():
        source_key = _string(key, "identity.stdout_json key")
        target = _string(variable, f"identity.stdout_json.{source_key}")
        if target not in ALLOWED_VARIABLES:
            raise RunnabilityContractError(
                f"identity export is not harness-owned: {target}"
            )
        exports.append((source_key, target))
    return RunnabilityIdentity(
        command=_command(raw.get("command"), "identity.command"),
        stdout_json=tuple(exports),
    )


def _parse_journey(value: Any) -> PrimaryJourney:
    raw = _mapping(value, "primary_journey")
    _reject_unknown(raw, _JOURNEY_FIELDS, "primary_journey")
    kind = _string(raw.get("kind"), "primary_journey.kind")
    if kind not in SUPPORTED_JOURNEY_KINDS:
        raise RunnabilityContractError(f"unsupported journey kind: {kind}")
    url = _optional_string(raw.get("url"), "primary_journey.url")
    requirements = tuple(
        _non_empty_string_list(raw.get("requirements"), "primary_journey.requirements")
    )
    service_names = _unique_strings(
        raw.get("real_services_required", []),
        "primary_journey.real_services_required",
    )
    unknown_services = [item for item in service_names if item not in SUPPORTED_SERVICES]
    if unknown_services:
        raise RunnabilityContractError(
            f"unsupported real service: {unknown_services[0]}"
        )
    session_raw = _mapping(raw.get("session_storage", {}), "primary_journey.session_storage")
    session_storage = tuple(
        (
            _string(key, "primary_journey.session_storage key"),
            _string(item, f"primary_journey.session_storage.{key}"),
        )
        for key, item in session_raw.items()
    )
    steps = tuple(_parse_steps(raw.get("steps")))
    observations = tuple(_parse_observations(raw.get("observations")))
    if not observations:
        raise RunnabilityContractError(
            "primary_journey requires an observable assertion beyond exit status"
        )
    if kind == "browser":
        if url is None:
            raise RunnabilityContractError("browser journey requires url")
        if not any(step.action == "goto" for step in steps):
            raise RunnabilityContractError("browser journey requires a goto step")
        if not any(item.kind == "browser_dom" for item in observations):
            raise RunnabilityContractError(
                "browser journey requires a browser_dom observable assertion"
            )
    return PrimaryJourney(
        kind=kind,
        url=url,
        requirements=requirements,
        real_services_required=tuple(service_names),
        session_storage=session_storage,
        steps=steps,
        observations=observations,
    )


def _parse_steps(value: Any) -> list[JourneyStep]:
    rows = _list(value, "primary_journey.steps")
    if not rows:
        raise RunnabilityContractError("primary_journey.steps must not be empty")
    steps: list[JourneyStep] = []
    for index, value in enumerate(rows):
        field = f"primary_journey.steps[{index}]"
        raw = _mapping(value, field)
        _reject_unknown(raw, _STEP_FIELDS, field)
        action = _string(raw.get("action"), f"{field}.action")
        if action not in SUPPORTED_STEP_ACTIONS:
            raise RunnabilityContractError(f"unsupported journey action: {action}")
        repeat = raw.get("repeat", 1)
        if type(repeat) is not int or not 1 <= repeat <= 1000:
            raise RunnabilityContractError(f"{field}.repeat must be between 1 and 1000")
        step = JourneyStep(
            action=action,
            path=_optional_string(raw.get("path"), f"{field}.path"),
            selector=_optional_string(raw.get("selector"), f"{field}.selector"),
            state=_optional_string(raw.get("state"), f"{field}.state"),
            key=_optional_string(raw.get("key"), f"{field}.key"),
            value=_optional_string(raw.get("value"), f"{field}.value"),
            command=_optional_string(raw.get("command"), f"{field}.command"),
            repeat=repeat,
        )
        required_field = {
            "goto": step.path,
            "click": step.selector,
            "fill": step.selector and step.value,
            "press": step.key,
            "expect": step.selector and step.state,
            "exec": step.command,
        }[action]
        if not required_field:
            raise RunnabilityContractError(f"{field} is incomplete for action {action}")
        steps.append(step)
    return steps


def _parse_observations(value: Any) -> list[Observation]:
    rows = _list(value, "primary_journey.observations")
    observations: list[Observation] = []
    seen: set[str] = set()
    for index, value in enumerate(rows):
        field = f"primary_journey.observations[{index}]"
        raw = _mapping(value, field)
        _reject_unknown(raw, _OBSERVATION_FIELDS, field)
        observation_id = _string(raw.get("id"), f"{field}.id")
        if observation_id in seen:
            raise RunnabilityContractError(
                f"duplicate observation id: {observation_id}"
            )
        seen.add(observation_id)
        kind = _string(raw.get("kind"), f"{field}.kind")
        if kind not in SUPPORTED_OBSERVATION_KINDS:
            raise RunnabilityContractError(f"unsupported observation kind: {kind}")
        observation = Observation(
            id=observation_id,
            kind=kind,
            expectation=_string(raw.get("expectation"), f"{field}.expectation"),
            selector=_optional_string(raw.get("selector"), f"{field}.selector"),
            statement=_optional_string(raw.get("statement"), f"{field}.statement"),
            parameters=tuple(_string_list(raw.get("parameters", []), f"{field}.parameters")),
            url=_optional_string(raw.get("url"), f"{field}.url"),
            method=_optional_string(raw.get("method"), f"{field}.method"),
            command=_optional_string(raw.get("command"), f"{field}.command"),
        )
        if kind == "browser_dom" and observation.selector is None:
            raise RunnabilityContractError(f"{field}.selector is required")
        if kind == "postgres_query":
            if observation.statement is None or "$1" not in observation.statement:
                raise RunnabilityContractError(
                    f"{field}.statement must contain positional parameter $1"
                )
            if not observation.parameters:
                raise RunnabilityContractError(f"{field}.parameters must not be empty")
        if kind == "http" and observation.url is None:
            raise RunnabilityContractError(f"{field}.url is required")
        if kind == "exec" and observation.command is None:
            raise RunnabilityContractError(f"{field}.command is required")
        observations.append(observation)
    return observations


def _parse_persistence(
    value: Any,
    *,
    observation_ids: set[str],
) -> PersistenceProbe | None:
    if value is None:
        return None
    raw = _mapping(value, "persistence_probe")
    _reject_unknown(raw, _PERSISTENCE_FIELDS, "persistence_probe")
    selected = _unique_strings(
        raw.get("observations"), "persistence_probe.observations"
    )
    if not selected:
        raise RunnabilityContractError("persistence_probe.observations must not be empty")
    missing = [item for item in selected if item not in observation_ids]
    if missing:
        raise RunnabilityContractError(
            f"persistence observation is not defined: {missing[0]}"
        )
    restart = _commands(
        raw.get("restart_commands"), "persistence_probe.restart_commands"
    )
    if not restart:
        raise RunnabilityContractError(
            "persistence_probe.restart_commands must not be empty"
        )
    return PersistenceProbe(
        restart_commands=restart,
        observation_ids=tuple(selected),
    )


def _parse_local_journey(value: Any) -> LocalUserJourney | None:
    if value is None:
        return None
    raw = _mapping(value, "local_journey")
    _reject_unknown(raw, _LOCAL_JOURNEY_FIELDS, "local_journey")

    prerequisites = tuple(
        _non_empty_string_list(
            raw.get("prerequisites", []),
            "local_journey.prerequisites",
        )
    )
    open_urls = tuple(
        _non_empty_string_list(
            raw.get("open_urls", []),
            "local_journey.open_urls",
        )
    )
    commands: dict[str, tuple[str, ...]] = {}
    for field in (
        "provision_commands",
        "readiness_commands",
        "prepare_commands",
        "verify_commands",
        "start_commands",
        "stop_commands",
        "cleanup_commands",
    ):
        parsed = _commands(raw.get(field, []), f"local_journey.{field}")
        if not parsed:
            raise RunnabilityContractError(
                f"local_journey.{field} must not be empty"
            )
        commands[field] = parsed
    return LocalUserJourney(
        prerequisites=prerequisites,
        provision_commands=commands["provision_commands"],
        readiness_commands=commands["readiness_commands"],
        prepare_commands=commands["prepare_commands"],
        verify_commands=commands["verify_commands"],
        start_commands=commands["start_commands"],
        open_urls=open_urls,
        stop_commands=commands["stop_commands"],
        cleanup_commands=commands["cleanup_commands"],
    )


def _validate_variables(value: Any) -> None:
    for text in _all_strings(value):
        if "${" in text and not _VARIABLE_PATTERN.search(text):
            raise RunnabilityContractError(f"malformed variable expression: {text}")
        for variable in _VARIABLE_PATTERN.findall(text):
            if variable not in ALLOWED_VARIABLES:
                raise RunnabilityContractError(f"unsupported variable: {variable}")


def _all_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _all_strings(key)
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunnabilityContractError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RunnabilityContractError(f"{field} keys must be strings")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise RunnabilityContractError(f"{field} must be a list")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnabilityContractError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _string_list(value: Any, field: str) -> list[str]:
    return [_string(item, f"{field}[{index}]") for index, item in enumerate(_list(value, field))]


def _non_empty_string_list(value: Any, field: str) -> list[str]:
    items = _string_list(value, field)
    if not items:
        raise RunnabilityContractError(f"{field} must not be empty")
    return items


def _unique_strings(value: Any, field: str) -> list[str]:
    items = _string_list(value, field)
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise RunnabilityContractError(f"duplicate {field} value: {item}")
        seen.add(item)
    return items


def _command(value: Any, field: str) -> str:
    command = _string(value, field)
    if "\n" in command or "\x00" in command:
        raise RunnabilityContractError(f"{field} contains forbidden control characters")
    return command


def _commands(value: Any, field: str) -> tuple[str, ...]:
    return tuple(
        _command(item, f"{field}[{index}]")
        for index, item in enumerate(_list(value, field))
    )


def _reject_unknown(raw: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = [str(key) for key in raw if key not in allowed]
    if not unknown:
        return
    label = "key" if len(unknown) == 1 else "keys"
    raise RunnabilityContractError(
        f"unknown {field} {label}: {', '.join(unknown)}; "
        f"allowed {field} keys: {', '.join(sorted(allowed))}"
    )
