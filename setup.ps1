# Europa Medical - Python ve bagimlilik kurulumu
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$EmbedDir   = Join-Path $Root "python-embed"
$EmbedPython = Join-Path $EmbedDir "python.exe"
$PythonVersion = "3.12.10"

function Write-Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host $msg -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host $msg -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host $msg -ForegroundColor Red }

function Test-PythonExe {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    try {
        $null = & $Path -c "import sys; print(sys.version)" 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-VenvModule {
    param([string]$Path)
    if (-not (Test-PythonExe $Path)) { return $false }
    try {
        $null = & $Path -c "import venv" 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Configure-EmbeddedPython {
    # Gomulu Python'da pip ve site-packages'i etkinlestir
    $pthFile = Get-ChildItem -Path $EmbedDir -Filter "python*._pth" | Select-Object -First 1
    if ($pthFile) {
        $lines = Get-Content $pthFile.FullName
        $newLines = @()
        $hasSite = $false
        $hasSitePackages = $false
        foreach ($line in $lines) {
            if ($line -match '^#\s*import site') {
                $newLines += 'import site'
                $hasSite = $true
            } else {
                $newLines += $line
                if ($line -eq 'import site') { $hasSite = $true }
                if ($line -eq 'Lib\site-packages') { $hasSitePackages = $true }
            }
        }
        if (-not $hasSite) { $newLines += 'import site' }
        if (-not $hasSitePackages) { $newLines += 'Lib\site-packages' }
        Set-Content -Path $pthFile.FullName -Value $newLines -Encoding ASCII
    }

    $sitePackages = Join-Path $EmbedDir "Lib\site-packages"
    if (-not (Test-Path $sitePackages)) {
        New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
    }

    # pip yoksa kur
    $pipOk = $false
    try {
        $null = & $EmbedPython -m pip --version 2>&1
        $pipOk = $LASTEXITCODE -eq 0
    } catch {}

    if (-not $pipOk) {
        Write-Info "pip kuruluyor..."
        $getPip = Join-Path $env:TEMP "get-pip.py"
        try {
            Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
            & $EmbedPython $getPip --no-warn-script-location 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "get-pip basarisiz" }
        } catch {
            Write-Err "pip kurulamadi: $($_.Exception.Message)"
            exit 1
        } finally {
            Remove-Item $getPip -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not (Test-PythonExe $EmbedPython)) {
        Write-Err "Gomulu Python calistirilamadi."
        exit 1
    }

    Install-PipToolchain $EmbedPython | Out-Null

    return $EmbedPython
}

function Test-IsEmbedPython {
    param([string]$PythonPath)
    if (-not (Test-Path $PythonPath) -or -not (Test-Path $EmbedPython)) {
        return $false
    }
    try {
        $a = (Resolve-Path -LiteralPath $PythonPath).Path.ToLowerInvariant()
        $b = (Resolve-Path -LiteralPath $EmbedPython).Path.ToLowerInvariant()
        return $a -eq $b
    } catch {
        return $false
    }
}

function Install-PipToolchain {
    param([string]$PythonPath)
    $null = & $PythonPath -m pip install --upgrade pip setuptools wheel 2>&1
    return $LASTEXITCODE -eq 0
}

function Test-EmbeddedPythonHealthy {
    if (-not (Test-PythonExe $EmbedPython)) { return $false }
    try {
        $null = & $EmbedPython -c "import pip, setuptools" 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Reset-EmbeddedSitePackages {
    Write-Warn "Gomulu Python paketleri temizleniyor..."
    $sitePackages = Join-Path $EmbedDir "Lib\site-packages"
    if (Test-Path $sitePackages) {
        Get-ChildItem -Path $sitePackages -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    Configure-EmbeddedPython | Out-Null
}

function Find-SystemPython {
    # py launcher (Windows)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $exe = (& py -3 -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($exe -and (Test-PythonExe $exe)) { return $exe }
        } catch {}
    }
    foreach ($name in @("python", "python3")) {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            try {
                $exe = (& $name -c "import sys; print(sys.executable)" 2>$null).Trim()
                if ($exe -and (Test-PythonExe $exe)) { return $exe }
            } catch {}
        }
    }
    return $null
}

function Get-ArchTag {
    $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    switch ($arch) {
        "Arm64" { return "arm64" }
        default { return "amd64" }
    }
}

function Install-EmbeddedPython {
    $arch = Get-ArchTag
    $zipName = "python-$PythonVersion-embed-$arch.zip"
    $url = "https://www.python.org/ftp/python/$PythonVersion/$zipName"
    $zipPath = Join-Path $env:TEMP $zipName

    Write-Warn ""
    Write-Warn "Python bulunamadi. Otomatik indiriliyor (ilk acilista birkaç dakika surebilir)..."
    Write-Info "Surum: $PythonVersion ($arch)"
    Write-Info "Kaynak: $url"
    Write-Warn ""

    if (Test-Path $EmbedDir) {
        Remove-Item $EmbedDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $EmbedDir -Force | Out-Null

    try {
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    } catch {
        Write-Err "Python indirilemedi. Internet baglantinizi kontrol edin."
        Write-Err $_.Exception.Message
        exit 1
    }

    Expand-Archive -Path $zipPath -DestinationPath $EmbedDir -Force
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

    Configure-EmbeddedPython | Out-Null

    Write-Ok "Python basariyla indirildi."
    return $EmbedPython
}

function Ensure-Venv {
    param([string]$BasePython)

    if (Test-PythonExe $VenvPython) {
        return $VenvPython
    }

    if (-not (Test-VenvModule $BasePython)) {
        Write-Err "Bu Python surumu venv modulunu desteklemiyor."
        exit 1
    }

    Write-Info "Sanal ortam olusturuluyor (.venv)..."
    $venvDir = Join-Path $Root ".venv"

    if (Test-Path $venvDir) {
        Remove-Item $venvDir -Recurse -Force
    }

    & $BasePython -m venv $venvDir 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Sanal ortam olusturulamadi."
        exit 1
    }

    if (-not (Test-PythonExe $VenvPython)) {
        Write-Err "Sanal ortam Python'u bulunamadi."
        exit 1
    }

    Write-Ok "Sanal ortam hazir."
    return $VenvPython
}

function Resolve-Python {
    if (Test-PythonExe $VenvPython) {
        Write-Ok "Mevcut sanal ortam bulundu."
        return $VenvPython
    }

    $systemPython = Find-SystemPython
    if ($systemPython) {
        Write-Ok "Sistem Python'u bulundu: $systemPython"
        return (Ensure-Venv $systemPython)
    }

    if (Test-PythonExe $EmbedPython) {
        Write-Ok "Proje icindeki Python bulundu."
        if (-not (Test-EmbeddedPythonHealthy)) {
            Write-Warn "Gomulu Python baska bilgisayardan kopyalanmis olabilir; yeniden hazirlaniyor..."
            Configure-EmbeddedPython | Out-Null
            if (-not (Test-EmbeddedPythonHealthy)) {
                Reset-EmbeddedSitePackages
            }
        }
        if (Test-VenvModule $EmbedPython) {
            return (Ensure-Venv $EmbedPython)
        }
        Write-Info "Gomulu Python kullaniliyor (venv yok, paketler dogrudan kurulacak)..."
        return (Configure-EmbeddedPython)
    }

    $embedPy = Install-EmbeddedPython
    if (Test-VenvModule $embedPy) {
        return (Ensure-Venv $embedPy)
    }
    Write-Info "Gomulu Python kullaniliyor (venv yok, paketler dogrudan kurulacak)..."
    return $embedPy
}

function Install-Requirements {
    param([string]$PythonPath)

    $reqFile = Join-Path $Root "requirements.txt"
    if (-not (Test-Path $reqFile)) {
        Write-Err "requirements.txt bulunamadi."
        exit 1
    }

    Write-Info "Temel araclar kuruluyor (pip, setuptools, wheel)..."
    if (-not (Install-PipToolchain $PythonPath)) {
        if (Test-IsEmbedPython $PythonPath) {
            Write-Warn "pip araclari kurulamadi, gomulu Python temizleniyor..."
            Reset-EmbeddedSitePackages
            if (-not (Install-PipToolchain $EmbedPython)) {
                Write-Err "pip/setuptools kurulumu basarisiz."
                exit 1
            }
            $PythonPath = $EmbedPython
        } else {
            Write-Err "pip/setuptools kurulumu basarisiz."
            exit 1
        }
    }

    Write-Info "Gerekli paketler yukleniyor (ilk seferde biraz surebilir)..."
    $pipOut = & $PythonPath -m pip install -r $reqFile --prefer-binary 2>&1
    if ($LASTEXITCODE -ne 0 -and (Test-IsEmbedPython $PythonPath)) {
        Write-Warn "Paket kurulumu basarisiz; gomulu Python sifirlanip tekrar deneniyor..."
        Reset-EmbeddedSitePackages
        if (-not (Install-PipToolchain $EmbedPython)) {
            Write-Err "pip/setuptools kurulumu basarisiz."
            exit 1
        }
        $pipOut = & $EmbedPython -m pip install -r $reqFile --prefer-binary 2>&1
        $PythonPath = $EmbedPython
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Err "Paket kurulumu basarisiz. Internet baglantinizi kontrol edip tekrar deneyin."
        $pipOut | ForEach-Object { Write-Host $_ }
        exit 1
    }
    Write-Ok "Tum paketler yuklendi."
    return $PythonPath
}

# --- Ana akis ---
Write-Host ""
Write-Host "=== Europa Medical - Kurulum Kontrolu ===" -ForegroundColor White
Write-Host ""

$pythonToUse = Resolve-Python

$pythonToUse = Install-Requirements $pythonToUse

# calistir.bat hangi Python'u kullanacagini bilsin
$launcherHint = Join-Path $Root ".python-path"
Set-Content -Path $launcherHint -Value $pythonToUse -Encoding ASCII -NoNewline

Write-Host ""
Write-Ok "Kurulum tamam. Uygulama baslatiliyor..."
Write-Host ""
exit 0
