# Windows integration test for the launcher and the actual workbench HTTP entry points.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$socket = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$socket.Start()
$env:SILICON_PORT = [string]$socket.LocalEndpoint.Port
$socket.Stop()
$base = 'http://127.0.0.1:' + $env:SILICON_PORT
$launcher = Join-Path $root 'tools/start-silicon-workbench.ps1'
& $launcher -Prepare
$serverId = [int](Get-Content (Join-Path $root 'ic-workbench/output/server.pid'))
try {
    $health = Invoke-RestMethod "$base/api/health"
    $page = Invoke-WebRequest -UseBasicParsing "$base/"
    $session = Invoke-RestMethod "$base/api/sessions" -Method Post -Headers @{Origin=$base} -ContentType application/json -Body '{}'
    $library = Invoke-RestMethod "$base/api/agent/tools"
    $providers = Invoke-RestMethod "$base/api/providers"
    $cases = (Invoke-RestMethod "$base/api/case-packages").packages
    if ($health.source -ne 'shared-dsh-main-agent' -or $page.StatusCode -ne 200 -or !$session.id -or !$library.cards.Count -or !$providers -or !($cases | Where-Object { $_.goal -eq 'full_backend' })) {
        throw 'Workbench session, provider dialog, tool library, or full-backend catalog failed.'
    }
    & $launcher -Prepare
    $listener = Get-NetTCPConnection -LocalPort $env:SILICON_PORT -State Listen
    if ($listener.OwningProcess -ne $serverId) { throw 'Second launch replaced the running workbench.' }
    Write-Host "Windows workbench verified: new session, $($library.cards.Count) tools, $($cases.Count) cases, provider settings, warm launch."
} finally {
    $listener = Get-NetTCPConnection -LocalPort $env:SILICON_PORT -State Listen -ErrorAction SilentlyContinue
    if ($listener -and $listener.OwningProcess -eq $serverId) { Stop-Process -Id $serverId }
}