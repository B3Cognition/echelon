# Stats Perform MSA Service Stack

Use the CAIC MSA service template and MSA core conventions for service and API-service targets.

Operational guidance:

- Use the MSA service template for new service structure.
- Follow MSA core conventions for FastAPI layout, pydantic-settings configuration, health checks, observability, Docker, CI, and release behavior.
- Use `uv` for Python environment and dependency operations.
- Use pytest for backend tests, ruff for linting, and mypy for type checking.

Boundaries:

- This stack does not imply Stark, Playbook, Postgres, Kafka, Flink, or any other infrastructure stack.
- Select persistence, messaging, and stream-processing stacks separately when requirements call for them.
