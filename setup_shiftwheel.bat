@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto fail
goto install
:use_python
python -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "from PySide6.QtWidgets import QApplication; import pynput, PIL, pypdf, pymupdf, openpyxl"
if errorlevel 1 goto fail
echo.
echo Setup complete. Double-click start_shiftwheel.bat.
echo For HEIC and OCR, also run install_optional.bat.
pause
exit /b 0
:fail
echo.
echo Setup failed. Read the error above.
echo Install 64-bit Python 3.12 or 3.13, then run this file again.
echo Internet access is needed to download packages.
pause
exit /b 1
