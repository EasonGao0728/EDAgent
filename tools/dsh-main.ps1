param([string]$Run,[ValidateSet('start','observe','job_status','job_cancel','download')][string]$Operation='start',[string]$Job,[switch]$Baseline,[ValidateSet('sky130_gcd','ibench_gcd_legacy','sky130_sram_pair','aes_sky130_t','aes_legacy','aes_core_sky130_t')][string]$Case='sky130_gcd',[ValidateSet('placement_def','routed_def','full_backend')][string]$Goal='placement_def')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$runtimeNode='D:\dsh\resources\runtime\primary-runtime\dependencies\node\bin\node.exe'
$launchArgs=@('dsh/run.mjs','--operation',$Operation,'--case',$Case,'--goal',$Goal)
if ($Run) {$launchArgs+=@('--run',$Run)}
if ($Job) {$launchArgs+=@('--job',$Job)}
if ($Baseline) {$launchArgs+='--baseline'}
Push-Location $projectRoot
try { & $runtimeNode @launchArgs; if ($LASTEXITCODE -ne 0) {throw 'Remote request failed; preserve remote-task.json/job_id and query before resubmitting.'} }
finally {Pop-Location}
