param(
    [Parameter(Position=0, Mandatory=$true)]
    [string]$Command,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$CommandArgs
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv. Follow README setup first.'
}
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    Push-Location $projectRoot
    if ($Command -eq 'test') {
        & $pythonPath -m pytest @CommandArgs
    } else {
        & $pythonPath -m financial_annotation_harness $Command @CommandArgs
    }
    $resultCode = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
exit $resultCode
