# Build the Windows bundle: dist\WordSession and dist\WordSession-<version>-win64.zip.
# -NoSync skips 'uv sync' (use when the environment is already synced or an exe is locked).
# -Installer also builds dist\WordSession-<version>-setup.exe with Inno Setup (skipped when iscc.exe is missing).
param([switch]$NoSync, [switch]$Installer)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "command failed with exit code $LASTEXITCODE" }
}

$run = if ($NoSync) { '--no-sync' } else { '--frozen' }
if (-not $NoSync) { Invoke-Checked { uv sync --frozen } }
Invoke-Checked { uv run $run pyinstaller --noconfirm --clean packaging/word-session.spec }

$bundle = Join-Path $root 'dist\WordSession'
Copy-Item (Join-Path $root 'packaging\shims\*.cmd') $bundle -Force

$version = (& uv run $run python -c "from importlib.metadata import version; print(version('word-session'))").Trim()
if ($LASTEXITCODE -ne 0) { throw 'could not read the package version' }
$zip = Join-Path $root "dist\WordSession-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
# Virus scanners can briefly lock freshly written files, so retry a few times.
for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        if (Test-Path $zip) { Remove-Item $zip -Force }
        Compress-Archive -Path $bundle -DestinationPath $zip -ErrorAction Stop
        break
    }
    catch {
        if ($attempt -eq 5) { throw }
        Start-Sleep -Seconds (2 * $attempt)
    }
}
Write-Host "Built $zip"

# Optional: compile the per-user installer when Inno Setup is available.
if ($Installer) {
    $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $candidates = @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    }
    if ($iscc) {
        Invoke-Checked { & $iscc "/DAppVersion=$version" (Join-Path $root 'packaging\installer.iss') }
        Write-Host "Built $(Join-Path $root "dist\WordSession-$version-setup.exe")"
    }
    else {
        Write-Host 'Skipped the installer: iscc.exe (Inno Setup 6) was not found.'
        Write-Host 'Install it with: winget install JRSoftware.InnoSetup  (or from https://jrsoftware.org/isinfo.php), then run build.ps1 -Installer again.'
    }
}
