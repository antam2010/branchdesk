# Run on Windows 11 after prerequisites are installed. Closes only its own test windows.
param([string]$Exe = (Join-Path $PSScriptRoot '..\Branchdesk.exe'))
$ErrorActionPreference = 'Stop'
if (Get-Process Branchdesk -ErrorAction SilentlyContinue) { throw 'Close other Branchdesk windows before running the placement test.' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BranchdeskPlacementTest {
    [StructLayout(LayoutKind.Sequential)] public struct POINT {public int x,y;}
    [StructLayout(LayoutKind.Sequential)] public struct RECT {public int left,top,right,bottom;}
    [StructLayout(LayoutKind.Sequential)] public struct PLACE {public uint length,flags,show;public POINT min,max;public RECT normal;}
    [DllImport("user32.dll")] public static extern bool GetWindowPlacement(IntPtr h,ref PLACE p);
    [DllImport("user32.dll")] public static extern bool SetWindowPlacement(IntPtr h,ref PLACE p);
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    public static PLACE Read(IntPtr h) {var p=new PLACE();p.length=(uint)Marshal.SizeOf(typeof(PLACE));if(!GetWindowPlacement(h,ref p))throw new Exception("Cannot read window placement");return p;}
}
'@
[void][BranchdeskPlacementTest]::SetProcessDpiAwarenessContext([IntPtr](-4))
$state = Join-Path $env:LOCALAPPDATA 'Branchdesk\window.bin'
$backup = if (Test-Path -LiteralPath $state) { [IO.File]::ReadAllBytes($state) } else { $null }
$owned = New-Object Collections.Generic.List[object]
function Open-TestWindow {
    $path = (Resolve-Path $Exe).Path
    $pointer = Join-Path $env:LOCALAPPDATA 'Branchdesk\current.json'
    if (Test-Path -LiteralPath $pointer) {
        $data = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        $candidate = Join-Path $env:LOCALAPPDATA ('Branchdesk\versions\'+$data.sha256+'\Branchdesk.exe')
        if ($data.sha256 -match '^[0-9a-f]{64}$' -and @($data.launchers) -contains $hash -and (Test-Path -LiteralPath $candidate)) { $path = $candidate }
    }
    $app = Start-Process -FilePath $path -PassThru
    $entry = @{app=$app; edge=$null}; $owned.Add($entry)
    $deadline = (Get-Date).AddSeconds(190)
    do {
        if ($app.HasExited) { throw 'App exited before opening its window.' }
        $child = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($app.Id) AND Name='msedge.exe'" | Where-Object {$_.CommandLine -match '--app=http://127\.0\.0\.1:\d+/#'} | Select-Object -First 1
        if ($child) {
            $edge = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
            if ($edge -and $edge.MainWindowHandle -ne [IntPtr]::Zero) { $entry.edge=$edge; Start-Sleep -Seconds 1; return $entry }
        }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    throw 'App window did not open.'
}
function Close-TestWindow($Entry) {
    if (!$Entry.edge.CloseMainWindow()) { throw 'Cannot close test window.' }
    if (!$Entry.app.WaitForExit(15000)) { throw 'App did not finish saving window state.' }
    if ($Entry.app.ExitCode -ne 0) { throw 'Test app exited with an error.' }
}
try {
    $first = Open-TestWindow
    $place = [BranchdeskPlacementTest]::Read($first.edge.MainWindowHandle)
    $place.show=1; $place.flags=0
    $place.normal.left=120; $place.normal.top=100; $place.normal.right=1160; $place.normal.bottom=820
    if (![BranchdeskPlacementTest]::SetWindowPlacement($first.edge.MainWindowHandle,[ref]$place)) { throw 'Cannot resize test window.' }
    Start-Sleep -Seconds 1; Close-TestWindow $first
    $second = Open-TestWindow
    $restored = [BranchdeskPlacementTest]::Read($second.edge.MainWindowHandle)
    foreach ($field in @('left','top','right','bottom')) {
        if ([Math]::Abs($restored.normal.$field - $place.normal.$field) -gt 4) { throw ('Window coordinate was not restored: '+$field) }
    }
    $restored.show=3; [void][BranchdeskPlacementTest]::SetWindowPlacement($second.edge.MainWindowHandle,[ref]$restored)
    Start-Sleep -Seconds 1; Close-TestWindow $second
    $third = Open-TestWindow
    $maximized = [BranchdeskPlacementTest]::Read($third.edge.MainWindowHandle)
    if ($maximized.show -ne 3) { throw 'Maximized state was not restored.' }
    $maximized.show=2; $maximized.flags=2
    [void][BranchdeskPlacementTest]::SetWindowPlacement($third.edge.MainWindowHandle,[ref]$maximized)
    Start-Sleep -Seconds 1; Close-TestWindow $third
    $fourth = Open-TestWindow
    if (([BranchdeskPlacementTest]::Read($fourth.edge.MainWindowHandle)).show -ne 3) { throw 'Closing while minimized lost the maximized restore state.' }
    Close-TestWindow $fourth
    Write-Output 'PASS: normal position/size, maximized restart, and minimized-to-maximized restore.'
} finally {
    foreach ($entry in $owned) {
        if (!$entry.app.HasExited) { if ($entry.edge) { [void]$entry.edge.CloseMainWindow() }; if (!$entry.app.WaitForExit(15000)) { Stop-Process -Id $entry.app.Id } }
    }
    if ($null -ne $backup) { [IO.File]::WriteAllBytes($state,$backup) }
    else { Remove-Item -LiteralPath $state -Force -ErrorAction SilentlyContinue }
}
