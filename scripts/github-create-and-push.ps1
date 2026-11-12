# github-create-and-push.ps1 - make a local project folder portable on GitHub.
#
# Creates a GitHub repo for a folder (if missing) and pushes it, respecting the
# folder's .gitignore. It refuses to overwrite a repo that already has content
# unless -Force is given, and retries on GitHub's secondary rate limit.
#
#   .\scripts\github-create-and-push.ps1 -Path "C:\path\to\proj" -Name "proj"
#   .\scripts\github-create-and-push.ps1 -Path . -Name reavectors -Public
#
# Secret hygiene: run this only after the folder has a .gitignore excluding
# .env / .dev.vars / node_modules. The script prints staged secret-looking files
# and aborts if any are staged.
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Name,
    [switch]$Public,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Path = (Resolve-Path -LiteralPath $Path).Path

# token from the macOS/Windows credential manager (same one git uses)
$cred = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
$tok = (($cred -split "`n") | Where-Object { $_ -match '^password=' }) -replace '^password=',''
if (-not $tok) { Write-Host "github: no stored credential for github.com" -ForegroundColor Red; exit 1 }
$user = (($cred -split "`n") | Where-Object { $_ -match '^username=' }) -replace '^username=',''
$H = @{ Authorization = "token $tok"; "User-Agent" = "portable-push"; Accept = "application/vnd.github+json" }

# init + stage
if (-not (Test-Path (Join-Path $Path ".git"))) { git -C $Path init -q }
git -C $Path add -A

$staged = git -C $Path diff --cached --name-only
$bad = @($staged | Where-Object {
    $_ -match '(^|/)node_modules/' -or $_ -match '(^|/)\.dev\.vars$' -or
    (($_ -match '(^|/)\.env') -and ($_ -notmatch '\.example$')) -or
    $_ -match '(^|/)secrets\.json$' -or $_ -match '\.(pem|key)$'
})
if ($bad.Count -gt 0) { Write-Host "ABORT: refusing to commit secrets:" -ForegroundColor Red; $bad | ForEach-Object { Write-Host "  $_" }; exit 1 }

git -C $Path -c user.name="$user" -c user.email="$user@users.noreply.github.com" commit -q -m "Portable import snapshot" 2>$null

# create repo (retry on secondary rate limit)
$vis = if ($Public) { $false } else { $true }
$body = @{ name = $Name; private = $vis } | ConvertTo-Json
$made = $false
for ($i = 1; $i -le 6 -and -not $made; $i++) {
    try { Invoke-WebRequest -Uri "https://api.github.com/user/repos" -Method POST -Headers $H -Body $body -ContentType "application/json" -UseBasicParsing | Out-Null; Write-Host "repo created"; $made = $true }
    catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq 422) { Write-Host "repo already exists"; $made = $true }
        else { Write-Host "create $code (secondary rate limit?) retry $i in 60s"; Start-Sleep -Seconds 60 }
    }
}
if (-not $made) { Write-Host "could not create repo; try again later" -ForegroundColor Red; exit 1 }

git -C $Path remote remove origin 2>$null
git -C $Path remote add origin "https://github.com/$user/$Name.git"
$env:GIT_TERMINAL_PROMPT = "0"
if ($Force) { git -C $Path push -u -f origin main } else { git -C $Path push -u origin main }
$code = $LASTEXITCODE
Remove-Item Env:GIT_TERMINAL_PROMPT
if ($code -ne 0) { Write-Host "push failed ($code) - remote may already have history; use -Force only if you mean to overwrite" -ForegroundColor Red; exit $code }
Write-Host "pushed -> https://github.com/$user/$Name" -ForegroundColor Green
