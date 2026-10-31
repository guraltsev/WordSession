# Build the Windows bundle: dist\WordSession and dist\WordSession-<version>-win64.zip.
# -NoSync skips 'uv sync' (use when the environment is already synced or an exe is locked).
param([switch]$NoSync)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "command failed with exit code $LASTEXITCODE" }
}

$run = if ($NoSync) { '--no-sync' } else { '--frozen' }
if (-not $NoSync) {
    # 'uv sync' rewrites .venv\Scripts\word-session*.exe, which Windows keeps locked
    # while any Word Session started from the venv runs. Say which one, up front.
    $venvExe = Join-Path $root '.venv\Scripts\word-session'
    $running = @(Get-CimInstance Win32_Process |
        Where-Object { $_.Name -in 'word-session.exe', 'word-session-cli.exe' -and $_.CommandLine -like "*$venvExe*" })
    if ($running.Count -gt 0) {
        $running | ForEach-Object { Write-Host ("  PID {0}: {1}" -f $_.ProcessId, $_.CommandLine) }
        throw ("Word Session is running from .venv (listed above), so 'uv sync' cannot replace it. " +
            "Quit it (tray > Quit, 'word-session-cli quit-app', or Stop-Process -Id <PID>), " +
            "or build with -NoSync.")
    }
    Invoke-Checked { uv sync --frozen }
}

# PyInstaller replaces dist\WordSession, whose files stay locked while a previous
# build runs from it.
$bundle = Join-Path $root 'dist\WordSession'
$fromBundle = @(Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith("$bundle\", 'OrdinalIgnoreCase') })
if ($fromBundle.Count -gt 0) {
    $fromBundle | ForEach-Object { Write-Host ("  PID {0}: {1}" -f $_.ProcessId, $_.ExecutablePath) }
    throw ("Word Session is running from dist\WordSession (listed above), so it cannot be rebuilt. " +
        "Quit it (tray > Quit, or 'dist\WordSession\word-session-cli.exe quit-app') and build again.")
}
Invoke-Checked { uv run $run pyinstaller --noconfirm --clean packaging/word-session.spec }

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
