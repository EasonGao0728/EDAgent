[CmdletBinding()]
param([switch]$Open, [switch]$Prepare)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$ui = Join-Path $root 'ic-workbench'
$port = if ($env:SILICON_PORT) { [int]$env:SILICON_PORT } else { 4173 }
if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid workbench port.' }
$url = "http://127.0.0.1:$port"

function Test-Ready {
    try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2 }
    catch { return $false }
    return ($health.ok -eq $true -and $health.source -eq 'shared-dsh-main-agent')
}

# A second double-click must not install dependencies or start another listener.
$guard = [Threading.Mutex]::new($false, "Local\EDAgent-Workbench-$port")
$held = $false
try {
    try { $held = $guard.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        Write-Host 'Another launcher is preparing the workbench. Please keep its window open.'
        return
    }
    if (-not (Test-Ready)) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            throw "Port $port is in use by a different or unresponsive service."
        }
        $node = (Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
        if (-not $node -or [int](& $node -p 'parseInt(process.versions.node)') -lt 24) {
            throw 'Install Node.js 24 or newer with npm, reopen this launcher and try again.'
        }
        if ($Prepare) {
            Push-Location -LiteralPath $root
            try {
                $python = Join-Path $root '.venv-agent\Scripts\python.exe'
                if (-not (Test-Path -LiteralPath $python)) {
                    $py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                    if (-not $py) { throw 'Install Python 3.11 or newer with the Windows Python launcher (py.exe).' }
                    & $py.Source -3 -m venv .venv-agent
                    if ($LASTEXITCODE) { throw 'Could not create the Python virtual environment.' }
                }
                & $python -c 'import sys; sys.exit(sys.version_info < (3, 11))'
                if ($LASTEXITCODE) { throw 'The workbench virtual environment requires Python 3.11 or newer.' }
                $stamp = Join-Path $root '.cache\windows-workbench-deps.txt'
                $signature = (Get-FileHash pyproject.toml, package.json, package-lock.json).Hash -join ':'
                if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $signature -or
                    -not (Test-Path 'node_modules\@deepseek-ai\dsh-tools\package.json') -or
                    -not (Test-Path '.venv-agent\Lib\site-packages\jwt')) {
                    Write-Host 'Installing the Python and JavaScript dependencies for this checkout...'
                    & $python -m pip install -e '.[chatgpt]'
                    if ($LASTEXITCODE) { throw 'Python dependency installation failed. See the pip output above.' }
                    & npm.cmd ci --ignore-scripts
                    if ($LASTEXITCODE) { throw 'JavaScript dependency installation failed. See the npm output above.' }
                    New-Item -ItemType Directory -Force -Path (Split-Path $stamp) | Out-Null
                    Set-Content $stamp $signature -Encoding ASCII
                }
            } finally { Pop-Location }
        }
        $output = Join-Path $ui 'output'
        New-Item -ItemType Directory -Force -Path $output | Out-Null
        $log = Join-Path $output 'server-error.log'
        $service = Start-Process -FilePath $node -ArgumentList 'server.mjs' -WorkingDirectory $ui -WindowStyle Hidden -RedirectStandardOutput (Join-Path $output 'server.log') -RedirectStandardError $log -PassThru
        $deadline = [DateTime]::UtcNow.AddSeconds(25)
        do {
            if ($service.HasExited) { throw "Workbench stopped during startup. See $log" }
            if (Test-Ready) { break }
            Start-Sleep -Milliseconds 300
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not (Test-Ready)) { throw "Workbench did not become ready. See $log" }
        Set-Content (Join-Path $output 'server.pid') $service.Id
    }
    Write-Host "EDAgent is ready at $url"
    if ($Open) { Start-Process -FilePath 'explorer.exe' -ArgumentList $url -WindowStyle Hidden }
} finally {
    if ($held) { $guard.ReleaseMutex() }
    $guard.Dispose()
}
