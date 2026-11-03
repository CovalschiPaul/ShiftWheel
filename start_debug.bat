@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" "%~dp0shiftwheel.py"
pause
exit /b 0
:missing
echo Run setup_shiftwheel.bat first.
pause
exit /b 1
