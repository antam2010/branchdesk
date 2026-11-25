param([Parameter(Mandatory=$true)][string]$RequestFile, [Parameter(Mandatory=$true)][string]$ResultFile)
$ErrorActionPreference = 'Stop'
# EMBED_I18N
if (!(Get-Command T -CommandType Function -ErrorAction SilentlyContinue)) { . (Join-Path $PSScriptRoot 'i18n.ps1') }
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public static class BranchdeskWindows {
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindowAsync(IntPtr h, int command);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll", EntryPoint="PeekMessageW")] static extern bool PeekMessage(IntPtr message,IntPtr window,uint min,uint max,uint flags);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder name, int size);
    [StructLayout(LayoutKind.Sequential)] struct FLASH {public uint size;public IntPtr hwnd;public uint flags,count,timeout;}
    [DllImport("user32.dll")] static extern bool FlashWindowEx(ref FLASH info);
    public static long[] Windows(bool terminal) {
        var windows = new List<long>();
        EnumWindows((h,p) => {if (IsWindowVisible(h)) {var name=new StringBuilder(256);GetClassName(h,name,256);
            if (!terminal || (name.ToString()=="CASCADIA_HOSTING_WINDOW_CLASS" || name.ToString()=="ConsoleWindowClass")) windows.Add(h.ToInt64());} return true;},IntPtr.Zero);
        return windows.ToArray();
    }
    public static bool Focus(long value) {
        var h=new IntPtr(value);
        var message=Marshal.AllocHGlobal(64);
        try {PeekMessage(message,IntPtr.Zero,0,0,0);} finally {Marshal.FreeHGlobal(message);}
        if (IsIconic(h)) {ShowWindowAsync(h,9);System.Threading.Thread.Sleep(80);}
        uint unused;uint current=GetCurrentThreadId();
        uint foreground=GetWindowThreadProcessId(GetForegroundWindow(),out unused);
        bool attached=foreground!=0 && foreground!=current && AttachThreadInput(current,foreground,true);
        try {BringWindowToTop(h);SetForegroundWindow(h);} finally {if(attached) AttachThreadInput(current,foreground,false);}
        if(GetForegroundWindow()==h) return true;
        var flash=new FLASH {size=(uint)Marshal.SizeOf(typeof(FLASH)),hwnd=h,flags=3,count=4,timeout=0};
        FlashWindowEx(ref flash);return false;
    }
}
'@
function Quote-Native([string]$Value) {
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Encode-Command([string]$Code) { return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Code)) }
function Normalize-Folder([string]$Path) { return ($Path -replace '^\\\\wsl\$\\','\\wsl.localhost\').TrimEnd('\').ToLowerInvariant() }
function Explorer-Window($Shell, [string]$Path) {
    foreach ($window in @($Shell.Windows())) {
        try { if ((Normalize-Folder ([string]$window.Document.Folder.Self.Path)) -eq (Normalize-Folder $Path)) { return [long]$window.HWND } } catch {}
    }
    return 0
}
function Write-Result($Value) { [IO.File]::WriteAllText($ResultFile, ($Value|ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false))) }
try {
    $request = Get-Content -LiteralPath $RequestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $focused = $false; $window = 0
    if ($request.action -eq 'explorer') {
        if (!(Test-Path -LiteralPath $request.path -PathType Container)) { throw (T '탐색기로 열 폴더를 찾지 못했습니다.') }
        $shell = New-Object -ComObject Shell.Application
        $window = Explorer-Window $shell $request.path
        if (!$window) {
            Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList (Quote-Native $request.path)
            $deadline = (Get-Date).AddSeconds(8)
            do { Start-Sleep -Milliseconds 120; $window = Explorer-Window $shell $request.path } while (!$window -and (Get-Date) -lt $deadline)
        }
        if ($window) { $focused = [BranchdeskWindows]::Focus($window) }
        $message = if ($focused) {(T '저장소 폴더를 탐색기 앞쪽에 열었습니다.')} else {(T '탐색기를 열었습니다. 작업 표시줄에서 탐색기 창을 확인하세요.')}
    } elseif ($request.action -eq 'terminal') {
        $encodedData = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($request|ConvertTo-Json -Compress)))
        $code = '$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('''+$encodedData+'''))|ConvertFrom-Json;'
        if ($request.distro) {
            $code += '& (Join-Path $env:SystemRoot ''System32\wsl.exe'') --distribution $d.distro --cd $d.nativePath'
        } else { $code += 'Set-Location -LiteralPath $d.path' }
        $encoded = Encode-Command $code
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
        $before = [BranchdeskWindows]::Windows($true)
        if ($wt) {
            # Only constants and base64 reach Terminal's semicolon command parser.
            $arguments = '--window new new-tab --title Branchdesk ' + (Quote-Native $powershell) + ' ' + $(if (!$request.distro) {'-NoExit '} else {'-NoProfile '}) + '-EncodedCommand ' + $encoded
            $process = Start-Process -FilePath $wt.Source -ArgumentList $arguments -WindowStyle Normal -PassThru
        } else {
            $arguments = $(if ($request.distro) {'-NoProfile -NoExit -EncodedCommand '} else {'-NoExit -EncodedCommand '}) + $encoded
            $process = Start-Process -FilePath $powershell -ArgumentList $arguments -WindowStyle Normal -PassThru
        }
        $deadline = (Get-Date).AddSeconds(8)
        do {
            Start-Sleep -Milliseconds 120
            if ($wt) { $window = @([BranchdeskWindows]::Windows($true)|Where-Object {$before -notcontains $_})|Select-Object -Last 1 }
            else { $process.Refresh(); $window = $process.MainWindowHandle.ToInt64(); if (!$window) { $window = @([BranchdeskWindows]::Windows($true)|Where-Object {$before -notcontains $_})|Select-Object -Last 1 } }
        } while (!$window -and (Get-Date) -lt $deadline)
        if ($window) { $focused = [BranchdeskWindows]::Focus([long]$window) }
        $process.Dispose()
        $message = if ($focused) {(T '터미널을 화면 앞쪽에 열었습니다.')} else {(T '터미널을 열었습니다. 작업 표시줄에서 새 터미널 창을 확인하세요.')}
    } elseif ($request.action -eq 'web') {
        $uri = [Uri]$request.url
        if ($uri.Scheme -notin @('http','https') -or $uri.UserInfo) { throw (T '웹 저장소 주소를 확인하세요.') }
        Start-Process -FilePath $uri.AbsoluteUri
        $message = (T '기본 브라우저로 원격 저장소 웹페이지를 열었습니다.')
    } else { throw (T '열기 작업을 확인하세요.') }
    Write-Result @{opened=$true;foreground=$focused;message=$message}
    exit 0
} catch { Write-Result @{error=$_.Exception.Message}; exit 1 }
