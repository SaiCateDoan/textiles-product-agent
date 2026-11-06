param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $env:DEEPSEEK_API_KEY) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
    if (-not $env:DEEPSEEK_API_KEY) { $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','Machine') }
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'Python 3.11+ is required. Install Python and run again.' }
& $pythonCommand.Source scripts/bootstrap.py
if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed.' }
$demoPort = if ($env:APP_PORT) { [int]$env:APP_PORT } else { 8765 }
$erpPort = if ($env:ERP_PORT) { [int]$env:ERP_PORT } else { 8766 }
$demoUrl = "http://127.0.0.1:$demoPort"
$runtimeDir = if ($env:DEMO_RUNTIME_DIR) { $env:DEMO_RUNTIME_DIR } else { Join-Path $PSScriptRoot '.runtime' }
$runtimeDir = [IO.Path]::GetFullPath($runtimeDir)
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$statePath = Join-Path $runtimeDir 'state.json'

function Get-DemoState {
    try {
        return Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop | ConvertFrom-Json
    } catch { return $null }
}

function Test-DemoReady {
    $demoState = Get-DemoState
    if (-not $demoState -or $demoState.workspace -ne $PSScriptRoot -or
        $demoState.app_port -ne $demoPort -or $demoState.erp_port -ne $erpPort) { return $false }
    try {
        Get-Process -Id $demoState.supervisor_pid -ErrorAction Stop | Out-Null
        $health = Invoke-RestMethod "$demoUrl/api/health" -TimeoutSec 1
        if ($health.status -ne 'ok' -or $health.service -ne 'textiles-agent' -or $health.erp.status -ne 'ok') { return $false }
        # Old running instances have no launch_id; still allow their normal reuse.
        return (-not $demoState.launch_id -or $health.instance_id -eq $demoState.launch_id)
    } catch { return $false }
}

function Get-StartupFailure([string]$reason) {
    $details = @($reason, "Startup log: $stderrLog")
    foreach ($logPath in @($stderrLog, $stdoutLog)) {
        if (Test-Path -LiteralPath $logPath) {
            $details += Get-Content -LiteralPath $logPath -Tail 25 -ErrorAction SilentlyContinue
        }
    }
    # The supervisor includes the current child failure in its own error output.
    return ($details -join [Environment]::NewLine)
}

if (-not (Test-DemoReady)) {
    $launchId = [Guid]::NewGuid().ToString('N')
    $stdoutLog = Join-Path $runtimeDir "launcher-$launchId.out.log"
    $stderrLog = Join-Path $runtimeDir "launcher-$launchId.err.log"
    $demoPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $previousLaunchId = $env:DEMO_LAUNCH_ID
    try {
        $env:DEMO_LAUNCH_ID = $launchId
        $supervisor = Start-Process -FilePath $demoPython -ArgumentList '-m','app.launcher' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        # Keep the process handle open so Windows PowerShell 5.1 can retrieve
        # ExitCode even when this short-lived duplicate launcher has exited.
        $supervisorHandle = $supervisor.Handle
    } finally { $env:DEMO_LAUNCH_ID = $previousLaunchId }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        # Check the shared service first: a duplicate launcher exits successfully
        # while the owning supervisor may still be starting its child services.
        if (Test-DemoReady) { $ready = $true; break }
        $supervisor.Refresh()
        if ($supervisor.HasExited) {
            $supervisor.WaitForExit()
            if ($null -ne $supervisor.ExitCode -and $supervisor.ExitCode -ne 0) {
                throw (Get-StartupFailure "Demo startup failed (exit $($supervisor.ExitCode)).")
            }
        }
    }
    if (-not $ready) {
        $demoState = Get-DemoState
        if ($demoState -and $demoState.launch_id -eq $launchId) {
            Set-Content -LiteralPath (Join-Path $runtimeDir 'shutdown.request') -Value 'startup-timeout'
        }
        throw (Get-StartupFailure 'Startup timed out: no healthy Demo instance became ready.')
    }
}
Write-Host "Demo ready: $demoUrl"
$demoData = if ($env:DEMO_DATA_DIR) { $env:DEMO_DATA_DIR } else { Join-Path $PSScriptRoot 'data' }
Write-Host ("Login accounts: " + (Join-Path $demoData 'demo-accounts.json'))
if (-not $env:DEEPSEEK_API_KEY) { Write-Warning 'DEEPSEEK_API_KEY missing. Business UI works; configure it and restart for AI chat.' }
if (-not $NoBrowser) { Start-Process $demoUrl }
