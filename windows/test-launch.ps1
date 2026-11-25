# Run in a Windows desktop session with Edge and the configured Windows or WSL runtime.
param([string]$Exe = (Join-Path $PSScriptRoot '..\Branchdesk.exe'))
$ErrorActionPreference = 'Stop'
$launcher = Start-Process -FilePath (Resolve-Path $Exe).Path -PassThru
$edge = $null
try {
    $deadline = (Get-Date).AddSeconds(190)
    do {
        $launcher.Refresh()
        if ($launcher.HasExited) { throw "Branchdesk exited before its window opened." }
        $child = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($launcher.Id) AND Name='msedge.exe'" |
            Where-Object { $_.CommandLine -match '--app=http://127\.0\.0\.1:\d+/#' } | Select-Object -First 1
        if ($child) {
            $edge = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
            if ($edge -and $edge.MainWindowHandle -ne [IntPtr]::Zero) { break }
        }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    if (!$edge -or $edge.MainWindowHandle -eq [IntPtr]::Zero) { throw "Edge app window not found." }
    if ($child.CommandLine -notmatch '--app=(http://127\.0\.0\.1:\d+)/#([A-Za-z0-9_-]{43})') {
        throw "Local session address missing."
    }
    $base = $Matches[1]
    $headers = @{'X-Desk-Key'=$Matches[2]}
    $response = Invoke-RestMethod -Uri "$base/api/repos" -Method Post -Headers $headers -ContentType 'application/json' -Body '{}' -TimeoutSec 10
    if (!($response.PSObject.Properties.Name -contains 'value')) { throw "Unexpected response from Git server." }
    if (!(Invoke-WebRequest -UseBasicParsing "$base/commands.js" -TimeoutSec 10).Content.Contains('fetchDialog')) {
        throw "The updated UI was not served."
    }
    if (!$edge.CloseMainWindow()) { throw "Could not close the test window." }
    if (!$launcher.WaitForExit(15000)) { throw "Launcher did not exit after the window closed." }
    if ($launcher.ExitCode -ne 0) { throw "Launcher exited with code $($launcher.ExitCode)." }
    $listening = $true
    try { $null = Invoke-WebRequest -UseBasicParsing "$base/" -TimeoutSec 2 } catch { $listening = $false }
    if ($listening) { throw "The server still responds after the test window closed." }
    Write-Output 'PASS: Branchdesk.exe, Edge window, authenticated local API, bundled UI, window close and server shutdown.'
} finally {
    if ($edge) {
        $edge.Refresh()
        if (!$edge.HasExited) { $null = $edge.CloseMainWindow() }
    }
    if (!$launcher.HasExited) { Stop-Process -Id $launcher.Id -ErrorAction SilentlyContinue }
}
