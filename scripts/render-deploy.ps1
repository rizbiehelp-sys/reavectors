# render-deploy.ps1 - trigger a deploy of the Render service.
#
#   .\scripts\render-deploy.ps1
#
# Use after pushing code (autoDeploy already handles git pushes; this is for
# re-deploying after env changes, or a manual restart).
param(
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) ".env"),
    [switch]$ClearCache
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "load-env.ps1") -Path $EnvFile

$rk  = $env:RENDER_API_KEY
$sid = $env:RENDER_SERVICE_ID
if (-not $rk -or -not $sid) { Write-Host "render-deploy: set RENDER_API_KEY and RENDER_SERVICE_ID in .env" -ForegroundColor Red; exit 1 }

$body = @{ clearCache = if ($ClearCache) { "clear" } else { "do_not_clear" } } | ConvertTo-Json
$h = @{ Authorization = "Bearer $rk"; Accept = "application/json" }
$r = Invoke-RestMethod -Method POST -Uri "https://api.render.com/v1/services/$sid/deploys" `
    -Headers $h -ContentType "application/json" -Body $body
Write-Host "render-deploy: triggered $($r.id) status=$($r.status)" -ForegroundColor Green
Write-Host "  dashboard: https://dashboard.render.com/web/$sid"
