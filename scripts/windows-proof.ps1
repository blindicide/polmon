# Dot-sourced by the Windows build: record `tasklist` after each exit path and fail on an orphan.
function Get-BackendTasks {
  (tasklist /FI "IMAGENAME eq polmon-backend.exe" /NH | Out-String).Trim()
}

function Assert-NoBackend([string]$After, [double]$WithinSeconds = 0) {
  # A one-file backend's Python child exits gracefully after its launcher dies; allow for that.
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $list = Get-BackendTasks
  while ($list -match "polmon-backend\.exe" -and $watch.Elapsed.TotalSeconds -lt $WithinSeconds) {
    Start-Sleep -Milliseconds 100
    $list = Get-BackendTasks
  }
  $waited = [math]::Round($watch.Elapsed.TotalSeconds, 2)
  "[$((Get-Date).ToUniversalTime().ToString('o'))] after ${After} (waited ${waited} s): $list" |
    Add-Content -Encoding utf8 windows-cleanup-proof.txt
  if ($list -match "polmon-backend\.exe") { throw "orphan polmon-backend.exe after ${After}: $list" }
}
