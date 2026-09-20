# sdexe installer for Windows.
#
#   irm https://sdexe.com/install.ps1 | iex
#
# Installs everything sdexe needs on a fresh PC, in order:
#   Python 3.12 (via winget, or python.org if winget is missing) -> pipx -> ffmpeg -> sdexe
# Safe to re-run: existing pieces are skipped, sdexe is upgraded.

$ErrorActionPreference = "Stop"
$MinMinor = 10
$script:Step = 0

function Write-Step($msg) { $script:Step++; Write-Host ""; Write-Host "[$script:Step] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    + $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }
function Write-Warn($msg) { Write-Host "    ! $msg" -ForegroundColor Yellow }
function Fail($msg, $hint) {
    Write-Host ""; Write-Host "x $msg" -ForegroundColor Red
    if ($hint) { Write-Host "  $hint" }
    exit 1
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-PythonOk($exe) {
    try {
        $out = & $exe -c "import sys; print(1 if sys.version_info >= (3, $MinMinor) else 0)" 2>$null
        return ($out -eq "1")
    } catch { return $false }
}

function Find-Python {
    # The py launcher is the most reliable way to reach a specific version.
    foreach ($v in "3.14", "3.13", "3.12", "3.11", "3.10") {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $out = & py "-$v" -c "print(1)" 2>$null
            if ($out -eq "1") { return @("py", "-$v") }
        }
    }
    foreach ($c in "python", "python3") {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        # Skip the Microsoft Store stub that opens the Store instead of Python.
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*" -and (Test-PythonOk $cmd.Source)) { return @($cmd.Source) }
    }
    return $null
}

function Invoke-Py {
    param([string[]]$PyCmd, [Parameter(ValueFromRemainingArguments)] [string[]]$Args)
    $exe = $PyCmd[0]
    $pre = @()
    if ($PyCmd.Count -gt 1) { $pre = $PyCmd[1..($PyCmd.Count - 1)] }
    & $exe @pre @Args
}

Write-Host ""
Write-Host "sdexe installer  (windows)" -ForegroundColor Cyan
Write-Host "Suite for Downloading, Editing & eXporting Everything" -ForegroundColor DarkGray

$winget = Get-Command winget -ErrorAction SilentlyContinue

# ── Python ────────────────────────────────────────────────────────────────────
Write-Step "Checking Python"
$py = Find-Python
if ($py) {
    $ver = Invoke-Py $py -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"
    Write-Ok "Python $ver"
} else {
    Write-Info "No Python 3.$MinMinor+ found. Installing Python 3.12 for the current user."
    if ($winget) {
        Write-Info "Using winget..."
        & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
    } else {
        Write-Info "winget is not available. Downloading the installer from python.org..."
        $arch = if ([Environment]::Is64BitOperatingSystem) { "-amd64" } else { "" }
        $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10$arch.exe"
        $tmp = Join-Path $env:TEMP "python-installer.exe"
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
        Write-Info "Running the installer silently (Add to PATH is on)..."
        $p = Start-Process -FilePath $tmp -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_test=0" -Wait -PassThru
        Remove-Item $tmp -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0) { Fail "The Python installer exited with code $($p.ExitCode)." "Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." }
    }
    Refresh-Path
    $py = Find-Python
    if (-not $py) { Fail "Python installed but cannot be found yet." "Close this window, open a new PowerShell, and run the installer again." }
    $ver = Invoke-Py $py -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"
    Write-Ok "Python $ver installed"
}

# ── pipx ──────────────────────────────────────────────────────────────────────
Write-Step "Checking pipx"
$havePipx = $false
try { Invoke-Py $py -m pipx --version 2>$null | Out-Null; $havePipx = ($LASTEXITCODE -eq 0) } catch {}
if ($havePipx) {
    Write-Ok "pipx already installed"
} else {
    Write-Info "Installing pipx..."
    Invoke-Py $py -m pip install --user --quiet --upgrade pipx
    if ($LASTEXITCODE -ne 0) { Fail "pipx did not install." "Try: python -m pip install --user pipx" }
    Write-Ok "pipx installed"
}
Invoke-Py $py -m pipx ensurepath 2>$null | Out-Null
Refresh-Path
$pipxBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $pipxBin) { $env:Path = "$pipxBin;$env:Path" }

# ── ffmpeg ────────────────────────────────────────────────────────────────────
Write-Step "Checking ffmpeg"
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Ok "ffmpeg already installed"
} elseif ($winget) {
    Write-Info "ffmpeg handles audio and video conversion. Installing with winget..."
    try {
        & winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Refresh-Path
        if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Write-Ok "ffmpeg installed" }
        else { Write-Ok "ffmpeg installed (available after you open a new window)" }
    } catch {
        Write-Warn "ffmpeg did not install. sdexe will use its bundled copy instead."
    }
} else {
    Write-Warn "ffmpeg not found and winget is unavailable. sdexe will use its bundled copy instead."
}

# ── sdexe ─────────────────────────────────────────────────────────────────────
Write-Step "Installing sdexe"
$installed = $false
try { $list = Invoke-Py $py -m pipx list --short 2>$null; $installed = ($list -match '^sdexe ') } catch {}
if ($installed) {
    Write-Info "sdexe is already installed, upgrading to the latest version..."
    Invoke-Py $py -m pipx upgrade sdexe | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "Upgrade failed." "Try: pipx upgrade sdexe" }
    # pipx upgrade leaves yt-dlp pinned; keep the downloader engine current.
    Invoke-Py $py -m pipx runpip sdexe install -U yt-dlp 2>$null | Out-Null
    Write-Ok "sdexe upgraded"
} else {
    Write-Info "Downloading sdexe and its dependencies from PyPI..."
    Invoke-Py $py -m pipx install sdexe | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "sdexe did not install." "Try: pipx install sdexe" }
    Write-Ok "sdexe installed"
}
Refresh-Path
if (Test-Path $pipxBin) { $env:Path = "$pipxBin;$env:Path" }

$sdexe = Get-Command sdexe -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "+ Done." -ForegroundColor Green
Write-Host ""
Write-Host "Run sdexe from any terminal to start it. It opens in your browser at http://localhost:5001"
if (-not $sdexe) {
    Write-Host "Open a new PowerShell window first so the sdexe command is found." -ForegroundColor DarkGray
    exit 0
}
$ans = Read-Host "`nLaunch sdexe now? [Y/n]"
if ($ans -notmatch '^(n|no)$') {
    & $sdexe.Source
} else {
    Write-Host "Open a new PowerShell window first so the sdexe command is found." -ForegroundColor DarkGray
}
