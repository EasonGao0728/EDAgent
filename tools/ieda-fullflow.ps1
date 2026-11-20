param([Parameter(Mandatory=$true)][string]$Task,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    & "$projectRoot\.venv-agent\Scripts\python.exe" -B tools/run_ieda_fullflow_local.py --task $Task --output $Output
    if ($LASTEXITCODE -ne 0) { throw 'iEDA continuation failed; inspect the new output directory logs.' }
} finally { Pop-Location }
