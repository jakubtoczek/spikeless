@echo off
setlocal
title Spikeless launcher

rem --- everything self-contained under C:\Users\Public (no admin, no PATH changes) ---
set "PUBLIC_ROOT=C:\Users\Public\Spikeless"
set "UV=%PUBLIC_ROOT%\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%PUBLIC_ROOT%\python"
set "UV_CACHE_DIR=%PUBLIC_ROOT%\cache"
set "UV_PROJECT_ENVIRONMENT=%PUBLIC_ROOT%\venv"
set "PROJECT=%~dp0"
set "PYTHONPATH=%~dp0src"
set "ICON=%~dp0src\spikeless\assets\spikeless.ico"

rem --- one-time: put a Spikeless shortcut (with the app icon) on the Desktop ---
set "LNK=%USERPROFILE%\Desktop\Spikeless.lnk"
if not exist "%LNK%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
        "$s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0';" ^
        "$s.IconLocation='%ICON%'; $s.WindowStyle=7;" ^
        "$s.Description='Spikeless - radio-HPLC plotting and spike removal'; $s.Save()"
)

rem --- one-time: fetch the uv binary ---
if not exist "%UV%" (
    echo First run: downloading uv ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "New-Item -ItemType Directory -Force -Path '%PUBLIC_ROOT%' | Out-Null;" ^
        "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile '%PUBLIC_ROOT%\uv.zip';" ^
        "Expand-Archive -Force '%PUBLIC_ROOT%\uv.zip' '%PUBLIC_ROOT%';" ^
        "Remove-Item '%PUBLIC_ROOT%\uv.zip'"
    if not exist "%UV%" (
        echo Failed to download uv. Check your internet connection.
        pause
        exit /b 1
    )
)

rem --- install Python + dependencies into the Public venv (fast no-op once done) ---
echo Preparing environment ...
"%UV%" sync --project "%PROJECT%." --python 3.12
if errorlevel 1 (
    echo Environment setup failed.
    pause
    exit /b 1
)

rem --- launch the GUI with pythonw (no console window) and exit ---
start "" "%UV_PROJECT_ENVIRONMENT%\Scripts\pythonw.exe" -m spikeless
exit /b 0
