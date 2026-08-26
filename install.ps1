# compman Windows One-Line Automatic Installer
$ErrorActionPreference = "Stop"

Write-Host "🚀 Installing compman CLI..." -ForegroundColor Cyan

# Pinned uv release: versioned download + SHA256 verification (no floating installer URL).
$UvVersion = "0.12.5"
$UvInstallerSha256 = "ca1ad558c65d31e2d3a24464638aff90bfb81d6c72428b4e71d6f55944a68541"

# 1. Remove old pip-installed compman from any Python Scripts directory (prevents PATH conflicts)
$oldPipPaths = @(
    "$env:USERPROFILE\AppData\Local\Programs\Python\Python314\Scripts\compman.exe",
    "$env:USERPROFILE\AppData\Local\Programs\Python\Python313\Scripts\compman.exe",
    "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\Scripts\compman.exe",
    "$env:USERPROFILE\AppData\Local\Programs\Python\Python311\Scripts\compman.exe",
    "$env:USERPROFILE\AppData\Roaming\Python\Scripts\compman.exe"
)
foreach ($p in $oldPipPaths) {
    if (Test-Path $p) {
        Remove-Item $p -Force -ErrorAction SilentlyContinue
        Write-Host "🧹 Removed old pip-installed compman from: $p" -ForegroundColor Yellow
    }
}

# 2. Ensure ~/.local/bin is at the FRONT of User PATH
$binDir = "$env:USERPROFILE\.local\bin"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathParts = ($userPath -split ';') | Where-Object { $_ -ne "" -and $_ -ne $binDir }
$newUserPath = ($binDir + ";" + ($pathParts -join ";")).TrimEnd(";")
[Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
$env:PATH = "$binDir;$env:PATH"
Write-Host "✅ Ensured '$binDir' is at the front of User PATH." -ForegroundColor Green

# 3. Install compman via uv (uv manages its own Python, so older system Python is fine)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv v$UvVersion (Python package manager)..." -ForegroundColor Yellow
    $tmpInstaller = New-Item -ItemType File -Path (Join-Path ([System.IO.Path]::GetTempPath()) "uv-installer-$UvVersion.ps1") -Force
    try {
        Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-installer.ps1" -OutFile $tmpInstaller -UseBasicParsing
        $actualHash = (Get-FileHash -Path $tmpInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $UvInstallerSha256) {
            throw "uv installer checksum mismatch: expected $UvInstallerSha256, got $actualHash."
        }
        & powershell -NoProfile -ExecutionPolicy Bypass -File $tmpInstaller
        if ($LASTEXITCODE -ne 0) {
            throw "uv installer failed with exit code $LASTEXITCODE."
        }
    } finally {
        Remove-Item $tmpInstaller -Force -ErrorAction SilentlyContinue
    }
}
# uv tool install places shims in ~/.local/bin (already set at front of PATH above)
uv tool install --force --reinstall --managed-python git+https://github.com/allbegray/compman.git
if ($LASTEXITCODE -ne 0) {
    throw "uv tool install failed with exit code $LASTEXITCODE."
}

# 4. Best-effort PowerShell tab-completion registration (never mutates execution policy)
if (Get-Command compman -ErrorAction SilentlyContinue) {
    try {
        compman completion powershell --install | Out-Null
        Write-Host "✅ Registered shell auto-completion for PowerShell." -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Could not register PowerShell completion: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
$execPolicy = Get-ExecutionPolicy
if ($execPolicy -eq "Restricted" -or $execPolicy -eq "AllSigned") {
    Write-Host "⚠️  Execution policy '$execPolicy' prevents profile scripts from loading, so tab completion stays off." -ForegroundColor Yellow
    Write-Host "   To enable it, run this command yourself:" -ForegroundColor Yellow
    Write-Host "      Set-ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Cyan
}

Write-Host "`n🎉 compman installed successfully! Run 'compman --help' to get started." -ForegroundColor Cyan
Write-Host "   ⚠️  Please open a new terminal window for the PATH changes to take effect." -ForegroundColor Yellow
