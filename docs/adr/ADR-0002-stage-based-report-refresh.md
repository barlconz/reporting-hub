# ADR-0002: Stage-based report refresh orchestration

Status: Accepted
Date: 2026-08-25

## Context

A single linear publish command makes failures high-blast-radius and slows reruns when only one report family needs regeneration.

## Decision

Adopt stage-based orchestration in `scripts/refresh_github_pages_reports.sh` with explicit stages:

1. `quarterly`
2. `sef`
3. `delivery-health`
4. `site-index`

Support stage selection and diagnostics via:

1. `--stage <name>` (repeatable)
2. `--list-stages`
3. Stage summary output with pass/fail status

CI runs these stages as separate workflow steps for clearer failure isolation.

## Consequences

Positive:

1. Faster targeted reruns.
2. Better workflow observability.
3. Cleaner ownership by report stream.

Trade-offs:

1. Slightly more scripting complexity.
2. More workflow step definitions to maintain.
