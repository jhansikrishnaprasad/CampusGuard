# Publish this project to YOUR GitHub account using GitHub's official browser sign-in (GitHub CLI).
# No password or token is typed into this script or into any chat. It then:
#   * replaces the <your-username> placeholder in README.md with your real account name, commits and pushes
#   * starts the "Build Windows executable" and "Tests" workflows on GitHub (GitHub's own Windows machine builds CampusGuard.exe)
#   * with -Release it also tags v<version> so the exe is attached to a GitHub Release
#   powershell -ExecutionPolicy Bypass -File .\scripts\publish_to_github.ps1 -RepoName CampusGuard -Release
param([string]$RepoName = "CampusGuard", [switch]$Private, [switch]$Release)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host "Install Git: winget install Git.Git   (then open a NEW terminal)" -ForegroundColor Red; exit 1 }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Write-Host "Install GitHub CLI: winget install GitHub.cli   (then open a NEW terminal)" -ForegroundColor Red; exit 1 }
gh auth status 2>$null; if ($LASTEXITCODE -ne 0) { gh auth login --web --git-protocol https }       # opens github.com in your browser
$user = (gh api user --jq .login)
$vis = if ($Private) { "PRIVATE" } else { "PUBLIC" }
Write-Host "Signed in as: $user"; Write-Host "About to create $vis repository '$user/$RepoName' and push the current folder."
if ((Read-Host "Type YES to continue") -ne "YES") { Write-Host "Cancelled."; exit 0 }
git config user.name  | Out-Null; if ($LASTEXITCODE -ne 0) { git config user.name  (Read-Host "Name for commits") }
git config user.email | Out-Null; if ($LASTEXITCODE -ne 0) { git config user.email (Read-Host "E-mail for commits (your GitHub noreply address keeps your real address private)") }
if (-not (Test-Path .git)) { git init -b main; git add -A; git commit -m "CampusGuard" }
$flag = if ($Private) { "--private" } else { "--public" }
gh repo create "$user/$RepoName" $flag --source . --remote origin --push --description "CampusGuard - AI-based video surveillance analytics for campus safety and dress-code compliance"
if ($LASTEXITCODE -ne 0) { Write-Host "Repository creation failed (name already taken?). Nothing was overwritten." -ForegroundColor Red; exit 1 }
# fill in the real repository URL
$url = "https://github.com/$user/$RepoName"
$readme = Get-Content README.md -Raw
if ($readme -match "<your-username>") {
    ($readme -replace "<your-username>/CampusGuard", "$user/$RepoName") | Set-Content README.md -NoNewline
    git add README.md; git commit -m "Set repository URL in README"; git push
}
# start the cloud builds
Start-Sleep -Seconds 5
gh workflow run "Build Windows executable" 2>$null
gh workflow run "Tests" 2>$null
if ($Release) {
    $ver = (Select-String -Path app\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
    git tag "v$ver"; git push origin "v$ver"
   Write-Host "Tagged v${ver}: the exe will be attached to $url/releases when the build finishes."
}
Write-Host ""
Write-Host "Repository : $url" -ForegroundColor Green
Write-Host "Builds     : $url/actions   (wait about 5-10 minutes, then open the 'Build Windows executable' run -> Artifacts -> CampusGuard-Windows)"
Write-Host "Check it is public: open $url in a private/incognito browser window."
