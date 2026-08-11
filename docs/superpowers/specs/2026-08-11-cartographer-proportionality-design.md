# Cartographer Proportionality Design

## Problem

The retained minimal Hello World run produced a 245-line specification with 42
formal requirements. The document was rigorous, but repeated the same small
observable contract as functional requirements, acceptance criteria,
verification requirements, non-functional requirements, and success criteria.
The resulting plan and task set inherited that duplication.

## Decision

CARTOGRAPHER will classify feature complexity from discovered behavior before
authoring. The classification guides document depth, not a requirement-count or
line-count quota.

For a small deterministic feature, CARTOGRAPHER will:

- represent each distinct observable product obligation once as an FR or NFR;
- use acceptance criteria as verification paths for those obligations rather
  than restating each obligation as another requirement;
- include only evidence-backed NFR categories, entities, scenarios, and scope
  distinctions;
- combine behaviors only when they form one independently verifiable contract;
- preserve explicit failure, boundary, and negative behavior when material;
- retain unresolved assumptions and questions instead of manufacturing detail.

Larger or uncertain features keep the existing rich structure where the domain
evidence warrants it. Complexity never relaxes atomicity, testability,
technology neutrality, evidence grounding, or controller-owned validation.

## Template Contract

The canonical specification template remains structurally recognizable to
downstream consumers, but its examples stop implying mandatory multiplicity.
Optional sections and rows are marked as conditional. The template explicitly
links acceptance criteria to the formal requirements they verify and warns
against duplicating the same contract across sections.

## Verification

Focused prompt/template contract tests will prove that:

- complexity is classified before scenario and requirement authoring;
- proportionality is defined without numeric document-volume targets;
- acceptance criteria verify requirements instead of duplicating them;
- NFR categories and optional sections are included only when evidenced;
- negative behavior, uncertainty, atomicity, and testability remain mandatory.

The retained Hello World artifacts remain the production benchmark. A later
live spec run should produce a materially smaller specification while retaining
the exact output, exit-status, standard-error, and no-input contract.
