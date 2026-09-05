# Publish Incident Runbook

## Scope

Use this runbook when `github-pages-reports.yml` or local refresh runs fail.

## Fast triage

1. Identify failed stage (`quarterly`, `sef`, `delivery-health`, `site-index`) from workflow step name or stage summary logs.
2. Confirm prerequisites:
   - Python is available
   - Profiles exist: `config/profiles/atlassian.json`, `config/profiles/twoa-programme.json`
   - Registry paths exist
   - Credentials file exists and is readable
3. Re-run only the failed stage locally.

## Local rerun commands

1. List stages:

```bash
bash scripts/refresh_github_pages_reports.sh --list-stages
```

2. Preflight only:

```bash
bash scripts/refresh_github_pages_reports.sh --preflight-only --stage <stage>
```

3. Rerun failed stage:

```bash
bash scripts/refresh_github_pages_reports.sh --stage <stage>
```

4. Rebuild index after a stage fix:

```bash
bash scripts/refresh_github_pages_reports.sh --stage site-index
```

## Failure patterns and responses

1. Preflight failures:
   - Fix missing files/env vars first.
   - Do not bypass with `--skip-preflight` unless debugging.

2. Jira/API failures:
   - Validate `ARTIFACT_LOCAL_CREDENTIALS` path and token health.
   - Confirm profile JSON files are present and correctly configured.

3. Data-specific script failures:
   - Run failing Python script directly to isolate stack trace.
   - Fix config/schema mismatches under `config/`.

4. Push/publish failures in CI:
   - Inspect rebase/push step logs.
   - Re-run workflow after main is stable.

## Rollback guidance

1. If generated `docs/**` output is broken after merge, revert the publish commit on `main`.
2. Open follow-up fix PR with root-cause notes.
3. Keep rollback and fix PRs separate for traceability.

## Communication checklist

1. Record incident window and failing stage.
2. Record root cause and corrected files.
3. Link the fixing commit/PR.
4. Note whether preflight or tests should be expanded.
