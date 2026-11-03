@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto missing
".venv\Scripts\python.exe" -c "from PySide6.QtWidgets import QApplication; import pynput, PIL, pypdf, pymupdf, openpyxl"
if errorlevel 1 goto failed
start "" ".venv\Scripts\pythonw.exe" "%~dp0shiftwheel.py"
exit /b 0
:missing
echo Run setup_shiftwheel.bat first.
pause
exit /b 1
:failed
echo A required package could not load. Run setup_shiftwheel.bat again.
pause
exit /b 1
