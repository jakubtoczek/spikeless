@echo off
setlocal
title Spikeless uninstaller

rem Spikeless.bat makes NO PATH or registry changes, so removing its runtime
rem folder removes every trace it left. Two cases:
rem   private root -> the whole folder is Spikeless's, delete it
rem   shared root  -> other apps use the Python and cache, delete only our venv
set "SHARED_ROOT=C:\ProgramData\PyApps"
set "PRIVATE_ROOT=C:\Users\Public\Spikeless"
set "LEGACY_ROOT=C:\Users\Public\SpikeRemover"

set "MODE="
rem (parenthesised: without them the second set on the line runs unconditionally)
if exist "%SHARED_ROOT%\envs\spikeless" ( set "MODE=shared"  & set "TARGET=%SHARED_ROOT%\envs\spikeless" )
if exist "%PRIVATE_ROOT%\uv.exe"        ( set "MODE=private" & set "TARGET=%PRIVATE_ROOT%" )

if not defined MODE if not exist "%LEGACY_ROOT%" (
    echo Nothing to remove - no Spikeless runtime found in:
    echo     %PRIVATE_ROOT%
    echo     %SHARED_ROOT%\envs\spikeless
    pause
    exit /b 0
)

echo This will delete:
if defined TARGET echo     %TARGET%
if exist "%LEGACY_ROOT%" echo     %LEGACY_ROOT%   (older SpikeRemover install)
if "%MODE%"=="private" echo (private Python, virtual env, uv.exe and cache - approx 1.8 GB).
if "%MODE%"=="shared"  echo (only Spikeless's virtual env - the shared Python, uv.exe and
if "%MODE%"=="shared"  echo  cache in %SHARED_ROOT% stay, because other apps use them.)
echo.
echo Your project files, data and exports are NOT touched.
echo.

set /p CONFIRM="Type Y to remove, anything else to cancel: "
if /I not "%CONFIRM%"=="Y" (
    echo Cancelled. Nothing was removed.
    pause
    exit /b 0
)

echo Removing ...
if defined TARGET if exist "%TARGET%" rmdir /s /q "%TARGET%"
if exist "%LEGACY_ROOT%" rmdir /s /q "%LEGACY_ROOT%"

rem also remove the Desktop shortcut if present
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Spikeless.lnk';" ^
    "if (Test-Path $lnk) { Remove-Item $lnk -Force }"

if defined TARGET if exist "%TARGET%" (
    echo.
    echo Could not fully remove it. Close Spikeless if it is running,
    echo then run this uninstaller again.
    pause
    exit /b 1
)

echo Done.
if "%MODE%"=="shared" (
    echo.
    echo The shared runtime is still there for your other apps:
    echo     %SHARED_ROOT%
    echo If Spikeless was the last one using it, delete that folder by hand.
)
pause
exit /b 0
