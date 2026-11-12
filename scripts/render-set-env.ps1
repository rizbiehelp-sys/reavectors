# render-set-env.ps1 — push runtime env vars to Render from the local .env.
#
# Reads RENDER_API_KEY + RENDER_SERVICE_ID (and the REAVECTORS_* / SUPABASE_*
# values) from .env and REPLACES the service's environment on Render.
#
#   .\scripts\render-set-env.ps1
#
# Secrets are sent over HTTPS to the Render API and are never printed.
param(
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) ".env")
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "load-env.ps1") -Path $EnvFile

$rk  = $env:RENDER_API_KEY
$sid = $env:RENDER_SERVICE_ID
if (-not $rk -or -not $sid) { Write-Host "render-set-env: set RENDER_API_KEY and RENDER_SERVICE_ID in .env" -ForegroundColor Red; exit 1 }

# The set of variables the runtime service needs. Add to this list as you like.
$keys = @(
    "PYTHON_VERSION", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
    "REAVECTORS_MAX_UPLOAD_MB", "REAVECTORS_MAX_DIM", "REAVECTORS_MAX_PIXELS",
    "REAVECTORS_RATE", "REAVECTORS_REFINE_RATE", "REAVECTORS_MAX_CONCURRENCY",
    "REAVECTORS_MAX_SIZE", "REAVECTORS_REFINE_MAX_SECONDS", "REAVECTORS_CACHE_SIZE",
    "REAVECTORS_STATS_CACHE_SECONDS", "REAVECTORS_SUPABASE_KEEPALIVE_SECONDS",
    "REAVECTORS_API_KEY", "REAVECTORS_CORS_ORIGINS"
)

$envs = @()
foreach ($k in $keys) {
    $v = [Environment]::GetEnvironmentVariable($k, "Process")
    if ($v) { $envs += @{ key = $k; value = $v } }
}
if ($envs.Count -eq 0) { Write-Host "render-set-env: nothing to push (empty .env?)" -ForegroundColor Yellow; exit 1 }

$body = ConvertTo-Json $envs -Depth 4
$h = @{ Authorization = "Bearer $rk"; Accept = "application/json" }
$r = Invoke-WebRequest -Method PUT -Uri "https://api.render.com/v1/services/$sid/env-vars" `
    -Headers $h -ContentType "application/json" -Body $body -UseBasicParsing
Write-Host "render-set-env: PUT $($r.StatusCode) — pushed $($envs.Count) vars" -ForegroundColor Green
($r.Content | ConvertFrom-Json) | ForEach-Object {
    $k = $_.envVar.key
    $shown = if ($k -match "SECRET|KEY|TOKEN") { "***" } else { $_.envVar.value }
    Write-Host ("  {0} = {1}" -f $k, $shown)
}
