param(
    [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
$envFile = Join-Path $scriptDir ".env"

function Get-PythonCommand {
    $candidates = @(
        (Join-Path $scriptDir ".venv\Scripts\python.exe"),
        "C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return @{ FilePath = $candidate; Arguments = @() }
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source -notlike "*WindowsApps*") {
        return @{ FilePath = $pythonCommand.Source; Arguments = @() }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand -and $pyCommand.Source -notlike "*WindowsApps*") {
        return @{ FilePath = $pyCommand.Source; Arguments = @("-3") }
    }

    throw "Python was not found. Install Python or create a local .venv first."
}

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $line = Get-Content $Path | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

function Ensure-ApiKey {
    if ($env:OPENAI_API_KEY) {
        return
    }

    $savedKey = Get-DotEnvValue -Path $envFile -Name "OPENAI_API_KEY"
    if ($savedKey) {
        $env:OPENAI_API_KEY = $savedKey
        return
    }

    Write-Host ""
    Write-Host "OPENAI_API_KEY is not set yet." -ForegroundColor Yellow
    Write-Host "Paste your OpenAI API key to save it in .env for next time." -ForegroundColor Yellow
    $enteredKey = Read-Host "OpenAI API key"

    if (-not $enteredKey) {
        throw "No OpenAI API key was entered."
    }

    Set-Content -Path $envFile -Value @(
        "OPENAI_API_KEY=$enteredKey"
        "OPENAI_MODEL=gpt-4.1-nano"
    )
    $env:OPENAI_API_KEY = $enteredKey

    Write-Host ""
    Write-Host "Saved your API key to .env" -ForegroundColor Green
    Write-Host ""
}

$python = Get-PythonCommand
Write-Host ""
Write-Host "Starting BTC Signal Agent in the console..." -ForegroundColor Cyan
Write-Host "Folder: $scriptDir"
Write-Host ""
Write-Host "The app will ask you to choose the update speed." -ForegroundColor Yellow
Write-Host "This version uses your OPENAI_API_KEY for the trading signal." -ForegroundColor Yellow
Write-Host "Tip: you can store the key in a local .env file for double-click startup." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop the tracker." -ForegroundColor Yellow
Write-Host ""

try {
    Ensure-ApiKey

    $arguments = @(".\btc_agent.py")
    if ($Once) {
        $arguments += "--once"
    }

    & $python.FilePath @($python.Arguments + $arguments)
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "The tracker exited with an error." -ForegroundColor Red
        Read-Host "Press Enter to close"
    }
    exit $LASTEXITCODE
}
catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
