@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m pip install -r requirements-optional.txt
if errorlevel 1 goto fail
echo.
echo Python extras installed. For OCR, also install the Tesseract program.
echo For video and audio, install FFmpeg and add its bin folder to PATH.
echo Restart ShiftWheel after installing either program.
pause
exit /b 0
:missing
echo Run setup_shiftwheel.bat first.
pause
exit /b 1
:fail
echo The optional install failed. Read the error above.
pause
exit /b 1
