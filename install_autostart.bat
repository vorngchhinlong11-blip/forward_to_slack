@echo off
REM Start Telegram to Slack Forwarder automatically when you log in to Windows.
REM Undo with remove_autostart.bat.
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Telegram to Slack Forwarder.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SHORTCUT);" ^
  "$s.TargetPath = '%~dp0run_windows.bat';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.WindowStyle = 7;" ^
  "$s.Description = 'Telegram to Slack Forwarder';" ^
  "$s.Save()"
if exist "%SHORTCUT%" (
    echo [OK] The forwarder will start automatically when you log in to Windows.
    echo      If forwarding was on, it resumes by itself.
) else (
    echo [ERROR] Could not create the startup shortcut.
)
pause
