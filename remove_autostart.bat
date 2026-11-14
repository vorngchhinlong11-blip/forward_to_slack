@echo off
REM Stop starting Telegram to Slack Forwarder automatically at Windows login.
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Telegram to Slack Forwarder.lnk"
if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo [OK] Auto-start at login removed.
) else (
    echo Auto-start at login was not set up.
)
pause
