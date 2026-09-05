# Save a GitHub PAT for arlitwoa (TWoA reporting-hub pushes).
# Writes to the central credentials file and sets TWOA_GITHUB_PAT for the user profile.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_twoa_github_pat.ps1
#
# Restart Cursor (or open a new terminal) so agent shells inherit TWOA_GITHUB_PAT.

$ErrorActionPreference = "Stop"

$localResolver = Join-Path $PSScriptRoot "lib\Resolve-GitHubPat.ps1"
$sharedResolver = Join-Path $(if ($env:DEV_SCRIPTS_DIR) { $env:DEV_SCRIPTS_DIR } else { "C:\development\scripts" }) "Resolve-GitHubPat.ps1"
if (Test-Path $localResolver) {
    . $localResolver
} elseif (Test-Path $sharedResolver) {
    . $sharedResolver
} else {
    throw "Resolve-GitHubPat.ps1 not found. Expected $localResolver or $sharedResolver"
}

Write-Host "TWoA GitHub PAT setup for arlitwoa/reporting-hub"
Write-Host ""
Write-Host "Token will be saved to:"
Write-Host "  $(Get-DevCredentialsPath) -> github.arlitwoa.pat"
Write-Host "  TWOA_GITHUB_PAT (Windows user environment variable)"
Write-Host ""
Write-Host "Create a fine-grained token with:"
Write-Host "  - Repository: arlitwoa/reporting-hub"
Write-Host "  - Contents: Read and write"
Write-Host "  - Workflows: Read and write (only if pushing workflow files)"
Write-Host ""

$secure = Read-Host "Paste TWoA PAT (input hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($token)) {
    throw "No token entered."
}

Set-GitHubPat -Account arlitwoa -Token $token
[Environment]::SetEnvironmentVariable("TWOA_GITHUB_PAT", $token, [EnvironmentVariableTarget]::User)
$env:TWOA_GITHUB_PAT = $token

Write-Host ""
Write-Host "Saved arlitwoa PAT to the central credentials file and TWOA_GITHUB_PAT."
Write-Host "Restart Cursor so agent terminals pick up the environment variable."
Write-Host ""
Write-Host "Then push from reporting-hub:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\push_to_github.ps1"
