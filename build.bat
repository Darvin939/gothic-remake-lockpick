@echo off

echo Build Gothic1 Remake Lockpicker...
echo.

set /p VERSION=<version.txt

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller --onefile --add-data "templates;templates" --hidden-import=pyautogui --hidden-import=pynput --name "Gothic1 Remake Lockpicker v%VERSION%" app.py