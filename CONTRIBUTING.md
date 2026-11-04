# Contributing

ShiftWheel is a public source preview. Before submitting substantial code, read [LICENSING.md](LICENSING.md): no project license has been selected. Bug reports and reproducible examples are welcome.

## Report a problem

Use the issue templates. Include the app/Windows version, source and target formats, steps, expected behavior and actual error. Share only synthetic or redacted samples. For sensitive reports, see [SECURITY.md](SECURITY.md).

## Development

Windows is the target platform. The installer CI uses Python 3.12 x64.

```bat
setup_shiftwheel.bat
install_optional.bat
.venv\Scripts\python.exe -m pip install pytest pytest-timeout
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest -q --timeout=240 --timeout-method=thread test_shiftwheel.py test_formats.py test_packaging.py
```

External-engine tests need FFmpeg, LibreOffice or Tesseract; absent engines can cause skips. A passing offscreen test suite does not establish that Windows hooks or installation work.

## Pull requests

Keep each change focused and explain the user-visible outcome. Include relevant tests and update the format matrix when conversions change. Preserve originals, avoid overwrites, keep slow work off the UI thread and report actionable failures. Do not commit personal samples, credentials, generated binaries, logs or local environments.

Check the Windows installer workflow. For UI or installer changes, record the Windows desktop checks actually performed and explicitly list any checks still pending.

## Build layout

- `shiftwheel.py`: tray UI, wheel and conversion operations.
- `test_shiftwheel.py`, `test_formats.py`, `test_packaging.py`: regression and packaging checks.
- `package_check.py`: smoke checks executed inside the packaged app.
- `ShiftWheel.spec`: PyInstaller bundle.
- `ShiftWheel.iss`: Inno Setup installer.
- `build_windows.ps1`: test, package, smoke-check and installer pipeline.

See [INSTALLER_README.md](INSTALLER_README.md) for local packaging and [VALIDATION.md](VALIDATION.md) for the current evidence.
