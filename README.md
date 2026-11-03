# ShiftWheel

A Windows tray app that opens a radial action menu when you hold Shift and drag files in Explorer. Convert images, PDFs, Office documents, tables, audio and video while keeping the originals.

![ShiftWheel wheel](assets/wheel-preview.png)

## Build an installer on GitHub

1. Create a repository named `ShiftWheel` (private is a reasonable starting point).
2. Put **the contents of this folder** at the repository root, including `.github/workflows/build-windows.yml`. Do not upload the ZIP itself as the project.
3. On GitHub, open **Actions → Build Windows installer → Run workflow** on `main`.
4. Wait for the job to finish. Open the completed run and download **ShiftWheel-Windows-…** under Artifacts.
5. Extract that download and run `ShiftWheelSetup-3.5.exe` (the name follows the app version).

The workflow also runs after code pushes and pull requests to `main`. It creates downloadable build artifacts; it does not publish a GitHub Release. No custom secrets are required. GitHub Actions usage is subject to your account's limits.

If the job fails, download **build-diagnostics-…** and inspect the failed step. The workflow has not yet been executed for this repository; a successful first Windows run is still required.

## Upload with Git

From this folder, with Git installed and authenticated to your GitHub account:

```sh
git init -b main
git add .
git commit -m "Add ShiftWheel app and Windows installer workflow"
git remote add origin https://github.com/YOUR_USERNAME/ShiftWheel.git
git push -u origin main
```

Create an empty repository first (without an initial README). GitHub Desktop is also suitable and includes the hidden workflow folder when adding this directory as a repository.

## What is included

- Python/Qt application and regression tests.
- PyInstaller packaging and an Inno Setup per-user installer.
- Start menu shortcut, optional desktop shortcut and optional startup at sign-in.
- Windows CI tests, packaged smoke checks, checksum and build dependency record.

The installed app includes Python and its app libraries. **LibreOffice, FFmpeg and Tesseract executables are still separate dependencies.** FFmpeg is installed on the CI runner for tests, not bundled into the installer. Office and OCR integration tests skip when their external engines are unavailable. No personal PowerPoint sample is included.

See [supported formats](SUPPORTED_FORMATS.md), [local installer build](INSTALLER_README.md), and [validation status](VALIDATION.md).

## Run from source

On Windows, run `setup_shiftwheel.bat`, then `start_shiftwheel.bat`. Look for the orange icon in the notification area. On first use, test with copies of files and inspect the outputs.

## Distribution status

This is an unsigned development build. Explorer behavior, clean installation, upgrades and uninstall require Windows acceptance testing. No open-source license has been selected for this repository. Before public distribution, choose the project's license and review included dependency terms (including PyMuPDF and Qt).
