@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m pip install pytest -r requirements-optional.txt
if errorlevel 1 goto fail
set QT_QPA_PLATFORM=offscreen
".venv\Scripts\python.exe" -m pytest -q test_shiftwheel.py test_formats.py
set SW_TEST_EXIT=%ERRORLEVEL%
pause
exit /b %SW_TEST_EXIT%
:missing
echo Run setup_shiftwheel.bat first.
pause
exit /b 1
:fail
echo Test dependencies could not be installed.
pause
exit /b 1
