@echo off
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building HDRSwitcher.exe...
pyinstaller --noconsole --onefile --name HDRSwitcher --hidden-import pystray._win32 main.py

echo.
if exist dist\HDRSwitcher.exe (
    echo Build successful: dist\HDRSwitcher.exe
) else (
    echo Build FAILED.
)
pause
