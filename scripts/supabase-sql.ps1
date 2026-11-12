# supabase-sql.ps1 — run SQL against your Supabase project (Management API).
#
#   .\scripts\supabase-sql.ps1 "select count(*) from public.conversions;"
#
# Requires SUPABASE_ACCESS_TOKEN in .env (the sbp_... account token).
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Query,
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) ".env"),
    [string]$ProjectRef = "qpfvblqtwhmndckghirs"
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "load-env.ps1") -Path $EnvFile

if (-not $env:SUPABASE_ACCESS_TOKEN) { Write-Host "supabase-sql: set SUPABASE_ACCESS_TOKEN in .env" -ForegroundColor Red; exit 1 }
$h = @{ Authorization = "Bearer $($env:SUPABASE_ACCESS_TOKEN)"; Accept = "application/json" }
$body = @{ query = $Query } | ConvertTo-Json
$r = Invoke-WebRequest -Method POST -Uri "https://api.supabase.com/v1/projects/$ProjectRef/database/query" `
    -Headers $h -ContentType "application/json" -Body $body -UseBasicParsing
Write-Host $r.Content
