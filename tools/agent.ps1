$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$agentPython = $env:MACRO_AGENT_PYTHON
if (-not $agentPython) {
    $agentPython = Join-Path $projectRoot '.venv-agent\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $agentPython)) {
        $agentPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    }
}
if (-not (Test-Path -LiteralPath $agentPython)) {
    throw 'Set MACRO_AGENT_PYTHON to a Windows CPython 3.11+ python.exe.'
}
Push-Location -LiteralPath $projectRoot
try {
    if ($args.Count -gt 0 -and $args[0] -eq 'test') {
        & $agentPython -m unittest discover -s tests -v
    } else {
        & $agentPython -m macro_agent @args
    }
    $agentExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $agentExit
