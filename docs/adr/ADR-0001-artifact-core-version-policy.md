# ADR-0001: Pin Artifact core version across runtime and CI

Status: Accepted
Date: 2026-08-25

## Context

This repository depends on `barlconz-artifact-core` and runs report refresh in both local and CI contexts. Drift between dependency metadata and CI install behavior causes difficult-to-debug inconsistencies.

## Decision

Use a pinned Artifact core version (`0.2.1`) consistently across:

1. `pyproject.toml` runtime dependency declaration
2. `README.md` local setup instructions
3. `.github/workflows/github-pages-reports.yml` install step

## Consequences

Positive:

1. Local and CI behavior are deterministic.
2. Incident triage is simpler because execution environments are aligned.

Trade-offs:

1. Version upgrades are explicit maintenance work.
2. Upgrade PRs must touch multiple files in one change.

## Upgrade rule

When bumping Artifact core, update all three files above in a single PR and run full tests before merge.
