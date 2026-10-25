param([string]$Python = 'py', [switch]$Cpu)
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Path '.cache\tmp','.cache\huggingface' -Force | Out-Null
$env:TEMP = Join-Path $projectRoot '.cache\tmp'
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $projectRoot '.cache\huggingface'
if (-not (Test-Path '.env-gpu\Scripts\python.exe') -and -not (Test-Path '.env-gpu\python.exe')) {
    if ($Python -eq 'py') { & py -3.12 -m venv .env-gpu }
    else { & $Python -m venv .env-gpu }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 virtual environment creation failed' }
}
$index = if ($Cpu) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu128' }
$pythonExe = if (Test-Path '.env-gpu\python.exe') { '.\.env-gpu\python.exe' } else { '.\.env-gpu\Scripts\python.exe' }
& $pythonExe -m pip install --no-cache-dir 'torch>=2.8,<3' --index-url $index
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed' }
& $pythonExe -m pip install --no-cache-dir -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed' }
if ($Cpu) { Write-Host 'Set device: cpu in configs/pipeline.yaml before model runs.' }
