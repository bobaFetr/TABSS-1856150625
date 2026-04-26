param(
    [int]$ApiPort = 8765,
    [int]$WebPort = 3000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$webDir = Join-Path $scriptDir "web"
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$apiOutLog = Join-Path $scriptDir "api_server.$runId.out.log"
$apiErrLog = Join-Path $scriptDir "api_server.$runId.err.log"
$webOutLog = Join-Path $webDir "next-dev.$runId.out.log"
$webErrLog = Join-Path $webDir "next-dev.$runId.err.log"
$startedProcesses = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Get-PythonCommand {
    $candidates = @(
        (Join-Path $scriptDir ".venv\Scripts\python.exe"),
        "C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source -notlike "*WindowsApps*") {
        return $pythonCommand.Source
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand -and $pyCommand.Source -notlike "*WindowsApps*") {
        return $pyCommand.Source
    }

    throw "Python was not found. Install Python or create a local .venv first."
}

function Test-Url {
    param([string]$Url)

    $client = $null
    try {
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds(2)
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $statusCode = [int]$response.StatusCode
        return $statusCode -ge 200 -and $statusCode -lt 500
    }
    catch {
        return $false
    }
    finally {
        if ($client) {
            $client.Dispose()
        }
    }
}

function Test-AgentApiCurrent {
    param([string]$Url)

    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
        return $response.ok -eq $true -and $response.auto.apiVersion -eq "2026-04-26-auto-runner-v2"
    }
    catch {
        return $false
    }
}

function Wait-ForUrl {
    param(
        [string]$Url,
        [string]$Name,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url -Url $Url) {
            Write-Host "$Name is ready: $Url" -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 700
    }

    throw "$Name did not become ready at $Url. Check the log files in this folder."
}

function Stop-PortListeners {
    param([int]$Port)

    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($connection in $connections) {
            try {
                Stop-Process -Id $connection.OwningProcess -Force -ErrorAction Stop
            }
            catch {
                Write-Host "Could not stop process on port ${Port}: $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }
    catch {
        return
    }
}

function Clear-NextBuildCache {
    $nextDir = Join-Path $webDir ".next"
    $resolvedWebDir = (Resolve-Path $webDir).Path
    if (-not (Test-Path $nextDir)) {
        return
    }

    $resolvedNextDir = (Resolve-Path $nextDir).Path
    if (-not $resolvedNextDir.StartsWith($resolvedWebDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear an unexpected .next path: $resolvedNextDir"
    }

    Remove-Item -LiteralPath $resolvedNextDir -Recurse -Force
}

function Start-LoggedProcess {
    param(
        [string]$FilePath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$StandardOutput,
        [string]$StandardError
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StandardOutput `
        -RedirectStandardError $StandardError `
        -PassThru
    $startedProcesses.Add($process)
    return $process
}

function Stop-StartedProcesses {
    foreach ($process in $startedProcesses) {
        try {
            if ($process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force
            }
        }
        catch {
            Write-Host "Could not stop process $($process.Id): $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

try {
    Set-Location $scriptDir
    if (-not (Test-Path $webDir)) {
        throw "The web directory is missing. The Next.js app was not found."
    }

    $python = Get-PythonCommand
    $env:AGENT_API_HOST = "127.0.0.1"
    $env:AGENT_API_PORT = "$ApiPort"
    $env:PY_AGENT_API_URL = "http://127.0.0.1:$ApiPort"
    $env:AUTO_SIM_ENABLED = "true"
    $env:AUTO_SIM_POLL_SECONDS = "5"
    $env:AUTO_SIM_STARTING_CASH = "500"
    $env:AUTO_SIM_BUY_COOLDOWN_SECONDS = "5"
    $env:AUTO_SIM_DROP_TO_BUY_USD = "1"
    $env:AUTO_SIM_RISE_TO_SELL_USD = "1"

    Write-Host ""
    Write-Host "Starting BTC Signal Agent dashboard..." -ForegroundColor Cyan
    Write-Host "API:  http://127.0.0.1:$ApiPort"
    Write-Host "Web:  http://127.0.0.1:$WebPort"
    Write-Host ""

    if (-not (Test-Path (Join-Path $webDir "node_modules"))) {
        Write-Host "Installing Next.js dependencies..." -ForegroundColor Yellow
        Push-Location $webDir
        cmd /c npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed."
        }
        Pop-Location
    }

    $apiHealthUrl = "http://127.0.0.1:$ApiPort/auto/status"
    if (Test-AgentApiCurrent -Url $apiHealthUrl) {
        Write-Host "Python API is already running." -ForegroundColor Green
    }
    else {
        Stop-PortListeners -Port $ApiPort
        Start-LoggedProcess `
            -FilePath $python `
            -Arguments "api_server.py" `
            -WorkingDirectory $scriptDir `
            -StandardOutput $apiOutLog `
            -StandardError $apiErrLog | Out-Null
        Wait-ForUrl -Url $apiHealthUrl -Name "Python API"
    }

    $webHealthUrl = "http://127.0.0.1:$WebPort/api/agent?action=health"
    if (Test-Url -Url $webHealthUrl) {
        Write-Host "Next.js is already running." -ForegroundColor Green
    }
    else {
        Stop-PortListeners -Port $WebPort
        Clear-NextBuildCache
        Start-LoggedProcess `
            -FilePath "cmd.exe" `
            -Arguments "/c npm run dev -- --hostname 127.0.0.1 --port $WebPort" `
            -WorkingDirectory $webDir `
            -StandardOutput $webOutLog `
            -StandardError $webErrLog | Out-Null
        Wait-ForUrl -Url $webHealthUrl -Name "Next.js"
    }

    Write-Host ""
    Write-Host "Dashboard is ready: http://127.0.0.1:$WebPort" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop the processes started by this launcher." -ForegroundColor Yellow
    Write-Host ""

    while ($true) {
        foreach ($process in $startedProcesses) {
            if ($process.HasExited) {
                throw "A dashboard process exited. API log: $apiErrLog | Web log: $webErrLog"
            }
        }
        Start-Sleep -Seconds 2
    }
}
catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "API logs: $apiOutLog / $apiErrLog"
    Write-Host "Web logs: $webOutLog / $webErrLog"
    Stop-StartedProcesses
    exit 1
}
finally {
    Stop-StartedProcesses
}
