$ErrorActionPreference = 'Stop'
# Local machine owner can stop the supervisor; web shutdown requires an admin login.
$demoRuntime = if ($env:DEMO_RUNTIME_DIR) { $env:DEMO_RUNTIME_DIR } else { Join-Path $PSScriptRoot '.runtime' }
$demoState = Join-Path $demoRuntime 'state.json'
if (-not (Test-Path -LiteralPath $demoState)) { Write-Host 'Demo is not running.'; exit 0 }
$demoInfo = Get-Content -LiteralPath $demoState -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($demoInfo.workspace) -ne [IO.Path]::GetFullPath($PSScriptRoot)) { throw 'Runtime belongs to a different workspace.' }
Set-Content -LiteralPath (Join-Path $demoRuntime 'shutdown.request') -Value 'local-owner-stop' -Encoding UTF8
Write-Host 'Stopping Demo. Business data and reports are saved.'
