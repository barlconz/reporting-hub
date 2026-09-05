# ADR-0003: Generated artifact commit contract

Status: Accepted
Date: 2026-08-25

## Context

This repository stores both source logic/config and generated report pages. Without explicit boundaries, commits can mix concerns and make review harder.

## Decision

Define and document a commit contract:

1. Source-of-truth inputs are code/config/workflows/docs.
2. `docs/**` report outputs are generated publish artifacts and must be committed when refreshed.
3. `reports/github-billing/**` snapshots are operational artifacts and should be committed only when intentionally captured.
4. Prefer separate commits for source edits vs generated-output refreshes.

## Consequences

Positive:

1. More predictable PR scope.
2. Easier review of behavioral vs generated changes.

Trade-offs:

1. More frequent multi-commit PRs.
2. Requires discipline during local refresh workflows.
