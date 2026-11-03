# Validation status

The v3.5 app passed 166 distinct checks in the development environment, including real Office conversions. This repository keeps that application code unchanged.

Repository changes: Windows GitHub Actions workflow, CI Python selection, JUnit report output, dynamic installer version, Git exclusions and documentation. Workflow structure and repository contents are checked locally. The Windows workflow and installer have NOT been executed here.

The Windows runner installs FFmpeg for media tests. LibreOffice and Tesseract integrations run only if present; the personal PowerPoint sample is excluded. Missing engines must not be mistaken for complete external-engine coverage.

Before distribution: run the workflow, download and inspect its diagnostics, test setup on Windows without Python, exercise Explorer drag/drop, then test startup, upgrade and uninstall. See INSTALLER_README.md for the detailed acceptance checklist.
