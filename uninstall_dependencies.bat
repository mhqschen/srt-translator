@echo off
chcp 65001 >nul
echo ========================================
echo   SRT Dependencies Uninstaller v1.0
echo ========================================
echo This script will remove SRT tool dependencies
echo.

rem Set Python encoding
set PYTHONIOENCODING=utf-8

rem Check Python installation
echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python not found or not in PATH
    echo Cannot uninstall dependencies without Python
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo OK: Python found
python --version
echo.

rem Check pip availability
echo Checking pip availability...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: pip not found, trying python -m pip
    python -m pip --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo ERROR: pip not available
        echo Cannot uninstall dependencies without pip
        echo.
        echo Press any key to exit...
        pause >nul
        exit /b 1
    )
    echo OK: pip found (using python -m pip)
    set PIP_CMD=python -m pip
) else (
    echo OK: pip ready
    set PIP_CMD=pip
)

echo.
echo ========================================
echo     Checking Current Dependencies
echo ========================================
echo.

rem Check which packages are currently installed
echo Checking requests package...
python -c "import requests; print('requests ' + requests.__version__ + ' is installed')" 2>nul
if %errorlevel% neq 0 (
    echo requests: NOT INSTALLED
    set REQUESTS_INSTALLED=false
) else (
    echo requests: INSTALLED
    set REQUESTS_INSTALLED=true
)

echo Checking colorama package...
python -c "import colorama; print('colorama ' + colorama.__version__ + ' is installed')" 2>nul
if %errorlevel% neq 0 (
    echo colorama: NOT INSTALLED
    set COLORAMA_INSTALLED=false
) else (
    echo colorama: INSTALLED
    set COLORAMA_INSTALLED=true
)

echo.

rem Check if any packages need to be uninstalled
if "%REQUESTS_INSTALLED%"=="false" if "%COLORAMA_INSTALLED%"=="false" (
    echo ========================================
    echo    No Dependencies Found to Remove
    echo ========================================
    echo.
    echo Both requests and colorama are already not installed.
    echo Nothing to uninstall.
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 0
)

echo ========================================
echo        Uninstalling Dependencies
echo ========================================
echo.

rem Confirm uninstallation
echo The following packages will be uninstalled:
if "%REQUESTS_INSTALLED%"=="true" echo   - requests
if "%COLORAMA_INSTALLED%"=="true" echo   - colorama
echo.
echo This action cannot be undone (but you can reinstall later).
echo.
choice /C YN /M "Do you want to continue"
if %errorlevel% neq 1 (
    echo.
    echo Uninstallation cancelled by user.
    echo.
    timeout /t 2 >nul
    exit /b 0
)

echo.
echo Starting uninstallation...
echo.

rem Uninstall requests if installed
if "%REQUESTS_INSTALLED%"=="true" (
    echo Uninstalling requests...
    echo Running: %PIP_CMD% uninstall requests -y
    %PIP_CMD% uninstall requests -y
    if %errorlevel% neq 0 (
        echo WARNING: Failed to uninstall requests (exit code: %errorlevel%)
        echo Trying with --break-system-packages flag...
        %PIP_CMD% uninstall requests -y --break-system-packages
        if %errorlevel% neq 0 (
            echo ERROR: Still failed to uninstall requests
        ) else (
            echo OK: requests uninstalled with --break-system-packages
        )
    ) else (
        echo OK: requests uninstalled successfully
    )
    echo.
)

rem Uninstall colorama if installed
if "%COLORAMA_INSTALLED%"=="true" (
    echo Uninstalling colorama...
    echo Running: %PIP_CMD% uninstall colorama -y
    %PIP_CMD% uninstall colorama -y
    if %errorlevel% neq 0 (
        echo WARNING: Failed to uninstall colorama (exit code: %errorlevel%)
        echo Trying with --break-system-packages flag...
        %PIP_CMD% uninstall colorama -y --break-system-packages
        if %errorlevel% neq 0 (
            echo ERROR: Still failed to uninstall colorama
        ) else (
            echo OK: colorama uninstalled with --break-system-packages
        )
    ) else (
        echo OK: colorama uninstalled successfully
    )
    echo.
)

echo ========================================
echo       Verifying Uninstallation
echo ========================================
echo.

rem Verify packages are uninstalled
echo Verifying requests removal...
python -c "import requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo OK: requests successfully removed
) else (
    echo WARNING: requests still appears to be installed
)

echo Verifying colorama removal...
python -c "import colorama" >nul 2>&1
if %errorlevel% neq 0 (
    echo OK: colorama successfully removed
) else (
    echo WARNING: colorama still appears to be installed
)

echo.
echo ========================================
echo        Uninstallation Complete
echo ========================================
echo.

rem Final verification
python -c "import requests, colorama" >nul 2>&1
if %errorlevel% neq 0 (
    echo SUCCESS: All SRT tool dependencies have been removed
    echo.
    echo You can now test the installation process by running:
    echo   run_gui.bat
    echo.
    echo The dependencies will be automatically reinstalled when needed.
) else (
    echo WARNING: Some dependencies may still be installed
    echo Please check manually if needed:
    echo   %PIP_CMD% list | findstr "requests colorama"
)

echo.
echo Press any key to exit...
pause >nul