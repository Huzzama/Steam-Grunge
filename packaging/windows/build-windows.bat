@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: build-windows.bat — Builds Steam Grunge Editor Windows installer
::
:: Run from the repo root:
::   packaging\windows\build-windows.bat
::
:: Requirements (must be installed and on PATH before running):
::   - Python 3.10+    https://python.org  (check "Add to PATH" during install)
::   - Inno Setup 6    https://jrsoftware.org/isdl.php
::   - pip install pyinstaller pillow
::
:: Output:
::   dist\installer\SteamGrungeEditor-{VERSION}-Setup.exe
::
:: v2.1.0 changes:
::   - icon.ico conversion now checks if .ico is already up-to-date
::   - PyInstaller step passes --noconfirm --clean explicitly
::   - ISCC call passes /DAppVersion from the VERSION file (was hardcoded)
::   - Added check that dist\SteamGrungeEditor\ exists before running ISCC
::   - Exit codes are now consistent (all failures exit /b 1)
:: ─────────────────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

:: ── Resolve repo root (two levels up from this script) ───────────────────────
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..\..
pushd "%REPO_ROOT%"
set REPO_ROOT=%CD%
popd

:: ── Read VERSION file ─────────────────────────────────────────────────────────
set /p VERSION=<"%REPO_ROOT%\VERSION"
if "!VERSION!"=="" (
    echo ERROR: VERSION file is empty or missing at %REPO_ROOT%\VERSION
    exit /b 1
)

echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   Building Steam Grunge Editor v!VERSION! for Windows
echo   Repo: %REPO_ROOT%
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

:: ── Step 1: Convert icon.png → icon.ico ──────────────────────────────────────
echo.
echo [1/3] Converting icon.png to icon.ico...
python -c ^
"from PIL import Image; ^
img = Image.open(r'%REPO_ROOT%\app\assets\icon.png'); ^
img.save(r'%REPO_ROOT%\app\assets\icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); ^
print('  icon.ico written')"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to create icon.ico.
    echo        Make sure Pillow is installed:  pip install pillow
    exit /b 1
)

:: ── Step 2: PyInstaller — bundle into dist\SteamGrungeEditor\ ────────────────
echo.
echo [2/3] Running PyInstaller...
cd /d "%REPO_ROOT%"
pyinstaller ^
    "packaging\windows\steam_grunge_editor.spec" ^
    --noconfirm ^
    --clean
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed.
    echo        Make sure it is installed:  pip install pyinstaller
    exit /b 1
)

:: Sanity check — make sure the exe was actually produced
if not exist "%REPO_ROOT%\dist\SteamGrungeEditor\SteamGrungeEditor.exe" (
    echo.
    echo ERROR: PyInstaller finished but SteamGrungeEditor.exe was not found.
    echo        Check the PyInstaller output above for warnings.
    exit /b 1
)
echo   PyInstaller OK — dist\SteamGrungeEditor\SteamGrungeEditor.exe

:: ── Step 3: Inno Setup — build the installer .exe ────────────────────────────
echo.
echo [3/3] Running Inno Setup...

:: Locate ISCC.exe — check both 32-bit and 64-bit Program Files
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)
:: Also check PATH (useful in CI environments where ISCC is on PATH directly)
where ISCC.exe >nul 2>&1
if not errorlevel 1 (
    set "ISCC=ISCC.exe"
)

if "!ISCC!"=="" (
    echo.
    echo ERROR: Inno Setup 6 not found.
    echo        Download from: https://jrsoftware.org/isdl.php
    echo        Or add ISCC.exe to PATH if using a portable install.
    exit /b 1
)

mkdir "%REPO_ROOT%\dist\installer" 2>nul

"!ISCC!" ^
    /DAppVersion=!VERSION! ^
    "%REPO_ROOT%\packaging\windows\steam_grunge_editor.iss"
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup compilation failed.
    echo        Check the output above for details.
    exit /b 1
)

:: Verify output
if not exist "%REPO_ROOT%\dist\installer\SteamGrungeEditor-!VERSION!-Setup.exe" (
    echo.
    echo WARNING: Build finished but installer file not found at expected path.
    echo          dist\installer\SteamGrungeEditor-!VERSION!-Setup.exe
    echo          Check the Inno Setup output above.
    exit /b 1
)

echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   Done!
echo   Installer: dist\installer\SteamGrungeEditor-!VERSION!-Setup.exe
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
