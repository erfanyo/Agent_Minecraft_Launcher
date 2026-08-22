@echo off
setlocal EnableDelayedExpansion
title Windows Sandbox Installer (Home Edition)
rem ============================================================
rem  Enable Windows Sandbox on Windows 10/11 Home edition.
rem  Fully offline. Steps:
rem   1. try enabling the feature directly (fast path)
rem   2. if that needs packages, register them with live
rem      progress, then enable again
rem ============================================================

rem ---- admin check ----
net session >nul 2>&1
if %errorlevel%==0 goto :got_admin

echo.
echo ============================================================
echo   NOT running as administrator.
echo   This script needs admin rights, so it will now re-launch
echo   itself with a UAC prompt. Please click YES on the prompt.
echo   If no prompt appears, close this and instead right-click
echo   this file, then choose "Run as administrator".
echo ============================================================
echo.
pause
powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
exit /b

:got_admin
echo.
echo ============================================
echo    Windows Sandbox Installer - Home Edition
echo ============================================
echo.

rem ---- 1. check virtualization ----
echo [1/5] Checking virtualization...
powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled" > "%temp%\virt.txt" 2>nul
set /p VIRT=<"%temp%\virt.txt"
del "%temp%\virt.txt" 2>nul
if /i "%VIRT%"=="TRUE" (
    echo       OK - virtualization is enabled
) else (
    echo       WARNING: virtualization seems off in BIOS.
    echo       Enable Intel VT-x or AMD SVM in BIOS first,
    echo       then run this script again.
)
echo.

rem ---- 1.5 pending-reboot check (DISM hangs if a servicing reboot is pending) ----
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending" >nul 2>&1
if %errorlevel%==0 (
    echo ============================================================
    echo   WARNING: Windows has a pending servicing reboot.
    echo   DISM can hang in this state. Please REBOOT now,
    echo   then run this script again.
    echo ============================================================
    echo.
    pause
    exit /b
)

rem ---- 2. enable VirtualMachinePlatform ----
echo [2/5] Enabling VirtualMachinePlatform...
dism /online /norestart /enable-feature /featurename:VirtualMachinePlatform /all /LimitAccess
echo.

rem ---- 3. try enabling sandbox directly ----
echo [3/5] Trying to enable Windows Sandbox directly...
dism /online /norestart /enable-feature /featurename:Containers-DisposableClientVM /all /LimitAccess
if %errorlevel%==0 goto :done

rem ---- 4. register local packages with progress ----
echo.
echo [4/5] Direct enable needs packages. Registering local ones now...
dir /b "%SystemRoot%\servicing\Packages\*Containers*.mum" > "%temp%\sb_mum.txt" 2>nul
set TOTAL=0
for /f "delims=" %%i in ('type "%temp%\sb_mum.txt"') do set /a TOTAL+=1
set COUNT=0
for /f "delims=" %%i in ('type "%temp%\sb_mum.txt"') do (
    set /a COUNT+=1
    echo       [!COUNT!/!TOTAL!] %%i
    dism /online /norestart /add-package:"%SystemRoot%\servicing\Packages\%%i" >nul 2>&1
)
del "%temp%\sb_mum.txt" 2>nul
echo       Registered !COUNT! packages.

rem ---- 5. enable again ----
echo.
echo [5/5] Enabling Windows Sandbox...
dism /online /norestart /enable-feature /featurename:Containers-DisposableClientVM /LimitAccess /All
set FEATURE_ERR=%errorlevel%

:done
set FEATURE_ERR=%errorlevel%
echo.
if %FEATURE_ERR%==0 (
    echo ============================================
    echo    Done. Reboot your PC, then search for
    echo    Windows Sandbox in the Start menu.
    echo ============================================
) else (
    echo ============================================
    echo    Enable failed, error code %FEATURE_ERR%.
    echo    Screenshot this window for help.
    echo ============================================
)
echo.
pause
