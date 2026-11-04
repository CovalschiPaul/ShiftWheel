# Changelog

## 3.5 — Preview

### App and conversion capabilities

- Paged radial menus, vector action icons, wrapped labels and adaptive result popups.
- Background conversion jobs and explicit failure reports.
- Image, PDF, Office, table, media and file utility actions; see the [format matrix](SUPPORTED_FORMATS.md).
- Copy-only drops, new output filenames and renamed copies to preserve originals.
- Tray file picker, configurable trigger/shortcut, global Escape and local engine diagnostics.

### Windows packaging

- Per-user Inno Setup installer with Start menu, optional desktop shortcut and optional startup.
- PyInstaller bundle including Python and app libraries.
- Windows CI with regression tests, packaged smoke checks, checksums and dependency records.
- Fixed UTF-8 source reading in a test, worker-test scheduling and quoting of the installer startup command.

### Validation

Build #4 on 2026-11-04 passed 157 tests with 9 skipped and produced the unsigned installer. Hands-on Windows acceptance testing remains pending. See [VALIDATION.md](VALIDATION.md).

## Repository presentation

Added setup and usage documentation, troubleshooting, issue templates, contribution guidance and an explicit roadmap. This documentation update does not change conversion behavior.
