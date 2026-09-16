@echo off
setlocal enabledelayedexpansion
title Spikeless uninstaller

rem Spikeless makes NO PATH or registry changes, so removing its runtime folder
rem removes every trace it left. What "removing" means depends on where it went:
rem   private root -> the whole folder is Spikeless's, nothing else can be in it
rem   shared root  -> the Python, uv.exe and package cache are shared with any
rem                   other tool set up this way, so there is a real choice, and
rem                   this script asks instead of guessing.
set "SHARED_ROOT=C:\ProgramData\PyApps"
set "PRIVATE_ROOT=C:\Users\Public\Spikeless"
set "LEGACY_ROOT=C:\Users\Public\SpikeRemover"
set "ENVNAME=spikeless"
set "OWNENV=%SHARED_ROOT%\envs\%ENVNAME%"

set "HAVE_PRIVATE="
set "HAVE_SHARED="
if exist "%PRIVATE_ROOT%\uv.exe" set "HAVE_PRIVATE=1"
if exist "%OWNENV%" set "HAVE_SHARED=1"

if not defined HAVE_PRIVATE if not defined HAVE_SHARED if not exist "%LEGACY_ROOT%" (
    echo Nothing to remove - no Spikeless runtime found in:
    echo     %PRIVATE_ROOT%
    echo     %OWNENV%
    pause
    exit /b 0
)

rem --- private install: one folder, only ours. Nothing to weigh up. ---
if defined HAVE_PRIVATE (
    echo This will delete the private Spikeless runtime:
    echo     %PRIVATE_ROOT%
    echo (Python, virtual env, uv.exe and cache - approx 1.8 GB.^)
    echo Nothing outside that folder uses it.
    echo.
    echo Your data files and exports are NOT touched.
    echo.
    set /p CONFIRM="Type Y to remove, anything else to cancel: "
    if /I not "!CONFIRM!"=="Y" goto :cancelled
    call :wipe "%PRIVATE_ROOT%"
    if errorlevel 1 exit /b 1
    call :unshortcut
    echo Done.
    pause
    exit /b 0
)

rem --- shared install: who else is in there? ---
set "OTHERS="
for /d %%D in ("%SHARED_ROOT%\envs\*") do (
    if /I not "%%~nxD"=="%ENVNAME%" set "OTHERS=!OTHERS! %%~nxD"
)

echo Spikeless uses the shared runtime folder:
echo     %SHARED_ROOT%
echo.
echo   [1] Remove Spikeless only  (recommended^)
echo       Deletes %OWNENV%
echo       and the Desktop shortcut. The shared Python, uv.exe and package
echo       cache stay, so anything else using them keeps working.
echo.
echo   [2] Remove EVERYTHING in %SHARED_ROOT%
echo       Also deletes the shared Python, uv.exe and the package cache.
if defined OTHERS (
    echo       WARNING: these other apps are installed in that folder and will
    echo       STOP WORKING until each is launched again:!OTHERS!
) else (
    echo       No other app is installed there right now.
)
echo.
echo Your data files and exports are NOT touched either way.
echo.
set /p CHOICE="Type 1, 2, or anything else to cancel: "

if "!CHOICE!"=="1" (
    call :wipe "%OWNENV%"
    if errorlevel 1 exit /b 1
    call :unshortcut
    echo Done.
    echo.
    echo The shared runtime is still there for your other apps:
    echo     %SHARED_ROOT%
    pause
    exit /b 0
)

if "!CHOICE!"=="2" (
    if defined OTHERS (
        echo.
        echo About to remove the runtime of:!OTHERS!
        set /p CONFIRM="Type ALL to confirm, anything else to cancel: "
        if /I not "!CONFIRM!"=="ALL" goto :cancelled
    )
    call :wipe "%SHARED_ROOT%"
    if errorlevel 1 exit /b 1
    call :unshortcut
    echo Done - the shared runtime folder is gone.
    echo Any other app set up this way will rebuild it on its next launch.
    pause
    exit /b 0
)

:cancelled
echo Cancelled. Nothing was removed.
pause
exit /b 0

rem --------------------------------------------------------------------------
:wipe
if not exist "%~1" exit /b 0
echo Removing %~1 ...
rmdir /s /q "%~1"
if exist "%~1" (
    echo.
    echo Could not fully remove it. Close Spikeless if it is running,
    echo then run this uninstaller again.
    pause
    exit /b 1
)
exit /b 0

:unshortcut
rem the pre-rename SpikeRemover folder is ours whatever the answer was
if exist "%LEGACY_ROOT%" (
    echo Removing the older SpikeRemover install in %LEGACY_ROOT% ...
    rmdir /s /q "%LEGACY_ROOT%"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Spikeless.lnk';" ^
    "if (Test-Path $lnk) { Remove-Item $lnk -Force }"
exit /b 0
