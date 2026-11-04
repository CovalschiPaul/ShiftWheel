# ShiftWheel 3.5 installer project

Status: the Windows CI build produced an unsigned installer and passed packaged smoke checks on 2026-11-04. Hands-on Windows installation and desktop acceptance checks remain pending. See [VALIDATION.md](VALIDATION.md).

## Build once on Windows

Use Windows 10/11 x64. Install Python 3.12 x64 from python.org and Inno Setup 6 from https://jrsoftware.org/isinfo.php. Extract this project into a writable folder and double-click BuildInstaller.cmd. Internet access is needed for Python build dependencies. This installs build dependencies into a local .build-venv, runs tests, packages the app, runs the packaged conversion smoke test, and compiles the installer. Any failed stage stops the build.

Successful output: release/ShiftWheelSetup-3.5.exe, SHA256.txt, build-dependencies.txt. Keep the dependency record with each release. Dependency ranges are not a reproducible lockfile; release builds should retain their resolved versions.

## What users get

Run the generated setup, install for the current user without administrator access, then launch ShiftWheel from Start. Python and Python libraries are included. Desktop shortcut and sign-in startup are optional. The app lives in the tray. Upgrades use the same application identity and location; setup asks users to quit a running instance. Uninstall keeps preferences in %APPDATA%/ShiftWheel and removes the matching startup entry.

The installer currently includes the app plus HEIF and OCR Python integration. It does NOT include LibreOffice, FFmpeg, or the Tesseract executable/language data. Office conversion requires LibreOffice; video/audio requires FFmpeg on PATH; OCR requires Tesseract. Existing tray diagnostics explain missing tools. See SUPPORTED_FORMATS.md. A full installer bundling these engines is a separate remaining task.

## Required Windows release acceptance

Use a clean Windows account or VM with no Python installed. Verify install and launch, Explorer drag/drop, high-DPI and multiple monitors, Escape, tray dialogs, progress and error handling. Convert image/PDF/spreadsheet fixtures. Test absent-engine errors, then install the external engines and test PPTX to PDF, video/audio and OCR. Verify a path with spaces and non-ASCII text. Enable startup, sign out/in, upgrade with preferences retained, then uninstall and confirm shortcuts and startup entry are gone while original files and preferences remain. Installer upgrade/uninstall must request app exit rather than terminating active conversion.

The build smoke test verifies Qt initialization, image conversion, PDF writing/reading, spreadsheet writing/reading and Python imports. It does not verify Explorer hooks, installer behavior, external conversion engines or a full visual review.

## Distribution

This build is unsigned. Public distribution still needs a signing/release decision and review of dependency redistribution terms, including PyMuPDF and Qt. Do not treat the generated binary as a publication-ready release until these and the Windows acceptance checks are complete. The original orange ring icon is reused; the first visual refinement is included, with vector icons, wrapped labels, stronger hover contrast and adaptive result popups.

The test runner has a 240-second per-test limit so a stuck test cannot block the installer build indefinitely. Office conversion timing and exit codes are recorded in the app debug log.
