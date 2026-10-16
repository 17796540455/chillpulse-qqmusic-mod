@echo off
rem ===========================================================================
rem  ChillPulse QQ Music Mod - double-click this to install.
rem  It only calls install.ps1 (PowerShell) so the window stays open and you
rem  can read what happened.
rem ===========================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "INSTALL_RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %INSTALL_RESULT%
