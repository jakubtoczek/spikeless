@echo off
setlocal
title SpikeRemover uninstaller

rem SpikeRemover.bat installs everything self-contained under this one folder
rem (uv.exe, private Python, cache, venv). It makes NO PATH or registry changes,
rem so removing this folder removes every trace it left on the PC.
set "PUBLIC_ROOT=C:\Users\Public\SpikeRemover"

echo This will delete the SpikeRemover runtime:
echo     %PUBLIC_ROOT%
echo (private Python, virtual env, uv.exe and cache — approx a few hundred MB).
echo.
echo Your project files, data and exports are NOT touched.
echo.

if not exist "%PUBLIC_ROOT%" (
    echo Nothing to remove — "%PUBLIC_ROOT%" does not exist.
    pause
    exit /b 0
)

set /p CONFIRM="Type Y to remove, anything else to cancel: "
if /I not "%CONFIRM%"=="Y" (
    echo Cancelled. Nothing was removed.
    pause
    exit /b 0
)

echo Removing %PUBLIC_ROOT% ...
rmdir /s /q "%PUBLIC_ROOT%"

if exist "%PUBLIC_ROOT%" (
    echo.
    echo Could not fully remove the folder. Close SpikeRemover if it is running,
    echo then run this uninstaller again.
    pause
    exit /b 1
)

echo Done. SpikeRemover left no other trace on this PC.
pause
exit /b 0
