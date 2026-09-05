# reporting-hub

TWoA **reporting hub** for GitHub Pages: programme-scoped delivery snapshots (EPC, SEF, enterprise) refreshed from Jira.

Runs on **`barlconz-artifact-core`** (Artifact core wheel from [barlconz/artifact](https://github.com/barlconz/artifact) GitHub Releases) with the TWoA programme extension from this repo. Published HTML lives under `docs/` on **TWoA GitHub** (`arlitwoa`).

## Live site

After Pages is enabled: **https://arlitwoa.github.io/reporting-hub/**

| Area | Path | Reports |
|------|------|---------|
| Site hub | `/` | Links to programme areas below |
| EPC delivery | `/epc/` | Quarter dashboard, milestone scope, Sprint Health, Dev Done risk |
| SEF | `/sef/` | Integrated project plan Gantt |
| Enterprise reporting | `/enterprise/` | Placeholder for cross-programme reports |

Report URLs are unchanged for stability (e.g. `/quarter/`, `/sprint-health/`, `/sef/project-plan.html`). Programme hubs group navigation only.

## Dependency version policy

This repo intentionally pins Artifact core to one tested release version (`0.2.1`) across runtime metadata, local setup guidance, and CI.

When upgrading Artifact core, update all of the following in one change:

1. `pyproject.toml` dependency for `barlconz-artifact-core`
2. `README.md` wheel download/install examples
3. `.github/workflows/github-pages-reports.yml` wheel download/install step

## Setup (local refresh)

**Option A — editable core (development):**

```powershell
pip install -e C:\development\artifact
pip install -e C:\development\reporting-hub
```

**Option B — pinned wheel (matches CI):**

```powershell
$env:GH_TOKEN = "<PAT with repo read on barlconz/artifact>"
gh release download v0.2.1 --repo barlconz/artifact --pattern "barlconz_artifact_core-0.2.1-py3-none-any.whl" --dir $env:TEMP
pip install "$env:TEMP\barlconz_artifact_core-0.2.1-py3-none-any.whl"
pip install -e C:\development\reporting-hub
```

Environment (PowerShell):

```powershell
$env:PYTHONPATH = "C:\development\reporting-hub"
$env:ARTIFACT_PROFILES_DIR = "C:\development\reporting-hub\config\profiles"
$env:ARTIFACT_PROGRAMME_REGISTRY = "C:\development\reporting-hub\config\programme-registry.json"
$env:ARTIFACT_ROLE_REGISTRY = "C:\development\reporting-hub\config\role-registry.json"
$env:ARTIFACT_LOCAL_CREDENTIALS = "C:\development\artifact\config\credentials.local.json"
```

Copy profile templates before first run:

```powershell
Copy-Item config\profiles\atlassian.template.json config\profiles\atlassian.json
Copy-Item config\profiles\twoa-programme.template.json config\profiles\twoa-programme.json
```

Refresh all GitHub Pages snapshots:

```powershell
# Git Bash
bash scripts/refresh_github_pages_reports.sh

# Or run the Python steps from that script in PowerShell (see consumer docs/execution-notes.md)
```

Run selected stages only (for faster reruns and narrower troubleshooting):

```powershell
# Stage list: quarterly, sef, delivery-health, site-index
bash scripts/refresh_github_pages_reports.sh --list-stages

# Example: refresh only SEF and the site index
bash scripts/refresh_github_pages_reports.sh --stage sef --stage site-index

# Validate prerequisites only (no report generation)
bash scripts/refresh_github_pages_reports.sh --preflight-only

# Skip preflight if you are intentionally debugging a partial environment
bash scripts/refresh_github_pages_reports.sh --skip-preflight --stage site-index
```

Preflight checks enforce prerequisites before stage execution:

1. Python command is available (`PYTHON` override supported).
2. Site config exists: `config/github-pages-site.json`.
3. For Jira-backed stages (`quarterly`, `sef`, `delivery-health`):
  - `ARTIFACT_PROGRAMME_REGISTRY` (or default `config/programme-registry.json`)
  - `ARTIFACT_ROLE_REGISTRY` (or default `config/role-registry.json`)
  - `ARTIFACT_PROFILES_DIR` containing `atlassian.json` and `twoa-programme.json`
  - `ARTIFACT_LOCAL_CREDENTIALS` file path is set and exists

Commit changed files under `docs/` when snapshots update.

## Credential management (local)

GitHub identities are split by account. Do not rely on one global `gh` login for all repos.

| Concern | Location |
|---------|----------|
| GitHub PATs (multi-account) | `C:\development\config\credentials.local.json` |
| GitHub PAT template | `C:\development\config\credentials.local.template.json` |
| Shared resolver / push helpers | `scripts/lib/Resolve-GitHubPat.ps1` (or `C:\development\scripts\` override) |
| Atlassian / Jira | `C:\development\artifact\artifact-core\config\credentials.local.json` via `ARTIFACT_LOCAL_CREDENTIALS` |

Central GitHub file shape:

```json
{
  "github": {
    "barlconz": { "pat": "..." },
    "arlitwoa": { "pat": "..." }
  }
}
```

Resolution order for pushes: account env var → central credentials file → repo-local legacy fallback.

Optional overrides: `DEV_ROOT`, `DEV_SCRIPTS_DIR`, `DEV_CREDENTIALS_PATH`.

## Push to GitHub (TWoA / arlitwoa)

Local `gh` may be logged in as a personal account (`barlconz`). Use a **TWoA org PAT** for programmatic push to this repo.

### 1. Create a fine-grained PAT

On the TWoA GitHub account that can access `arlitwoa/reporting-hub`:

1. [Fine-grained tokens](https://github.com/settings/tokens?type=beta) → **Generate new token**
2. **Resource owner:** `arlitwoa` (or your TWoA user if the org delegates)
3. **Repository access:** Only `reporting-hub`
4. **Permissions:** Contents → **Read and write**
5. Copy the token once (it is not shown again)

### 2. Push from this machine

```powershell
cd C:\development\clients\twoa\reporting-hub

# One-time: save PAT to central credentials + TWOA_GITHUB_PAT
powershell -ExecutionPolicy Bypass -File .\scripts\setup_twoa_github_pat.ps1
# Restart Cursor after this

powershell -ExecutionPolicy Bypass -File .\scripts\push_to_github.ps1
```

The script commits staged files if needed, pushes with `-c credential.helper=''`, and does **not** store the token in `.git/config`.

**Feature branches:**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\push_to_github.ps1 `
  -Branch feature/my-branch `
  -NoCommit
```

Open PRs against **`main`** in the GitHub UI if `gh pr create` fails with the TWoA PAT.

### 3. GitHub Actions secrets (on arlitwoa/reporting-hub)

| Secret | Purpose |
|--------|---------|
| `ARTIFACT_CREDENTIALS_JSON` | Atlassian credentials for Jira refresh |
| `ARTIFACT_CORE_PAT` | Read **repo** on `barlconz/artifact` (download release wheel) |
| `ARTIFACT_USER_EMAIL` | Optional attribution |

CI installs the **v0.2.1 release wheel** from `barlconz/artifact` — no git checkout.

## GitHub Actions

Workflow: `.github/workflows/github-pages-reports.yml` — hourly (UTC) or manual dispatch.

**Repository secrets**

| Secret | Purpose |
|--------|---------|
| `ARTIFACT_CREDENTIALS_JSON` | Full contents of `credentials.local.json` (Atlassian) |
| `ARTIFACT_CORE_PAT` | PAT with **repo read** on `barlconz/artifact` (download release wheel) |
| `ARTIFACT_USER_EMAIL` | Optional attribution for generated content |

Push from the workflow uses the built-in **`GITHUB_TOKEN`** on `arlitwoa/reporting-hub`.

**GitHub Pages:** Settings → Pages → deploy from branch **`main`** → folder **`/docs`**.

## Config

| File | Role |
|------|------|
| `config/github-pages-site.json` | Site hub structure — programmes (EPC, SEF, enterprise) and report links |
| `config/quarterly-reporting.json` | Three-lane quarter model, burn tracking, milestone scope |
| `config/delivery-health.json` | Sprint Health + Dev Done risk |
| `config/sef-project-plan-reporting.json` | SEF Block Gantt hub keys, chart window, artifact names |
| `config/sef-project-plan-blocks.json` | PDE issue keys for Phase 1 and Phase 2 Block hierarchy |
| `config/jira-binding.json` | D-Train status → phase map |
| `config/programme-registry.json` | Wires `extensions.twoa_programme` into Artifact core |

Update `githubPages.githubUser` / `repoName` in both reporting configs if the repo is renamed or moved.

## Generated artifact contract

The repository intentionally mixes source code/config and generated report artifacts. Use this contract to decide what to commit.

### Source-of-truth inputs (always review as code)

1. `extensions/` and `scripts/` Python/bash/PowerShell logic
2. `config/*.json` report and navigation configuration
3. `.github/workflows/github-pages-reports.yml`
4. `README.md` and related docs guidance

### Generated publish outputs (commit when report refresh runs)

1. `docs/index.html`
2. `docs/epc/**`
3. `docs/quarter/index.html`
4. `docs/quarter/milestone.html`
5. `docs/sprint-health/**`
6. `docs/dev-done-risk/**`
7. `docs/sef/**`
8. `docs/enterprise/**`

These are the artifacts GitHub Pages serves from `main`.

### Operational snapshot artifacts (optional by workflow)

1. `reports/github-billing/**`

Commit these when you intentionally capture/trace a billing data snapshot for governance reporting. Keep them out of unrelated feature commits.

### Commit hygiene rules

1. Prefer separate commits for source changes and generated outputs.
2. If only generated timestamps/content changed, use a `chore(site): refresh ...` style commit.
3. If source logic changed, include the regenerated `docs/**` artifacts in the same PR so reviewers can verify output impact.
4. Avoid mixing `reports/github-billing/**` snapshots into unrelated report or script refactors.

## Sync from consumer

When reporting code changes in `artifact-consumer-twoa`, re-export:

```powershell
C:\development\artifact-consumer-twoa\scripts\export_reporting_hub.ps1
```

Then patch `githubUser` / `repoName` in `config/quarterly-reporting.json` and `config/delivery-health.json` if the export script overwrote them.

## Tests

```powershell
$env:ARTIFACT_PROGRAMME_REGISTRY = "C:\development\reporting-hub\config\programme-registry.json"
python -m unittest discover -s tests -v
```

## Architecture decisions and operations

1. ADRs:
  - `docs/adr/ADR-0001-artifact-core-version-policy.md`
  - `docs/adr/ADR-0002-stage-based-report-refresh.md`
  - `docs/adr/ADR-0003-generated-artifact-commit-contract.md`
2. Publish incident runbook:
  - `docs/operations/publish-incident-runbook.md`
