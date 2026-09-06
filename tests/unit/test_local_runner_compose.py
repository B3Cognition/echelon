"""Fail-closed Compose-plan policy tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.local_runner_compose import (
    LocalComposePolicyError,
    parse_canonical_compose_plan,
)


def _write_compose(tmp_path: Path, content: str) -> None:
    (tmp_path / "docker-compose.yml").write_text(content, encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("compose", "message"),
    [
        ("services: {postgres: {image: postgres:17, privileged: true}}", "privileged"),
        (
            "services: {postgres: {image: postgres:17, ports: ['127.0.0.1:5432:5432']}}",
            "candidate-authored published port",
        ),
        (
            "services: {postgres: {image: postgres:17, volumes: ['/tmp/host:/data']}}",
            "absolute bind mount",
        ),
        (
            "volumes: {data: {driver_opts: {type: none}}}\nservices: {postgres: {image: postgres:17, volumes: [data:/data]}}",
            "driver_opts",
        ),
    ],
)
def test_compose_plan_rejects_unsafe_host_topology(
    tmp_path: Path, compose: str, message: str
) -> None:
    _write_compose(tmp_path, compose)

    with pytest.raises(LocalComposePolicyError, match=message):
        parse_canonical_compose_plan(tmp_path, "docker-compose.yml", {"postgres"})


@pytest.mark.unit
def test_compose_plan_accepts_only_selected_internal_postgres(tmp_path: Path) -> None:
    _write_compose(
        tmp_path,
        "services:\n  postgres:\n    image: postgres:17-alpine\n",
    )

    plan = parse_canonical_compose_plan(tmp_path, "docker-compose.yml", {"postgres"})

    assert [service.name for service in plan.services] == ["postgres"]
    assert plan.services[0].image == "postgres:17-alpine"
