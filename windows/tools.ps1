param([ValidateSet('windows','wsl')][string]$Kind, [string]$Directory = '', [string]$Distro = '', [string]$RequestFile = '')
$ErrorActionPreference = 'Stop'
# EMBED_I18N
if (!(Get-Command T -CommandType Function -ErrorAction SilentlyContinue)) { . (Join-Path $PSScriptRoot 'i18n.ps1') }
try {
    if (!$RequestFile) {
        $request = Join-Path ([IO.Path]::GetTempPath()) ('branchdesk-install-'+[guid]::NewGuid().ToString('N')+'.json')
        @{kind=$Kind; directory=$Directory; distro=$Distro} | ConvertTo-Json | Set-Content -LiteralPath $request -Encoding UTF8
        try {
            $arguments = '-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -RequestFile "'+$request+'"'
            $process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList $arguments -WindowStyle Normal -Wait -PassThru
            $code = $process.ExitCode; $process.Dispose(); exit $code
        } finally { Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue }
    }
    $request = Get-Content -LiteralPath $RequestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $Kind = $request.kind; $Directory = $request.directory; $Distro = $request.distro
    if ($Kind -notin @('windows','wsl')) { throw (T '설치 환경을 확인하세요.') }
    if ($Kind -eq 'windows') {
        if (!$Directory -or ![IO.Path]::IsPathRooted($Directory) -or $Directory.StartsWith('\\')) { throw (T 'Windows의 로컬 설치 폴더를 지정하세요.') }
        if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw (T 'Microsoft Store에서 앱 설치 관리자(App Installer)를 설치한 뒤 다시 시도하세요.') }
        Write-Host ((T '사용자 계정에 Git·Python 설치: ') + $Directory) -ForegroundColor Cyan
        # WinGet verifies the package manifest's installer hash. Do not disable verification.
        $git = Join-Path $Directory 'git'
        $python = Join-Path $Directory 'python'
        & winget.exe install --id Git.Git --exact --source winget --scope user --architecture x64 --location $git --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0 -and !(Test-Path -LiteralPath (Join-Path $git 'cmd\git.exe'))) { throw (T 'Git 설치가 완료되지 않았습니다. 이미 설치된 Git이 있으면 해당 경로를 직접 연결하세요.') }
        & winget.exe install --id Python.Python.3.13 --exact --source winget --scope user --architecture x64 --location $python --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0 -and !(Test-Path -LiteralPath (Join-Path $python 'python.exe'))) { throw (T 'Python 설치가 완료되지 않았습니다. 이미 설치된 Python이 있으면 해당 경로를 직접 연결하세요.') }
        if (!(Test-Path -LiteralPath (Join-Path $git 'cmd\git.exe')) -or !(Test-Path -LiteralPath (Join-Path $python 'python.exe'))) { throw (T '지정한 폴더에서 실행 파일을 찾지 못했습니다. 설치 위치를 확인하여 경로를 직접 연결하세요.') }
    } else {
        $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
        $wslArgs = @()
        if ($Distro) { $wslArgs += @('--distribution', $Distro) }
        Write-Host (T '선택한 WSL 배포판에 Python·Git·OpenSSH 클라이언트를 설치합니다.') -ForegroundColor Cyan
        & $wsl @wslArgs --user root --exec sh -c 'command -v apt-get >/dev/null || exit 30; apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 git openssh-client'
        if ($LASTEXITCODE -ne 0) { throw (T 'Ubuntu/Debian 계열의 시작 가능한 WSL 배포판에서만 설치할 수 있습니다. 다른 배포판은 직접 설치한 경로를 연결하세요.') }
    }
    Write-Host (T '설치 완료. Branchdesk에서 경로를 확인하고 저장하세요.') -ForegroundColor Green
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host (T '안내를 확인했으면 Enter')
    exit 1
}
