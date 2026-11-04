# Validation status

## Windows build — 2026-11-04

[Build 4](https://github.com/CovalschiPaul/ShiftWheel/actions/runs/41797363438) succeeded for commit d5ff618bb0a888c28a5c1d07e9260d4c0a713b43.

- Windows tests: 157 passed, 9 skipped, 7 Qt deprecation warnings.
- PyInstaller executable built successfully.
- Packaged executable smoke checks passed: Qt initialization, imports, image conversion, PDF write/read and spreadsheet write/read.
- Inno Setup compiled ShiftWheelSetup-3.5.exe successfully.
- Installer, SHA256 record and resolved dependency record uploaded as ShiftWheel-Windows-4.

Fixed during Windows validation: explicit UTF-8 reading in a regression test, Python worker scheduling in the Qt test wait helper, and startup registry command quoting in the installer.

## Scope and remaining checks

The Windows runner installs FFmpeg for media tests. LibreOffice and Tesseract are not installed on that runner; their integrations and the private PowerPoint sample are skipped. Earlier development validation covered real Office conversions. External engines are not bundled into setup.

Compilation and smoke checks do not verify interactive installation, Explorer drag/drop, real monitor scaling, startup, upgrade or uninstall. Test these on a Windows desktop using INSTALLER_README.md before distribution. The installer is unsigned.
