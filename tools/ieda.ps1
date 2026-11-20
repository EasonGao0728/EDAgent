param(
    [ValidateSet('status','run')][string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $projectRoot
try {
    & (Join-Path $projectRoot '.venv-agent/Scripts/python.exe') -m macro_agent.ieda_runtime $Action
    if ($LASTEXITCODE -ne 0) { throw "iEDA $Action failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }
