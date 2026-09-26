# Dot-sourced by the Windows build: record `tasklist` after each exit path and fail on an orphan.
function Assert-NoBackend([string]$After) {
  $list = (tasklist /FI "IMAGENAME eq polmon-backend.exe" /NH | Out-String).Trim()
  "[$((Get-Date).ToUniversalTime().ToString('o'))] after ${After}: $list" |
    Add-Content -Encoding utf8 windows-cleanup-proof.txt
  if ($list -match "polmon-backend\.exe") { throw "orphan polmon-backend.exe after ${After}: $list" }
}
