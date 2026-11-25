param([switch]$Install, [string]$Launcher = '', [string]$RuntimeFile = '')
$ErrorActionPreference = 'Stop'
# EMBED_TOOLS
if (!$ToolsScript -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'tools.ps1'))) { $ToolsScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tools.ps1') -Raw -Encoding UTF8 }

# This check runs as the desktop user. Only WSL's official installer requests UAC.
$Wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Probe = @'
python_ok=0
git_ok=0
apt_ok=0
if python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then python_ok=1; fi
version=$(git --version 2>/dev/null)
set -- $version
version=${3:-0.0}
major=${version%%.*}
rest=${version#*.}
minor=${rest%%.*}
case "$major:$minor" in
  *[!0-9:]*|:*) ;;
  *) if [ "$major" -gt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -ge 28 ]; }; then git_ok=1; fi ;;
esac
if command -v apt-get >/dev/null 2>&1; then apt_ok=1; fi
printf 'BD_ENV/1\nPYTHON=%s\nGIT=%s\nAPT=%s\n' "$python_ok" "$git_ok" "$apt_ok"
'@

function Start-CachedUpdate([string]$Current) {
    try {
        $root = Join-Path $env:LOCALAPPDATA 'Branchdesk'
        $pointer = Join-Path $root 'current.json'
        if (!(Test-Path -LiteralPath $pointer)) { return $false }
        $data = Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($data.sha256 -notmatch '^[0-9a-f]{64}$') { return $false }
        $hash = (Get-FileHash -LiteralPath $Current -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -eq $data.sha256 -or @($data.launchers) -notcontains $hash) { return $false }
        $candidate = Join-Path (Join-Path (Join-Path $root 'versions') $data.sha256) 'Branchdesk.exe'
        if (!(Test-Path -LiteralPath $candidate) -or (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $data.sha256) { return $false }
        Start-Process -FilePath $candidate
        return $true
    } catch { return $false }
}

function Get-Edge {
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
        if ($base -and (Test-Path -LiteralPath (Join-Path $base 'Microsoft\Edge\Application\msedge.exe'))) { return $true }
    }
    return $false
}

function Get-EnvironmentState {
    $state = @{ Edge = (Get-Edge); Distro = $false; Shell = $false; Python = $false; Git = $false; Apt = $false }
    $lxss = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction SilentlyContinue
    if (!$lxss -or !$lxss.DefaultDistribution) { return $state }
    $distro = Get-ItemProperty ("HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss\" + $lxss.DefaultDistribution) -ErrorAction SilentlyContinue
    if (!$distro -or !$distro.DistributionName) { return $state }
    $state.Distro = $true
    $state.Name = $distro.DistributionName
    if (!(Test-Path -LiteralPath $Wsl)) { return $state }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $Wsl
    $process.StartInfo.Arguments = '--exec sh -s'
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardInput = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.WriteLine($Probe)
        $process.StandardInput.Close()
        if (!$process.WaitForExit(90000)) {
            $process.Kill()
            return $state
        }
        $output = $stdout.GetAwaiter().GetResult()
        [void]$stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -eq 0 -and $output -match '(?m)^BD_ENV/1\r?$') {
            $state.Shell = $true
            $state.Python = $output -match '(?m)^PYTHON=1\r?$'
            $state.Git = $output -match '(?m)^GIT=1\r?$'
            $state.Apt = $output -match '(?m)^APT=1\r?$'
        }
    } catch {
        # Broken stdin, a disabled WSL feature, or an uninitialized distribution.
    } finally { $process.Dispose() }
    return $state
}

function Get-Missing($State) {
    if (!$State.Edge) { 'Microsoft Edge' }
    if (!$State.Distro) { 'WSL + Ubuntu (처음 설치할 때 관리자 승인·재부팅·Linux 계정 생성 필요)' }
    elseif (!$State.Shell) { '기본 WSL 배포판 시작 확인 (' + $State.Name + ')' }
    else {
        if (!$State.Python) { 'WSL Python 3.9 이상' }
        if (!$State.Git) { 'WSL Git 2.28 이상' }
    }
}

function Show-Message([string]$Text, [string]$Buttons = 'OK', [string]$Icon = 'Information') {
    Add-Type -AssemblyName System.Windows.Forms
    return [System.Windows.Forms.MessageBox]::Show($Text, 'Branchdesk 시작 준비', $Buttons, $Icon)
}

function Install-Environment {
    $Host.UI.RawUI.WindowTitle = 'Branchdesk 시작 준비'
    Write-Host 'Branchdesk가 필요한 프로그램을 확인하고 준비합니다.' -ForegroundColor Cyan
    $state = Get-EnvironmentState
    if (!$state.Edge) {
        if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
            & winget.exe install --id Microsoft.Edge --exact --source winget --accept-package-agreements --accept-source-agreements | Out-Host
            if ($LASTEXITCODE -ne 0 -or !(Get-Edge)) { throw 'Microsoft Edge를 설치하지 못했습니다. https://www.microsoft.com/edge/download 에서 설치한 뒤 다시 실행하세요.' }
        } else {
            Start-Process 'https://www.microsoft.com/edge/download'
            throw 'Edge 다운로드 페이지를 열었습니다. Edge 설치 후 Branchdesk.exe를 다시 실행하세요.'
        }
    }
    if (!$state.Distro) {
        if (!(Test-Path -LiteralPath $Wsl)) { throw 'Windows 11과 Windows 업데이트 상태를 확인하세요. WSL 설치 명령을 찾을 수 없습니다.' }
        Write-Host 'WSL과 Ubuntu를 설치합니다. 관리자 권한 요청을 승인하세요.'
        $installer = Start-Process -FilePath $Wsl -ArgumentList '--install', '-d', 'Ubuntu' -Verb RunAs -Wait -PassThru
        $code = $installer.ExitCode
        $installer.Dispose()
        if ($code -ne 0 -and $code -ne 3010) { throw "WSL 설치가 완료되지 않았습니다 (종료 코드 $code). 가상화 지원과 Windows 업데이트 상태를 확인하세요." }
        Write-Host ''
        Write-Host '설치 안내에 재부팅이 표시되면 작업을 저장하고 직접 재부팅하세요.' -ForegroundColor Yellow
        Write-Host 'Ubuntu를 처음 열 때 Linux 사용자 이름과 비밀번호를 만드세요.'
        Write-Host '완료 후 Branchdesk.exe를 다시 열면 Python과 Git 준비를 이어갑니다.'
        [void](Read-Host '안내를 확인했으면 Enter')
        return 2
    }
    if (!$state.Shell) { throw ('기본 WSL 배포판을 시작하지 못했습니다: ' + $state.Name + '. 시작 메뉴에서 해당 배포판을 열어 초기 계정 설정 또는 오류를 확인한 뒤 다시 실행하세요. 기존 배포판을 교체하거나 기본 배포판을 변경하지 않습니다.') }
    if (!$state.Python -or !$state.Git) {
        if (!$state.Apt) { throw ('자동 패키지 설치는 Ubuntu/Debian 계열을 지원합니다. ' + $state.Name + '의 패키지 관리자로 Python 3.9 이상과 Git 2.28 이상을 설치한 뒤 다시 실행하세요.') }
        $packages = @()
        if (!$state.Python) { $packages += 'python3' }
        if (!$state.Git) { $packages += 'git' }
        Write-Host ('기본 배포판에 설치: ' + ($packages -join ', ')) -ForegroundColor Cyan
        # Package names are fixed above; no user or repository text enters this shell command.
        & $Wsl --user root --exec sh -c ('apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ' + ($packages -join ' ')) | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '패키지 설치에 실패했습니다. 인터넷 연결과 배포판의 패키지 저장소 상태를 확인하고 다시 실행하세요.' }
    }
    $state = Get-EnvironmentState
    $missing = @(Get-Missing $state)
    if ($missing.Count) { throw ('준비되지 않은 항목: ' + ($missing -join ', ') + '. 배포판을 업데이트한 뒤 다시 실행하세요.') }
    Write-Host '준비가 끝났습니다. Branchdesk를 엽니다.' -ForegroundColor Green
    return 0
}

function Write-Runtime([string]$Python) {
    if ($RuntimeFile) { [IO.File]::WriteAllText($RuntimeFile, $Python, (New-Object Text.UnicodeEncoding($false,$false))) }
}
function Get-WindowsDefaults {
    $root = Join-Path $env:LOCALAPPDATA 'Branchdesk\tools'
    $python = Join-Path $root 'python\python.exe'
    $git = Join-Path $root 'git\cmd\git.exe'
    if (!(Test-Path -LiteralPath $python)) {
        $found = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notlike '*\WindowsApps\*') { $python = $found.Source }
    }
    if (!(Test-Path -LiteralPath $git)) {
        $found = Get-Command git.exe -ErrorAction SilentlyContinue
        if ($found) { $git = $found.Source }
        elseif (Test-Path -LiteralPath 'C:\Program Files\Git\cmd\git.exe') { $git = 'C:\Program Files\Git\cmd\git.exe' }
    }
    return @{python=$python; git=$git; kind='windows'}
}
function Test-WindowsHost($Config) {
    if (!(Get-Edge) -or !$Config.python -or !$Config.git) { return $false }
    if (!(Test-Path -LiteralPath $Config.python -PathType Leaf) -or !(Test-Path -LiteralPath $Config.git -PathType Leaf)) { return $false }
    try {
        & $Config.python -I -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $version = & $Config.git --version 2>$null
        return $LASTEXITCODE -eq 0 -and $version -match 'git version (\d+)\.(\d+)' -and ([int]$Matches[1] -gt 2 -or ([int]$Matches[1] -eq 2 -and [int]$Matches[2] -ge 28))
    } catch { return $false }
}
function Select-WindowsHost($Config) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object Windows.Forms.Form
    $form.Text = 'Branchdesk 실행 환경'
    $form.Size = New-Object Drawing.Size(680,380)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $title = New-Object Windows.Forms.Label
    $title.Text = 'Windows 단독 실행: Python·Git 경로를 선택하세요. (WSL 불필요)'
    $title.SetBounds(18,18,620,26); $form.Controls.Add($title)
    $boxes = @{}
    $row = 62
    foreach ($name in @('python','git')) {
        $label = New-Object Windows.Forms.Label
        $label.Text = if ($name -eq 'python') {'Python 실행 파일 (3.9 이상)'} else {'Git 실행 파일 (2.28 이상)'}
        $label.SetBounds(18,$row,600,22); $form.Controls.Add($label)
        $box = New-Object Windows.Forms.TextBox
        $box.Text = $Config.$name
        $box.SetBounds(18,($row+24),530,26); $form.Controls.Add($box); $boxes[$name] = $box
        $browse = New-Object Windows.Forms.Button
        $browse.Text = '찾기'; $browse.SetBounds(558,($row+23),80,27)
        $browse.Tag = $box
        $browse.Add_Click({ $picker = New-Object Windows.Forms.OpenFileDialog; $picker.Filter = '실행 파일 (*.exe)|*.exe'; if ($picker.ShowDialog() -eq 'OK') { $this.Tag.Text = $picker.FileName }; $picker.Dispose() })
        $form.Controls.Add($browse); $row += 78
    }
    $install = New-Object Windows.Forms.Button
    $install.Text = '앱 전용 폴더에 설치'; $install.SetBounds(18,240,170,32)
    $install.Add_Click({
        try {
            $script = Join-Path ([IO.Path]::GetTempPath()) ('branchdesk-tools-'+[guid]::NewGuid().ToString('N')+'.ps1')
            [IO.File]::WriteAllText($script, $ToolsScript, (New-Object Text.UTF8Encoding($true)))
            $directory = Join-Path $env:LOCALAPPDATA 'Branchdesk\tools'
            $arguments = '-NoProfile -ExecutionPolicy Bypass -File "'+$script+'" -Kind windows -Directory "'+$directory+'"'
            $child = Start-Process -FilePath $PowerShell -ArgumentList $arguments -Wait -PassThru
            $code = $child.ExitCode; $child.Dispose(); Remove-Item -LiteralPath $script -Force
            $boxes.python.Text = Join-Path $directory 'python\python.exe'
            $boxes.git.Text = Join-Path $directory 'git\cmd\git.exe'
            if ($code -ne 0) { [void](Show-Message '설치가 끝나지 않았습니다. 직접 설치된 실행 파일 경로를 연결할 수도 있습니다.' 'OK' 'Warning') }
        } catch { [void](Show-Message $_.Exception.Message 'OK' 'Error') }
    }); $form.Controls.Add($install)
    $wslButton = New-Object Windows.Forms.Button
    $wslButton.Text = 'WSL 방식 사용'; $wslButton.SetBounds(200,240,140,32)
    $wslButton.Add_Click({ $form.Tag = @{kind='wsl'}; $form.DialogResult = 'OK'; $form.Close() }); $form.Controls.Add($wslButton)
    $go = New-Object Windows.Forms.Button
    $go.Text = '연결하고 실행'; $go.SetBounds(480,286,158,32)
    $go.Add_Click({
        $selected = @{kind='windows'; python=$boxes.python.Text.Trim(); git=$boxes.git.Text.Trim()}
        if (!(Get-Edge)) { [void](Show-Message 'Microsoft Edge를 먼저 설치하세요: https://www.microsoft.com/edge/download' 'OK' 'Warning'); return }
        if (!(Test-WindowsHost $selected)) { [void](Show-Message 'Python 3.9 이상·Git 2.28 이상을 실행하지 못했습니다. 경로를 확인하거나 설치 버튼으로 준비하세요.' 'OK' 'Warning'); return }
        $form.Tag = $selected; $form.DialogResult = 'OK'; $form.Close()
    }); $form.Controls.Add($go)
    $form.AcceptButton = $go
    $answer = $form.ShowDialog()
    $selected = $form.Tag; $form.Dispose()
    if ($answer -ne 'OK') { return $null }
    $root = Join-Path $env:LOCALAPPDATA 'Branchdesk'
    [void][IO.Directory]::CreateDirectory($root)
    $selected | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'host.json') -Encoding UTF8
    return $selected
}

try {
    if (!$Install -and $Launcher -and (Start-CachedUpdate $Launcher)) { exit 20 }
    if ($Install) {
        $result = Install-Environment
        exit $result
    }
    $hostFile = Join-Path $env:LOCALAPPDATA 'Branchdesk\host.json'
    $config = $null
    if (Test-Path -LiteralPath $hostFile) { try { $config = Get-Content -LiteralPath $hostFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch {} }
    $state = $null
    if (!$config) {
        $state = Get-EnvironmentState
        if ($state.Distro -and $state.Shell) { $config = @{kind='wsl'} }
        else { $config = Get-WindowsDefaults }
    }
    if ($config.kind -eq 'windows') {
        if (!(Test-WindowsHost $config)) { $config = Select-WindowsHost $config }
        if (!$config) { exit 10 }
        if ($config.kind -eq 'windows') { Write-Runtime $config.python; exit 0 }
    }
    Write-Runtime 'wsl'
    if (!$state) { $state = Get-EnvironmentState }
    $missing = @(Get-Missing $state)
    if (!$missing.Count) { exit 0 }
    $message = "다음 항목을 준비해야 합니다.`n`n- " + ($missing -join "`n- ") + "`n`n설치를 진행할까요? 인터넷 연결이 필요합니다.`n이미 설치된 기본 WSL 배포판과 Git 설정을 사용합니다."
    if ((Show-Message $message 'YesNo' 'Question') -ne 'Yes') { exit 10 }
    # Quote the path for Windows argv; the script is never elevated wholesale.
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Install'
    $child = Start-Process -FilePath $PowerShell -ArgumentList $arguments -WindowStyle Normal -Wait -PassThru
    $code = $child.ExitCode
    $child.Dispose()
    exit $code
} catch {
    $message = $_.Exception.Message
    if ($Install) {
        Write-Host $message -ForegroundColor Red
        [void](Read-Host '안내를 확인했으면 Enter')
    } else { [void](Show-Message $message 'OK' 'Error') }
    exit 3
}
