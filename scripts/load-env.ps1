# load-env.ps1 - dot-source to load the repo's .env into this PowerShell session.
#
#   . .\scripts\load-env.ps1
#
# Values already present in the environment are NOT overridden.
param(
    [string]$Path = (Join-Path (Split-Path -Parent $PSScriptRoot) ".env")
)

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Host "load-env: no .env at $Path (copy .env.example to .env and fill it in)" -ForegroundColor Yellow
    return
}

Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $k, $v = $line.Split("=", 2)
    $k = $k.Trim(); $v = $v.Trim().Trim('"').Trim("'")
    if ($k -and -not [Environment]::GetEnvironmentVariable($k, "Process")) {
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}
Write-Host "load-env: loaded $Path" -ForegroundColor Green
