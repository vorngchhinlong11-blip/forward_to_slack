@echo off
setlocal enabledelayedexpansion
REM Always run from the project folder (also when started from the Startup folder)
cd /d "%~dp0"
chcp 65001 >nul 2>&1

echo =========================================
echo   Telegram to Slack Forwarder
echo =========================================
echo.

REM Check if virtual environment exists
if not exist venv (
    echo [!] Virtual environment not found
    echo Starting setup...
    echo.

    REM Check Python version
    echo Checking Python version...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python is not installed or not in PATH
        echo Please install Python 3.9 or higher from https://www.python.org/
        pause
        exit /b 1
    )

    python --version
    echo.

    REM Create virtual environment
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
    echo.

    REM Activate virtual environment
    echo Activating virtual environment...
    call venv\Scripts\activate.bat

    REM Install dependencies
    echo Installing dependencies...
    pip install --upgrade pip
    pip install -r requirements.txt

    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )

    echo.
    echo =========================================
    echo   Setup completed!
    echo =========================================
    echo.
) else (
    REM Activate virtual environment
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
    echo [OK] Virtual environment activated
    echo.
)

REM Start application - and restart it if it closes unexpectedly
REM (crash, killed for low memory...). Closing the window yourself ends it.
set RESTART_FLAG=
:run_app
echo Starting application...
python gui.py %RESTART_FLAG%
set EXIT_CODE=%errorlevel%
if "%EXIT_CODE%"=="0" goto app_closed
if "%EXIT_CODE%"=="10" goto app_closed
echo.
echo WARNING: The app closed unexpectedly (exit code %EXIT_CODE%).
echo     Restarting in 15 seconds... close this window to cancel.
timeout /t 15 /nobreak >nul 2>&1 || ping -n 16 127.0.0.1 >nul
set RESTART_FLAG=--restarted
goto run_app

:app_closed

endlocal
