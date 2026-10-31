# Smoke-test a built bundle: smoke_test.ps1 -Dist dist\WordSession [-SkipServe]
param(
    [Parameter(Mandatory = $true)][string]$Dist,
    [switch]$SkipServe
)
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path (Join-Path $Dist 'word-session-cli.exe')).Path
$homeDir = Join-Path ([IO.Path]::GetTempPath()) ("ws-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $homeDir | Out-Null
$env:WORD_SESSION_HOME = $homeDir

function Assert-Ok {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) { throw "$What failed with exit code $LASTEXITCODE" }
    Write-Host "ok: $What"
}

try {
    & $exe --version | Out-Host
    Assert-Ok '--version'

    $doctor = (& $exe --demo --json doctor) -join "`n"
    $doctorExit = $LASTEXITCODE
    $null = $doctor | ConvertFrom-Json
    Write-Host "ok: doctor produced JSON (exit $doctorExit)"

    & $exe --demo save | Out-Host
    Assert-Ok 'save'
    $list = (& $exe --demo list) -join "`n"
    Assert-Ok 'list'
    if (-not $list.Trim()) { throw 'list printed nothing after save' }

    if (-not $SkipServe) {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $exe
        $info.Arguments = '--demo serve --port 0 --no-import'
        $info.RedirectStandardOutput = $true
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($info)
        try {
            $task = $proc.StandardOutput.ReadLineAsync()
            if (-not $task.Wait(30000)) { throw 'serve did not print its URL within 30 s' }
            if ($task.Result -notmatch '(http://127\.0\.0\.1:\d+)') { throw "no URL in: $($task.Result)" }
            $health = Invoke-RestMethod -Uri "$($Matches[1])/api/health" -TimeoutSec 10
            if (-not $health.ok) { throw 'health check returned not ok' }
            Write-Host "ok: serve health $($health.version)"
        }
        finally {
            if (-not $proc.HasExited) { $proc.Kill() }
        }
    }
    Write-Host 'smoke test passed'
}
finally {
    Remove-Item Env:WORD_SESSION_HOME -ErrorAction SilentlyContinue
    Remove-Item $homeDir -Recurse -Force -ErrorAction SilentlyContinue
}
