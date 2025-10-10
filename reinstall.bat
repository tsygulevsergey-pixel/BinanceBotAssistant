cd /d %~dp0
if exist venv rmdir /s /q venv
echo [INFO] Creating fresh virtual environment...
python -m venv venv
echo [INFO] Installing dependencies...
venv\Scripts\pip.exe install -r requirements.txt
echo.
echo [OK] Ready! Now run start.bat
pause
