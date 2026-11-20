# Start the existing Docker installation through the Windows desktop launcher.
# Direct child-process startup reproduced error 1920 on this workstation.
# Desktop launch is the verified workaround; the OS-level cause is not proven.
param([ValidateRange(0,120)][int]$WaitSeconds=90,[switch]$Json,[switch]$ProbeOnly)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$dockerExecutable='D:\Docker\resources\bin\docker.exe'
$dockerDesktop='D:\Docker\Docker Desktop.exe'
if (!(Test-Path -LiteralPath $dockerExecutable) -or !(Test-Path -LiteralPath $dockerDesktop)) {
    throw 'Configured Docker installation not found; no installation or download was attempted.'
}
function Read-Engine {
    $startInfo=New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName=$dockerExecutable
    $config=Join-Path $projectRoot '.cache\ieda\docker-public'
    $startInfo.Arguments='--config "'+$config+'" --host npipe:////./pipe/dockerDesktopLinuxEngine info --format "{{.OSType}}/{{.ServerVersion}}"'
    $startInfo.UseShellExecute=$false
    $startInfo.CreateNoWindow=$true
    $startInfo.RedirectStandardOutput=$true
    $startInfo.RedirectStandardError=$true
    $probe=New-Object System.Diagnostics.Process
    $probe.StartInfo=$startInfo
    try {
        [void]$probe.Start()
        $stdout=$probe.StandardOutput.ReadToEndAsync()
        $stderr=$probe.StandardError.ReadToEndAsync()
        if (!$probe.WaitForExit(5000)) { $probe.Kill(); $probe.WaitForExit(); return $null }
        $text=$stdout.Result.Trim()
        if ($probe.ExitCode -eq 0 -and $text.StartsWith('linux/')) { return $text }
        return $null
    } finally { $probe.Dispose() }
}
$engine=Read-Engine
$launched=$false
if (!$ProbeOnly -and !$engine -and !(Get-Process -Name 'com.docker.backend' -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath (Join-Path $env:WINDIR 'explorer.exe') -ArgumentList ('"'+$dockerDesktop+'"') -WindowStyle Hidden
    $launched=$true
}
$probeWait=$WaitSeconds
if ($ProbeOnly) { $probeWait=0 }
$deadline=(Get-Date).AddSeconds($probeWait)
while (!$engine -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2; $engine=Read-Engine }
$result=[ordered]@{ready=[bool]$engine;engine=$engine;launched_via_desktop=$launched;code='DOCKER_READY';checked_at=(Get-Date).ToUniversalTime().ToString('o')}
if (!$engine) {
    $result.code='DOCKER_ENGINE_UNAVAILABLE'
    $result.message='Docker Linux engine is unavailable. If an error window mentions sailor-ingest.sock, choose Quit and launch Docker from Start. No EDA stage was started; resume the same task after Engine running. Do not factory-reset.'
}
if ($Json) { $result | ConvertTo-Json -Compress } else { $result | Format-List }
if (!$engine) { exit 2 }
