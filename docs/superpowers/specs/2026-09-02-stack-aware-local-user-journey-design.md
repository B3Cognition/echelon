# Stack-Aware Local User Journey Design

## Goal

Make Echelon delivery distinguish a sandbox-verified application from a
complete, documented local user journey. A project using persistence must not
claim a runnable README unless the service provisioning path is explicit.

## Existing contract extension

Each delivered target may already contain `.echelon/runnability.yml`. Echelon
extends that schema with one optional, typed `local_journey` section rather
than introducing a second contract or lifecycle subsystem. The section carries
the concrete prerequisite, provision, readiness, prepare, verify, start, open,
stop, and cleanup instructions needed by a local user. The candidate owns those
project-specific values; Echelon owns validation, evidence, reporting, and
disposition.

## Stack capability

Stacks use the existing runnability capability mechanism to declare
`local_journey`. The PostgreSQL persistence stack requires that capability but
does not prescribe Docker Compose, credentials, database names, or project
commands. The generic validator requires a complete lifecycle; projects remain
free to use Compose or another provisioner. Other persistence stacks can opt in
without changing the core schema.

## Execution and truthfulness

The existing Linux sandbox remains authoritative for sandbox verification.
This change does not execute project commands on the host. Echelon records the
declared local journey separately as `unverified`, including the exact commands,
URLs, prerequisites, and reason; it must not imply that the README journey
passed. A future compatible runner can add execution evidence without changing
the contract.

## Documentation gate

For stacks requiring local services, the existing documentation verifier reads
the validated local journey from runnability evidence and requires README
instructions to include every exact declared command and URL. It rejects vague
placeholders and requires truthful wording when the local journey is unverified.

## Verification

Tests cover schema validation, PostgreSQL stack requirements, rejected
incomplete local journeys, truthful unverified reporting, README/contract
command consistency, and backward compatibility for existing contracts. This
change modifies Echelon only; a later delivery run is responsible for repairing
the demo from the new generic guardrail.
