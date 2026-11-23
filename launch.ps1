$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYGAME_HIDE_SUPPORT_PROMPT = '1'
$projectPython = Join-Path $PSScriptRoot 'runtime\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    Write-Host 'Missing project runtime: runtime\python.exe'
    exit 1
}
& $projectPython -X utf8 (Join-Path $PSScriptRoot 'bootstrap.py') @args
exit $LASTEXITCODE
