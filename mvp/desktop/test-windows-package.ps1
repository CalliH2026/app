# Test the distributed ZIP, not a Python source checkout.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Archive = Join-Path $ProjectDir 'dist-pilot-windows/PRONOTE-Pilote-Windows-x64.zip'
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ('pronote-test-' + [guid]::NewGuid())
$env:PRONOTE_PILOT_DATA = Join-Path $TestRoot 'private-data'
Expand-Archive -Path $Archive -DestinationPath $TestRoot
$Executable = Join-Path $TestRoot 'PRONOTE Pilote/PRONOTE Pilote.exe'
$OriginalPath = $env:PATH
try {
    # No Python or installed browser on PATH while the packaged test runs.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $Process = Start-Process -FilePath $Executable -ArgumentList '--smoke-test' -PassThru
    if (-not $Process.WaitForExit(120000)) {
        Stop-Process -Id $Process.Id -Force
        throw 'Packaged smoke test timed out.'
    }
    if ($Process.ExitCode -ne 0 -or -not (Test-Path (Join-Path $env:PRONOTE_PILOT_DATA 'smoke-test-ok'))) {
        $FailureFile = Join-Path $env:PRONOTE_PILOT_DATA 'smoke-test-failure.txt'
        if (Test-Path $FailureFile) { Get-Content $FailureFile }
        throw "Packaged smoke test failed (exit $($Process.ExitCode))."
    }
    Get-Content (Join-Path $env:PRONOTE_PILOT_DATA 'smoke-test-ok')
} finally {
    $env:PATH = $OriginalPath
}
