param([switch]$Install, [string]$Launcher = '')
$ErrorActionPreference = 'Stop'

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

try {
    if (!$Install -and $Launcher -and (Start-CachedUpdate $Launcher)) { exit 20 }
    if ($Install) {
        $result = Install-Environment
        exit $result
    }
    $state = Get-EnvironmentState
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
