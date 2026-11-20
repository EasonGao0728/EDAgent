$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$basePython = $env:MACRO_AGENT_PYTHON
if (-not $basePython) {
    $basePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $basePython)) {
    throw 'Set MACRO_AGENT_PYTHON to a Windows CPython 3.11+ python.exe.'
}
$venvPython = Join-Path $projectRoot '.venv-agent\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $basePython -m venv --system-site-packages (Join-Path $projectRoot '.venv-agent')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment.' }
}
& $venvPython -m pip install --disable-pip-version-check -e ($projectRoot + '[chatgpt]')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the optional ChatGPT dependencies.' }
Write-Output 'Ready. Run .\tools\agent.ps1 auth login'
