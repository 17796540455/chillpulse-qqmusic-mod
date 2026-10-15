@echo off
rem ---------------------------------------------------------------------------
rem  start_bridge.bat -- ChillPulse <-> QQ Music bridge
rem
rem  Serves a small JSON API on http://127.0.0.1:38610 that the in-game
rem  QQ Music panel talks to.  Keep this window open while you play.
rem
rem  Edit GAME_DIR below if ChillPulse is installed elsewhere.
rem ---------------------------------------------------------------------------
setlocal
set "GAME_DIR=E:\steam\steam\steamapps\common\ChillPulse"
set "PORT=38610"
set "HERE=%~dp0"
set "FALLBACK=C:\Users\wmcyh\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

title qqbridge - QQ Music bridge for ChillPulse
echo [qqbridge] game dir : %GAME_DIR%
echo [qqbridge] port     : %PORT%
echo [qqbridge] log file : %HERE%qqbridge.log
echo.

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (
    echo [qqbridge] interpreter: py -3
    py -3 "%HERE%qqbridge.py" --port %PORT% --game-dir "%GAME_DIR%" --cache-mb 1024 --quality 128
    goto :done
)

if exist "%FALLBACK%" (
    echo [qqbridge] interpreter: bundled python
    "%FALLBACK%" "%HERE%qqbridge.py" --port %PORT% --game-dir "%GAME_DIR%" --cache-mb 1024 --quality 128
    goto :done
)

echo [qqbridge] ERROR: no working Python 3 interpreter found.
echo             Install Python 3 from https://www.python.org/downloads/ and retry.
pause
exit /b 1

:done
echo.
echo [qqbridge] stopped (exit code %ERRORLEVEL%).
pause
