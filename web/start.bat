@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   sol_trade site - local server
echo ============================================
echo.
echo On this PC:
echo     http://localhost:8080
echo.
echo On your phone (must be on the same WiFi):
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    set ip=%%a
    set ip=!ip: =!
    echo     http://!ip!:8080
)
echo.
echo This is local-network only -- not reachable from
echo the public internet. Press Ctrl+C to stop.
echo ============================================
echo.

python -m http.server 8080
pause
