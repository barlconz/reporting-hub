# Push reporting-hub to GitHub (arlitwoa) using shared credential resolution.
#
# Usage:
#   .\scripts\push_to_github.ps1
#   .\scripts\push_to_github.ps1 -CommitMessage "Update quarter dashboard"
#   .\scripts\push_to_github.ps1 -Branch feature/my-branch -NoCommit

param(
    [string]$CommitMessage = "Initial reporting-hub slice from artifact-consumer-twoa",
    [string]$Remote = "https://github.com/arlitwoa/reporting-hub.git",
    [string]$Branch = "main",
    [switch]$NoCommit
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$localResolver = Join-Path $PSScriptRoot "lib\Resolve-GitHubPat.ps1"
$sharedResolver = Join-Path $(if ($env:DEV_SCRIPTS_DIR) { $env:DEV_SCRIPTS_DIR } else { "C:\development\scripts" }) "Resolve-GitHubPat.ps1"
if (Test-Path $localResolver) {
    . $localResolver
} elseif (Test-Path $sharedResolver) {
    . $sharedResolver
} else {
    throw "Resolve-GitHubPat.ps1 not found. Expected $localResolver or $sharedResolver"
}

Set-Location $Root

$params = @{
    Account = "arlitwoa"
    Remote  = $Remote
    Branch  = $Branch
    RepoRoot = $Root
}
if ($NoCommit) {
    $params.NoCommit = $true
} else {
    $params.CommitMessage = $CommitMessage
}

Invoke-GitHubPush @params
