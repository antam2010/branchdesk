# Real filesystem/PowerShell regression checks; process launches and dialogs are intercepted.
param([string]$Helper = (Join-Path $PSScriptRoot 'update.ps1'))
$ErrorActionPreference = 'Stop'
$Helper = (Resolve-Path -LiteralPath $Helper).Path
$root = Join-Path ([IO.Path]::GetTempPath()) ('branchdesk-helper-' + [Guid]::NewGuid().ToString('N'))
$oldLocalAppData = $env:LOCALAPPDATA
$global:BranchdeskUpdateTestState = [pscustomobject]@{Launcher=''; Pointer=''; MockParent=$null; Launches=$null; FailCandidate=$false; BlockPointer=$false}
[void][IO.Directory]::CreateDirectory($root)

# Never display a Windows dialog or launch/close a real app during this test.
Add-Type -TypeDefinition @'
namespace System.Windows.Forms {
    public static class MessageBox {
        public static readonly System.Collections.Generic.List<string> Messages = new System.Collections.Generic.List<string>();
        public static void Show(string message, string title, string buttons, string icon) { Messages.Add(message); }
    }
}
'@
function Add-Type { param([string]$AssemblyName) if ($AssemblyName -ne 'System.Windows.Forms') { throw 'Unexpected assembly request' } }
function T([string]$Key) { return $Key }
function Get-Process { param([int]$Id) return $global:BranchdeskUpdateTestState.MockParent }
function Start-Process {
    param([string]$FilePath)
    if ($global:BranchdeskUpdateTestState.FailCandidate -and $FilePath -ne $global:BranchdeskUpdateTestState.Launcher) { throw 'Simulated launch failure' }
    $global:BranchdeskUpdateTestState.Launches.Add($FilePath)
}
function Assert($Condition, [string]$Message) { if (!$Condition) { throw $Message } }
function Invoke-Scenario([string]$Name, [bool]$BlockPointer = $false, [bool]$FailCandidate = $false, [bool]$Mismatch = $false) {
    $stage = Join-Path $root ('branchdesk-update-' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    $source = Join-Path $stage 'new app.exe'
    [IO.File]::WriteAllText($source, 'test executable ' + $Name)
    $sha = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    $signal = Join-Path $root ($Name + '.signal')
    $requestFile = Join-Path $stage 'request.json'
    $helperCopy = Join-Path $stage 'update.ps1'
    [IO.File]::WriteAllText($helperCopy, [IO.File]::ReadAllText($Helper, [Text.Encoding]::UTF8), (New-Object Text.UTF8Encoding($true)))
    $request = @{parentPid=123; launcher=$global:BranchdeskUpdateTestState.Launcher; signal=$signal; source=$source; sha256=$sha}
    [IO.File]::WriteAllText($requestFile, ($request | ConvertTo-Json -Compress))
    $global:BranchdeskUpdateTestState.Launches = New-Object 'Collections.Generic.List[string]'
    [System.Windows.Forms.MessageBox]::Messages.Clear()
    $global:BranchdeskUpdateTestState.BlockPointer = $BlockPointer
    $global:BranchdeskUpdateTestState.FailCandidate = $FailCandidate
    $global:BranchdeskUpdateTestState.MockParent = [pscustomobject]@{Path=$global:BranchdeskUpdateTestState.Launcher; HasExited=$false}
    if ($Mismatch) { $global:BranchdeskUpdateTestState.MockParent.Path = 'different launcher'; $global:BranchdeskUpdateTestState.MockParent.HasExited = $true }
    $global:BranchdeskUpdateTestState.MockParent | Add-Member ScriptMethod WaitForExit {
        param($Milliseconds)
        $this.HasExited = $true
        if ($global:BranchdeskUpdateTestState.BlockPointer) {
            [IO.File]::Delete($global:BranchdeskUpdateTestState.Pointer)
            [void][IO.Directory]::CreateDirectory($global:BranchdeskUpdateTestState.Pointer)
        }
        return $true
    }
    $global:BranchdeskUpdateTestState.MockParent | Add-Member ScriptMethod Dispose {}
    & $helperCopy -RequestFile $requestFile
    Assert (!(Test-Path -LiteralPath $stage)) 'Update staging directory was not cleaned up'
    return @{sha=$sha; signal=$signal; error=$(if (Test-Path -LiteralPath ($signal + '.error')) { [IO.File]::ReadAllText($signal + '.error') } else { '' })}
}
try {
    $env:LOCALAPPDATA = Join-Path $root 'user data 한글'
    [void][IO.Directory]::CreateDirectory($env:LOCALAPPDATA)
    $global:BranchdeskUpdateTestState.Launcher = Join-Path $root 'old app 한글.exe'
    [IO.File]::WriteAllText($global:BranchdeskUpdateTestState.Launcher, 'old executable remains unchanged')
    $global:BranchdeskUpdateTestState.Pointer = Join-Path (Join-Path $env:LOCALAPPDATA 'Branchdesk') 'current.json'

    $first = Invoke-Scenario 'first'
    Assert (!$first.error) ('First update failed: ' + $first.error)
    Assert ((Get-Content -LiteralPath $global:BranchdeskUpdateTestState.Pointer -Raw | ConvertFrom-Json).sha256 -eq $first.sha) 'First pointer was not saved'
    Assert ($global:BranchdeskUpdateTestState.Launches.Count -eq 1 -and $global:BranchdeskUpdateTestState.Launches[0] -ne $global:BranchdeskUpdateTestState.Launcher) 'New app was not launched'

    $second = Invoke-Scenario 'second'
    Assert (!$second.error) ('Replacing an existing pointer failed: ' + $second.error)
    $saved = [IO.File]::ReadAllText($global:BranchdeskUpdateTestState.Pointer)
    $data = $saved | ConvertFrom-Json
    Assert ($data.sha256 -eq $second.sha) 'Existing pointer did not move to the second update'
    Assert (@($data.launchers).Count -eq 1) 'Known launchers were duplicated'
    Assert ($global:BranchdeskUpdateTestState.Launches.Count -eq 1 -and $global:BranchdeskUpdateTestState.Launches[0] -ne $global:BranchdeskUpdateTestState.Launcher) 'Second app was not launched'

    $blocked = Invoke-Scenario 'blocked' $true
    Assert (Test-Path -LiteralPath ($blocked.signal + '.error')) 'Pointer replacement failure was not reported'
    Assert ($global:BranchdeskUpdateTestState.Launches.Count -eq 1 -and $global:BranchdeskUpdateTestState.Launches[0] -eq $global:BranchdeskUpdateTestState.Launcher) 'Old app did not reopen after replacement failed'
    Assert (@(Get-ChildItem -LiteralPath (Split-Path -Parent $global:BranchdeskUpdateTestState.Pointer) -Filter '*.tmp').Count -eq 0) 'Temporary pointer was not cleaned up'
    [IO.Directory]::Delete($global:BranchdeskUpdateTestState.Pointer)
    [IO.File]::WriteAllText($global:BranchdeskUpdateTestState.Pointer, $saved)

    $failed = Invoke-Scenario 'launch-failed' $false $true
    Assert (Test-Path -LiteralPath ($failed.signal + '.error')) 'Launch failure was not reported'
    Assert ([IO.File]::ReadAllText($global:BranchdeskUpdateTestState.Pointer) -eq $saved) 'Previous pointer was not restored after launch failure'
    Assert ($global:BranchdeskUpdateTestState.Launches.Count -eq 1 -and $global:BranchdeskUpdateTestState.Launches[0] -eq $global:BranchdeskUpdateTestState.Launcher) 'Old app did not reopen after launch failure'

    $mismatch = Invoke-Scenario 'mismatch' $false $false $true
    Assert (Test-Path -LiteralPath ($mismatch.signal + '.error')) 'Mismatched parent was accepted'
    Assert ($global:BranchdeskUpdateTestState.Launches.Count -eq 0) 'An unverified launcher was started'
    Assert ([IO.File]::ReadAllText($global:BranchdeskUpdateTestState.Pointer) -eq $saved) 'Mismatched request changed the pointer'
    Assert ([IO.File]::ReadAllText($global:BranchdeskUpdateTestState.Launcher) -eq 'old executable remains unchanged') 'Original executable was modified'
    Write-Output 'PASS: first/repeated pointer updates, replacement failure recovery, launch rollback, parent validation, Unicode paths, and staging cleanup.'
} finally {
    Remove-Variable -Name BranchdeskUpdateTestState -Scope Global
    $env:LOCALAPPDATA = $oldLocalAppData
    [IO.Directory]::Delete($root, $true)
}
