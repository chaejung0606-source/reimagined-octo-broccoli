# COSS 업무데스크 설치 - 윈도우만 있는 PC 에서 필요한 것을 받아 앱을 띄운다.
#
#   파이썬(없으면 받음) -> Git(없으면 휴대용 MinGit 을 받음) -> 저장소 받기 -> 앱 실행.bat
#
# 관리자 권한이 없어도 된다 - 전부 사용자 폴더(%LOCALAPPDATA%\COSS업무데스크) 안에 둔다.
#   app\     저장소 작업본 (앱 실행.bat 이 여기 있다. 앱의 자동 업데이트도 이 폴더에서 git pull)
#   tools\   MinGit (Git 이 PATH 에 없을 때만. updater.py 가 이 위치를 안다)
# 두 번째로 돌리면 있는 것은 건너뛰고 저장소만 최신으로 당긴다.
#
# 이 파일은 UTF-8 BOM 으로 저장한다 - BOM 이 없으면 한글 윈도우의 PowerShell 5.1 이 CP949 로 읽어
# 한글 문구가 깨진다. 보통은 설치.bat 이 이 파일을 돌린다. 직접 돌리려면:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# 받는 곳(세 군데뿐):
#   파이썬   winget(Python.Python.3.12) -> 안 되면 python.org 공식 설치 파일
#   Git      github.com/git-for-windows 릴리스의 MinGit zip (무설치)
#   앱       github.com/chaejung0606-source/reimagined-octo-broccoli (공개 저장소)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = 'chaejung0606-source/reimagined-octo-broccoli'
$Branch = 'claude/expense-document-review-criteria-yzji9p'   # updater.BRANCH 와 같아야 한다
$Root = Join-Path $env:LOCALAPPDATA 'COSS업무데스크'
$App = Join-Path $Root 'app'
$Tools = Join-Path $Root 'tools'
$PyVersion = '3.12.8'
# 최신 판을 못 읽을 때 쓰는 알려진 판 (2026-10-12 확인)
$MinGitKnown = 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip'

function Say($text) { Write-Host "  $text" }

function Refresh-Path {
    # 방금 설치한 것이 PATH 에 들어가도 지금 창은 모른다. 레지스트리에서 다시 읽는다.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user;$env:Path"
}

function Find-Python {
    # 3.11 이상인 진짜 파이썬만. 윈도우 11 의 python.exe 는 스토어로 보내는 빈 껍데기라 버전이 안 나온다.
    foreach ($name in @('py', 'python')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $v = & $cmd.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($v -and ([version]$v -ge [version]'3.11')) { return $cmd.Source }
        } catch { }
    }
    # 사용자 폴더에 깔린 파이썬도 3.11 이상만. 이름순으로 고르면 Python39 가 Python312 보다 앞서 옛 판이 뽑혔다(2026-10-14 점검)
    $best = $null
    $bestVersion = [version]'0.0'
    foreach ($exe in Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue) {
        try {
            $v = & $exe.FullName -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($v -and ([version]$v -ge [version]'3.11') -and ([version]$v -gt $bestVersion)) { $best = $exe.FullName; $bestVersion = [version]$v }
        } catch { }
    }
    return $best
}

function Install-Python {
    Say '[1/3] 파이썬을 받습니다 (몇 분 걸립니다)'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements --silent | Out-Null
        } catch { }
        Refresh-Path
        if (Find-Python) { return }
        Say 'winget 으로는 받지 못해 python.org 에서 직접 받습니다'
    }
    $url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"
    $exe = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
    Invoke-WebRequest -UseBasicParsing $url -OutFile $exe
    # 사용자 설치 - 관리자 권한 없이. PATH 와 py 런처를 함께 넣는다.
    Start-Process -FilePath $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'InstallLauncherAllUsers=0', 'Include_test=0' -Wait
    Refresh-Path
}

function Find-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $portable = Join-Path $Tools 'MinGit\cmd\git.exe'
    if (Test-Path $portable) { return $portable }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Git\cmd\git.exe", "$env:ProgramFiles\Git\cmd\git.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Install-Git {
    Say '[2/3] Git 을 받습니다 - 앱이 스스로 업데이트하는 데 씁니다 (약 50MB)'
    # 설치 프로그램 대신 압축만 푸는 MinGit. 관리자 권한이 필요 없다.
    $url = $null
    try {
        $release = Invoke-RestMethod -UseBasicParsing 'https://api.github.com/repos/git-for-windows/git/releases/latest'
        $asset = $release.assets | Where-Object { $_.name -like 'MinGit-*-64-bit.zip' -and $_.name -notlike '*busybox*' } | Select-Object -First 1
        if ($asset) { $url = $asset.browser_download_url }
    } catch { }
    if (-not $url) { $url = $MinGitKnown }
    $zip = Join-Path $env:TEMP 'MinGit.zip'
    Invoke-WebRequest -UseBasicParsing $url -OutFile $zip
    $dest = Join-Path $Tools 'MinGit'
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Remove-Item $zip -ErrorAction SilentlyContinue
}

Write-Host ''
Say 'COSS 업무데스크를 설치합니다.'
Say "설치 위치: $Root"
Write-Host ''
New-Item -ItemType Directory -Force -Path $Root, $Tools | Out-Null

# 1) 파이썬
$py = Find-Python
if (-not $py) { Install-Python; $py = Find-Python }
if (-not $py) {
    throw '파이썬을 설치하지 못했습니다. https://www.python.org/downloads/ 에서 직접 설치한 뒤("Add python.exe to PATH" 체크) 이 설치를 다시 실행하세요.'
}
Say "[1/3] 파이썬: $py"
$env:Path = (Split-Path $py) + ';' + $env:Path     # 앱 실행.bat 의 where py / where python 이 이것을 먼저 찾게

# 2) Git
$git = Find-Git
if (-not $git) { Install-Git; $git = Find-Git }
if (-not $git) { throw 'Git 을 준비하지 못했습니다. 인터넷 연결을 확인하고 다시 실행하세요.' }
Say "[2/3] Git: $git"
$env:Path = (Split-Path $git) + ';' + $env:Path

# 3) 저장소 - 처음이면 받고, 있으면 최신으로
if (Test-Path (Join-Path $App '.git')) {
    Say '[3/3] 앱 저장소를 최신으로 당깁니다'
    & $git -c core.autocrlf=false -C $App pull --ff-only
} else {
    Say '[3/3] 앱 저장소를 받습니다'
    & $git -c core.autocrlf=false clone --branch $Branch --single-branch "https://github.com/$Repo.git" $App
}
if ($LASTEXITCODE -ne 0) { throw '앱 저장소를 받지 못했습니다. 인터넷 연결을 확인하고 다시 실행하세요.' }

Write-Host ''
Say '앱을 준비합니다 - 화면 라이브러리와 자동 조작용 브라우저를 받습니다 (처음 5~10분).'
Say '검은 창에 Downloading 막대가 움직이면 정상입니다. 앱이 뜨면 창은 저절로 닫힙니다.'
Write-Host ''
$launcher = Join-Path $App '앱 실행.bat'
Start-Process -FilePath $launcher -WorkingDirectory $App -Wait

Write-Host ''
Say '설치를 마쳤습니다. 다음부터는 바탕화면의 [ COSS 업무데스크 ] 아이콘으로 여세요.'
Say "앱 폴더: $App"
Write-Host ''
