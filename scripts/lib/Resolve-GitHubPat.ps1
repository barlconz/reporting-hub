# Shared GitHub PAT resolution for multi-account local development.
# Dot-source from repo push scripts:
#   . (Join-Path $PSScriptRoot 'lib\Resolve-GitHubPat.ps1')
#   $token = Resolve-GitHubPat -Account arlitwoa -RepoRoot $Root

$script:DefaultDevRoot = 'C:\development'
$script:KnownGitHubAccounts = @('barlconz', 'arlitwoa')

function Get-DevRootPath {
    if (-not [string]::IsNullOrWhiteSpace($env:DEV_ROOT)) {
        return $env:DEV_ROOT
    }
    return $script:DefaultDevRoot
}

function Get-DevScriptsPath {
    if (-not [string]::IsNullOrWhiteSpace($env:DEV_SCRIPTS_DIR)) {
        return $env:DEV_SCRIPTS_DIR
    }
    return Join-Path (Get-DevRootPath) 'scripts'
}

function Get-DevCredentialsPath {
    if (-not [string]::IsNullOrWhiteSpace($env:DEV_CREDENTIALS_PATH)) {
        return $env:DEV_CREDENTIALS_PATH
    }
    return Join-Path (Get-DevRootPath) 'config\credentials.local.json'
}

function Get-EnvironmentVariableValue {
    param([Parameter(Mandatory)][string]$Name)

    $processValue = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }

    $userValue = [Environment]::GetEnvironmentVariable($Name, 'User')
    if (-not [string]::IsNullOrWhiteSpace($userValue)) {
        return $userValue
    }

    return $null
}

function Get-GitHubPatEnvironmentVariables {
    param([Parameter(Mandatory)][string]$Account)

    switch ($Account) {
        'arlitwoa' { return @('TWOA_GITHUB_PAT', 'GITHUB_PAT_ARLITWOA') }
        'barlconz' { return @('BARLCONZ_GITHUB_PAT', 'GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_PAT_BARLCONZ') }
        default { return @("GITHUB_PAT_$($Account.ToUpper())") }
    }
}

function Get-GitHubPatFromObject {
    param(
        [Parameter(Mandatory)]$Credentials,
        [Parameter(Mandatory)][string]$Account
    )

    if (-not $Credentials.github) {
        return $null
    }

    $accountEntry = $Credentials.github.$Account
    if ($accountEntry -and -not [string]::IsNullOrWhiteSpace($accountEntry.pat)) {
        return $accountEntry.pat
    }

    if ($Account -eq 'arlitwoa' -and -not [string]::IsNullOrWhiteSpace($Credentials.github.pat)) {
        return $Credentials.github.pat
    }

    return $null
}

function Resolve-GitHubPat {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('barlconz', 'arlitwoa')]
        [string]$Account,
        [string]$RepoRoot
    )

    foreach ($envVar in (Get-GitHubPatEnvironmentVariables -Account $Account)) {
        $token = Get-EnvironmentVariableValue -Name $envVar
        if (-not [string]::IsNullOrWhiteSpace($token)) {
            return $token
        }
    }

    $centralPath = Get-DevCredentialsPath
    if (Test-Path $centralPath) {
        $token = Get-GitHubPatFromObject -Credentials (Get-Content $centralPath -Raw | ConvertFrom-Json) -Account $Account
        if (-not [string]::IsNullOrWhiteSpace($token)) {
            return $token
        }
    }

    if ($RepoRoot) {
        $repoLocalPath = Join-Path $RepoRoot 'config\credentials.local.json'
        if (Test-Path $repoLocalPath) {
            $token = Get-GitHubPatFromObject -Credentials (Get-Content $repoLocalPath -Raw | ConvertFrom-Json) -Account $Account
            if (-not [string]::IsNullOrWhiteSpace($token)) {
                return $token
            }
        }
    }

    throw @"
No GitHub PAT found for account '$Account'.

Resolution order:
  1. Account env vars: $((Get-GitHubPatEnvironmentVariables -Account $Account) -join ', ')
  2. $(Get-DevCredentialsPath) -> github.$Account.pat
  3. <repo>\config\credentials.local.json (legacy fallback)

Create a fine-grained PAT for the target repository, then either:
  - Save it with scripts\setup_twoa_github_pat.ps1 (arlitwoa), or
  - Add github.$Account.pat to $(Get-DevCredentialsPath)
"@
}

function Set-GitHubPat {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('barlconz', 'arlitwoa')]
        [string]$Account,
        [Parameter(Mandatory)][string]$Token
    )

    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw 'Token must not be empty.'
    }

    $path = Get-DevCredentialsPath
    $directory = Split-Path $path -Parent
    if (-not (Test-Path $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    if (Test-Path $path) {
        $credentials = Get-Content $path -Raw | ConvertFrom-Json
    } else {
        $templatePath = Join-Path $directory 'credentials.local.template.json'
        if (Test-Path $templatePath) {
            $credentials = Get-Content $templatePath -Raw | ConvertFrom-Json
        } else {
            $credentials = [PSCustomObject]@{
                github = [PSCustomObject]@{}
            }
        }
    }

    if (-not $credentials.github) {
        $credentials | Add-Member -NotePropertyName github -NotePropertyValue ([PSCustomObject]@{}) -Force
    }

    $accountEntry = $credentials.github.$Account
    if (-not $accountEntry) {
        $accountEntry = [PSCustomObject]@{}
        $credentials.github | Add-Member -NotePropertyName $Account -NotePropertyValue $accountEntry -Force
    }

    $accountEntry | Add-Member -NotePropertyName pat -NotePropertyValue $Token -Force
    ($credentials | ConvertTo-Json -Depth 10) | Set-Content -Path $path -Encoding UTF8
}

function New-AuthGitRemote {
    param(
        [Parameter(Mandatory)][string]$Remote,
        [Parameter(Mandatory)][string]$Token
    )

    return $Remote -replace '^https://', "https://x-access-token:${Token}@"
}

function Invoke-GitHubPush {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('barlconz', 'arlitwoa')]
        [string]$Account,
        [Parameter(Mandatory)][string]$Remote,
        [string]$Branch = 'main',
        [string]$CommitMessage,
        [switch]$NoCommit,
        [string]$RepoRoot
    )

    $ErrorActionPreference = 'Stop'
    $workingRoot = if ($RepoRoot) { $RepoRoot } else { (Get-Location).Path }
    Set-Location $workingRoot

    $token = Resolve-GitHubPat -Account $Account -RepoRoot $workingRoot
    $authRemote = New-AuthGitRemote -Remote $Remote -Token $token

    if (-not (git remote get-url origin 2>$null)) {
        git remote add origin $Remote
    } else {
        git remote set-url origin $Remote
    }

    if (-not $NoCommit) {
        if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
            throw 'CommitMessage is required unless -NoCommit is specified.'
        }

        $status = git status --porcelain
        if ($status) {
            git add -A
            git commit -m $CommitMessage
        } elseif (-not (git rev-parse HEAD 2>$null)) {
            throw 'No commits and nothing staged.'
        }
    }

    Write-Host "Pushing HEAD to $Remote ($Branch) as $Account ..."
    git -c credential.helper='' push $authRemote "HEAD:${Branch}"
    git remote set-url origin $Remote
    git fetch origin $Branch 2>$null
    git branch --set-upstream-to=origin/$Branch $Branch 2>$null
    Write-Host 'Done.'
}
