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
$demoUrl = "http://127.0.0.1:$demoPort"
$alreadyRunning = $false
$statePath = Join-Path $PSScriptRoot '.runtime/state.json'
if (Test-Path -LiteralPath $statePath) {
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $health = Invoke-RestMethod "$demoUrl/api/health" -TimeoutSec 2
        $alreadyRunning = ($state.workspace -eq $PSScriptRoot -and $health.service -eq 'textiles-agent')
    } catch { }
}
if (-not $alreadyRunning) {
    New-Item -ItemType Directory -Force .runtime | Out-Null
    $demoPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $supervisor = Start-Process -FilePath $demoPython -ArgumentList '-m','app.launcher' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot '.runtime/launcher.out.log') -RedirectStandardError (Join-Path $PSScriptRoot '.runtime/launcher.err.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        $supervisor.Refresh()
        if ($supervisor.HasExited) { throw 'Demo startup failed. See .runtime/launcher.err.log and service logs.' }
        try {
            $health = Invoke-RestMethod "$demoUrl/api/health" -TimeoutSec 1
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        Set-Content -LiteralPath (Join-Path $PSScriptRoot '.runtime/shutdown.request') -Value 'startup-timeout'
        throw 'Startup timed out; shutdown requested. Inspect .runtime logs.'
    }
}
Write-Host "Demo ready: $demoUrl"
if (-not $env:DEEPSEEK_API_KEY) { Write-Warning 'DEEPSEEK_API_KEY missing. Business UI works; configure it and restart for AI chat.' }
if (-not $NoBrowser) { Start-Process $demoUrl }
