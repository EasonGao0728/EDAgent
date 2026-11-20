param([switch]$Open)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$workbench=Join-Path $projectRoot 'ic-workbench'
$url='http://127.0.0.1:4173'
$healthy=$false
try {
  $health=Invoke-RestMethod "$url/api/health" -TimeoutSec 3
  if ($health.source -ne 'shared-dsh-main-agent') { throw '端口 4173 被其他服务占用；请先检查，不会停止未知进程。' }
  $healthy=$true
} catch {
  if ($_.Exception.Message -like '*端口 4173*') {throw}
  if (Get-NetTCPConnection -State Listen -LocalPort 4173 -ErrorAction SilentlyContinue) {throw '端口 4173 已占用，但服务未通过健康检查；没有结束该进程。'}
}
if (-not $healthy) {
  $node=(Get-Command node -ErrorAction SilentlyContinue).Source
  if (-not $node) {$node='D:\dsh\resources\runtime\primary-runtime\dependencies\node\bin\node.exe'}
  if (-not (Test-Path -LiteralPath $node)) {throw '未找到 Node.js；请安装 Node 24 或修复 DSH runtime。'}
  $output=Join-Path $workbench 'output'
  New-Item -ItemType Directory -Force -Path $output | Out-Null
  $process=Start-Process -FilePath $node -ArgumentList 'server.mjs' -WorkingDirectory $workbench -WindowStyle Hidden -RedirectStandardOutput (Join-Path $output 'server.log') -RedirectStandardError (Join-Path $output 'server-error.log') -PassThru
  $process.Id | Set-Content (Join-Path $output 'server.pid')
  for ($attempt=0;$attempt -lt 20;$attempt++) {
    Start-Sleep -Milliseconds 500
    try {$health=Invoke-RestMethod "$url/api/health" -TimeoutSec 2; if ($health.source -eq 'shared-dsh-main-agent') {$healthy=$true;break}}catch{}
  }
  if (-not $healthy) {throw '工作台未启动，请查看 ic-workbench/output/server-error.log。原 DSH 未修改。'}
}
Write-Output "SILICON ready: $url (GPT-6 Astra / high)"
if ($Open) {Start-Process -FilePath 'explorer.exe' -ArgumentList $url -WindowStyle Hidden}
