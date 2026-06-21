# Tessera - GitHub repo setup script
# Run from project root:  .\scripts\setup_github.ps1

$ErrorActionPreference = "Stop"

$GhExe = "C:\Program Files\GitHub CLI\gh.exe"
$RepoName = "art_ai_mosaic_r1"
$RepoDescription = "Tessera: multi-megapixel mosaic engine (xAI + RTX 4080)"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RepoUrl = "https://github.com/jaws1111/" + $RepoName

# Ensure GitHub CLI is on PATH for this session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Test-Path $GhExe)) {
    Write-Host "GitHub CLI not found. Installing via winget..." -ForegroundColor Yellow
    winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
    if (-not (Test-Path $GhExe)) {
        throw "GitHub CLI installation failed. Install manually: winget install GitHub.cli"
    }
}

Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot" -ForegroundColor Cyan

# --- Step 1: Authenticate ---
Write-Host ""
Write-Host "[1/3] Checking GitHub authentication..." -ForegroundColor Cyan
$authCheck = & $GhExe auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Opening browser for GitHub login..." -ForegroundColor Yellow
    Write-Host "Complete the login in your browser, then return here." -ForegroundColor Yellow
    Write-Host ""
    & $GhExe auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub login failed or was cancelled."
    }
} else {
    Write-Host "Already authenticated." -ForegroundColor Green
    Write-Host $authCheck
}

# --- Step 2: Create remote repo (skip if origin already set) ---
Write-Host ""
Write-Host "[2/3] Setting up remote repository..." -ForegroundColor Cyan
$existingRemote = git remote get-url origin 2>$null
if ($existingRemote) {
    Write-Host "Remote origin already exists: $existingRemote" -ForegroundColor Green
} else {
    & $GhExe repo view ("jaws1111/" + $RepoName) 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Repo exists on GitHub - linking local repo..." -ForegroundColor Yellow
        git remote add origin ($RepoUrl + ".git")
    } else {
        Write-Host "Creating new public repo: $RepoName" -ForegroundColor Yellow
        & $GhExe repo create $RepoName `
            --public `
            --source=. `
            --remote=origin `
            --description $RepoDescription
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create GitHub repository."
        }
        Write-Host "Repository created." -ForegroundColor Green
    }
}

# --- Step 3: Push ---
Write-Host ""
Write-Host "[3/3] Pushing to GitHub..." -ForegroundColor Cyan
git push -u origin main
if ($LASTEXITCODE -ne 0) {
    throw "Push failed."
}

Write-Host ""
Write-Host "Done! Repository synced:" -ForegroundColor Green
Write-Host ("  " + $RepoUrl) -ForegroundColor Green
