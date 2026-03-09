@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: build-windows.bat — Builds Steam Grunge Editor Windows installer
::
:: Run from the repo root:
::   packaging\windows\build-windows.bat
::
:: Requirements (install these first):
::   - Python 3.10+ (from python.org, add to PATH)
::   - Inno Setup 6 (from https://jrsoftware.org/isdl.php)
::   - pip install pyinstaller pillow
::
:: Output:
::   dist\installer\SteamGrungeEditor-1.0.0-Setup.exe
:: ─────────────────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

:: Resolve repo root (two levels up from this script)
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..\..
pushd %REPO_ROOT%
set REPO_ROOT=%CD%
popd

:: Read version
set /p VERSION=<%REPO_ROOT%\VERSION
if "%VERSION%"=="" set VERSION=1.0.0

echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   Building Steam Grunge Editor v%VERSION% for Windows
echo   Repo: %REPO_ROOT%
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:: ── Step 1: Convert icon.png to icon.ico ──────────────────────────────────────
echo [1/3] Converting icon.png to icon.ico...
python -c "
from PIL import Image
import os
img = Image.open(r'%REPO_ROOT%\app\assets\icon.png')
img.save(r'%REPO_ROOT%\app\assets\icon.ico', format='ICO',
         sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon.ico created')
"
if errorlevel 1 (
    echo ERROR: Failed to create icon.ico. Make sure Pillow is installed.
    echo        pip install pillow
    exit /b 1
)

:: ── Step 2: PyInstaller — bundle app into dist\SteamGrungeEditor\ ─────────────
echo [2/3] Running PyInstaller...
cd /d "%REPO_ROOT%"
pyinstaller packaging\windows\steam_grunge_editor.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller failed.
    echo        Make sure it is installed: pip install pyinstaller
    exit /b 1
)
echo PyInstaller done. Output: dist\SteamGrungeEditor\

:: ── Step 3: Inno Setup — build the installer ──────────────────────────────────
echo [3/3] Running Inno Setup...

:: Common Inno Setup install locations
set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if %ISCC%=="" (
    echo ERROR: Inno Setup not found.
    echo        Download from: https://jrsoftware.org/isdl.php
    exit /b 1
)

mkdir "%REPO_ROOT%\dist\installer" 2>nul
%ISCC% /DAppVersion=%VERSION% "%REPO_ROOT%\packaging\windows\steam_grunge_editor.iss"
if errorlevel 1 (
    echo ERROR: Inno Setup compilation failed.
    exit /b 1
)

echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   Done!
echo   Installer: dist\installer\SteamGrungeEditor-%VERSION%-Setup.exe
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
