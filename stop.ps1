$ErrorActionPreference = 'Stop'
$demoPort = if ($env:APP_PORT) { [int]$env:APP_PORT } else { 8765 }
$demoUrl = "http://127.0.0.1:$demoPort"
$bootstrap = Invoke-RestMethod "$demoUrl/api/bootstrap"
$result = Invoke-RestMethod "$demoUrl/api/shutdown" -Method Post -Headers @{'X-Demo-Token'=$bootstrap.token} -ContentType 'application/json' -Body '{}'
Write-Host $result.message
