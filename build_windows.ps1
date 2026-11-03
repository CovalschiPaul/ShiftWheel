param([string]$PythonExe = "")
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Build this project on Windows 10/11 x64.' }
    $ISCC = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $ISCC) {
        $ISCC = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    }
    if (-not (Test-Path $ISCC)) { throw 'Install Inno Setup 6 from jrsoftware.org, then run this again.' }
    if ($PythonExe) {
        Checked $PythonExe @('-m', 'venv', '.build-venv')
    } else {
        Checked 'py' @('-3.12', '-m', 'venv', '.build-venv')
    }
    $Python = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
    New-Item -ItemType Directory -Force 'build' | Out-Null
    Checked $Python @('-m', 'pip', 'install', '-r', 'requirements.txt', '-r', 'requirements-optional.txt', 'pyinstaller>=6.11,<7', 'pytest>=8,<10', 'pytest-timeout>=2.3,<3')
    $env:QT_QPA_PLATFORM = 'offscreen'
    Checked $Python @('-m', 'pytest', '-q', '--timeout=240', '--timeout-method=thread', '--junitxml=build/test-results.xml')
    Remove-Item Env:QT_QPA_PLATFORM
    Checked $Python @('-m', 'PyInstaller', '--clean', '--noconfirm', 'ShiftWheel.spec')
    $Report = Join-Path $PSScriptRoot 'build\package-check.json'
    Remove-Item $Report -ErrorAction SilentlyContinue
    $App = Start-Process -FilePath 'dist\ShiftWheel\ShiftWheel.exe' -ArgumentList "--package-check --report `"$Report`"" -PassThru
    if (-not $App.WaitForExit(120000)) { $App.Kill(); throw 'Packaged smoke test timed out.' }
    if ($App.ExitCode -ne 0 -or -not (Test-Path $Report)) { throw 'Packaged smoke test failed. See build\package-check.json.' }
    if (-not (Get-Content $Report -Raw | ConvertFrom-Json).ok) { throw 'Packaged conversion checks failed.' }
    $Version = (& $Python 'build_version.py').Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+\.\d+(\.\d+)?$') { throw 'Invalid application version.' }
    Checked $ISCC @("/DAppVersion=$Version", 'ShiftWheel.iss')
    & $Python -m pip freeze | Set-Content 'release\build-dependencies.txt'
    Get-FileHash "release\ShiftWheelSetup-$Version.exe" -Algorithm SHA256 | Format-List | Out-File 'release\SHA256.txt'
    Write-Host "Installer created: release\ShiftWheelSetup-$Version.exe"
} catch {
    Write-Error $_
    exit 1
}
