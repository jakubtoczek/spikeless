@echo off
setlocal
title Spikeless uninstaller

rem Spikeless.bat installs everything self-contained under this one folder
rem (uv.exe, private Python, cache, venv). It makes NO PATH or registry changes,
rem so removing this folder removes every trace it left on the PC.
set "PUBLIC_ROOT=C:\Users\Public\Spikeless"
set "LEGACY_ROOT=C:\Users\Public\SpikeRemover"

echo This will delete the Spikeless runtime:
echo     %PUBLIC_ROOT%
if exist "%LEGACY_ROOT%" echo     %LEGACY_ROOT%   (older SpikeRemover install)
echo (private Python, virtual env, uv.exe and cache — approx a few hundred MB).
echo.
echo Your project files, data and exports are NOT touched.
echo.

if not exist "%PUBLIC_ROOT%" if not exist "%LEGACY_ROOT%" (
    echo Nothing to remove — no Spikeless runtime folder exists.
    pause
    exit /b 0
)

set /p CONFIRM="Type Y to remove, anything else to cancel: "
if /I not "%CONFIRM%"=="Y" (
    echo Cancelled. Nothing was removed.
    pause
    exit /b 0
)

echo Removing runtime folders ...
if exist "%PUBLIC_ROOT%" rmdir /s /q "%PUBLIC_ROOT%"
if exist "%LEGACY_ROOT%" rmdir /s /q "%LEGACY_ROOT%"

if exist "%PUBLIC_ROOT%" (
    echo.
    echo Could not fully remove the folder. Close Spikeless if it is running,
    echo then run this uninstaller again.
    pause
    exit /b 1
)

echo Done. Spikeless left no other trace on this PC.
pause
exit /b 0
