@echo off
rem ===========================================================================
rem  reinstall_mod.bat -- put the patched data.win back
rem
rem  Steam restores data.win to the vanilla one whenever you use
rem  "Verify integrity of game files" (or when the game updates), which removes
rem  the QQ Music tab.  Double-click this file to put the mod back.
rem
rem  ASCII only on purpose: a .bat is read as ANSI, so non-ASCII text can turn
rem  into mojibake in the console.
rem ===========================================================================
setlocal
set "MODDIR=%~dp0"
set "GAME=%MODDIR%.."
set "SRC=%MODDIR%data_patched.win"
set "DST=%GAME%\data.win"
set "BAK=%GAME%\data.win.qqmod-backup"

echo.
echo   ChillPulse QQ Music mod - reinstall
echo   ----------------------------------
echo   game folder : %GAME%
echo.

if not exist "%SRC%" (
    echo   [ERROR] prebuilt patch not found:
    echo           %SRC%
    echo   Ask the mod author to rebuild it.
    echo.
    pause
    exit /b 1
)

if not exist "%DST%" (
    echo   [ERROR] data.win not found in the game folder.
    echo.
    pause
    exit /b 1
)

rem --- keep one pristine copy of the original, never overwrite it -------------
if not exist "%BAK%" (
    echo   backing up the original data.win ...
    copy /y "%DST%" "%BAK%" >nul
    if errorlevel 1 (
        echo   [ERROR] could not create the backup. Is the game running?
        echo.
        pause
        exit /b 1
    )
)

rem --- is it already patched? -------------------------------------------------
fc /b "%SRC%" "%DST%" >nul 2>nul
if not errorlevel 1 (
    echo   already patched - nothing to do.
    echo.
    pause
    exit /b 0
)

echo   installing the patched data.win ...
copy /y "%SRC%" "%DST%" >nul
if errorlevel 1 (
    echo   [ERROR] copy failed. Close the game ^(and Steam^) and try again.
    echo.
    pause
    exit /b 1
)

echo.
echo   Done.  Start the game and look for the "QQ Music" tab in the music panel.
echo.
pause
