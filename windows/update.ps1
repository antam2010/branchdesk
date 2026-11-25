param([Parameter(Mandatory=$true)][string]$RequestFile)
$ErrorActionPreference = 'Stop'
$request = $null
$parent = $null
$previous = $null
$pointer = $null
$changed = $false
try {
    $request = Get-Content -LiteralPath $RequestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.sha256 -notmatch '^[0-9a-f]{64}$') { throw '업데이트 파일 정보가 올바르지 않습니다.' }
    $parent = Get-Process -Id ([int]$request.parentPid)
    if (![string]::Equals($parent.Path, $request.launcher, [StringComparison]::OrdinalIgnoreCase)) { throw '실행 중인 앱을 확인하지 못했습니다.' }
    if ((Get-FileHash -LiteralPath $request.source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sha256) { throw '업데이트 파일 검증에 실패했습니다.' }
    $root = Join-Path $env:LOCALAPPDATA 'Branchdesk'
    $directory = Join-Path (Join-Path $root 'versions') $request.sha256
    [void](New-Item -ItemType Directory -Path $directory -Force)
    $candidate = Join-Path $directory 'Branchdesk.exe'
    if ((Test-Path -LiteralPath $candidate) -and (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sha256) {
        Move-Item -LiteralPath $candidate -Destination ($candidate + '.bad-' + [Guid]::NewGuid().ToString())
    }
    if (!(Test-Path -LiteralPath $candidate)) { [IO.File]::Copy($request.source, $candidate, $false) }
    if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sha256) { throw '저장된 업데이트 파일 검증에 실패했습니다.' }
    $pointer = Join-Path $root 'current.json'
    $launchers = @()
    if (Test-Path -LiteralPath $pointer) {
        $previous = [IO.File]::ReadAllText($pointer)
        try { $launchers = @((ConvertFrom-Json $previous).launchers | Where-Object { $_ -match '^[0-9a-f]{64}$' }) } catch { $launchers = @() }
    }
    $launchers += (Get-FileHash -LiteralPath $request.launcher -Algorithm SHA256).Hash.ToLowerInvariant()
    $launchers = @($launchers | Select-Object -Unique)
    # Mark readiness only after every file needed after the old app exits is in Windows storage.
    [IO.File]::WriteAllText($request.signal + '.helper', 'ready')
    $deadline = (Get-Date).AddMinutes(2)
    while (!$parent.WaitForExit(200)) {
        if (Test-Path -LiteralPath ($request.signal + '.cancel')) { throw '업데이트 적용이 취소되었습니다.' }
        if ((Get-Date) -gt $deadline) { throw '현재 앱이 종료되지 않아 업데이트를 적용하지 않았습니다.' }
    }
    $newPointer = @{sha256=$request.sha256; launchers=$launchers} | ConvertTo-Json -Compress
    $tempPointer = Join-Path $root ([Guid]::NewGuid().ToString() + '.tmp')
    [IO.File]::WriteAllText($tempPointer, $newPointer)
    if (Test-Path -LiteralPath $pointer) { [IO.File]::Replace($tempPointer, $pointer, $null) }
    else { [IO.File]::Move($tempPointer, $pointer) }
    $changed = $true
    Start-Process -FilePath $candidate
} catch {
    $message = $_.Exception.Message
    if ($request) {
        try { [IO.File]::WriteAllText($request.signal + '.error', $message, (New-Object Text.UTF8Encoding($false))) } catch {}
        if ($changed) {
            try {
                if ($previous) { [IO.File]::WriteAllText($pointer, $previous) } else { Remove-Item -LiteralPath $pointer -Force }
                Start-Process -FilePath $request.launcher
            } catch {}
        }
    }
    if ($parent -and $parent.HasExited) {
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show($message, 'Branchdesk 업데이트', 'OK', 'Error')
    }
} finally {
    if ($parent) { $parent.Dispose() }
    # This directory was created exclusively by this update request.
    $stage = Split-Path -Parent $RequestFile
    if ((Split-Path -Leaf $stage) -like 'branchdesk-update-*') {
        try { Remove-Item -LiteralPath $stage -Recurse -Force } catch {}
    }
}
