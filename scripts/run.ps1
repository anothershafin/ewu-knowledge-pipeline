param([Parameter(ValueFromRemainingArguments=$true)][string[]]$PipelineArgs)
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:HF_HOME = Join-Path $projectRoot '.cache\huggingface'
$env:TEMP = Join-Path $projectRoot '.cache\tmp'
$env:TMP = $env:TEMP
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.env-gpu\python.exe'
if (-not (Test-Path $pythonExe)) { $pythonExe = Join-Path $projectRoot '.env-gpu\Scripts\python.exe' }
& $pythonExe -X utf8 -m ewu_kb.cli @PipelineArgs
exit $LASTEXITCODE
