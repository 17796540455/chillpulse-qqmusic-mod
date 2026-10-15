@echo off
rem ===========================================================================
rem  fix_mod.bat -- check / repair the patched data.win and show the result.
rem
rem  The game launcher already does this automatically on every start; this is
rem  the manual version for when you want to see what happened.
rem
rem  ASCII only: a .bat is read as ANSI, non-ASCII text turns into mojibake.
rem ===========================================================================
setlocal
echo.
echo   ChillPulse QQ Music mod - data.win check / repair
echo   ------------------------------------------------
echo.

py -3 "%~dp0mod_guard.py" 2>nul
if errorlevel 9009 (
    python "%~dp0mod_guard.py"
)

echo.
echo   exit code %errorlevel%
echo     0  = already patched, nothing to do
echo     10 = Steam had restored the vanilla file, patch put back
echo     2  = the game was updated - patch NOT applied, ask for a rebuild
echo     3  = data_patched.win missing / could not write
echo     4  = game folder or data.win not found
echo.
pause
