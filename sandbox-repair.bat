@echo off
setlocal EnableDelayedExpansion
title Windows Sandbox Repair
rem ============================================================
rem  Repair Windows Sandbox after "0x80070490 element not found".
rem  1. show current feature states and hypervisor status
rem  2. stop Windows Update services (prevents CBS hang)
rem  3. disable both sandbox-related features
rem  4. restart Windows Update services
rem  5. reboot, then run install-windows-sandbox.bat again
rem ============================================================

net session >nul 2>&1
if %errorlevel%==0 goto :got_admin
echo NOT running as administrator.
pause
powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
exit /b

:got_admin
echo.
echo ============================================
echo    Windows Sandbox Repair
echo ============================================
echo.
echo --- current feature states ---
dism /online /get-featureinfo /featurename:Containers-DisposableClientVM | findstr /i "State"
dism /online /get-featureinfo /featurename:VirtualMachinePlatform | findstr /i "State"
echo.
echo --- hypervisor status ---
echo True  = hypervisor is running, good
echo False = hypervisor is NOT running, a reboot after enabling is required
powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).HypervisorPresent"
echo.

echo --- step 0: stopping Windows Update services ---
echo (this prevents CBS from hanging on Windows Update downloads)
net stop wuauserv
net stop bits
echo.
echo --- step 1: disabling features ---
dism /online /disable-feature /featurename:Containers-DisposableClientVM /norestart
dism /online /disable-feature /featurename:VirtualMachinePlatform /norestart
echo.
echo --- step 2: restarting Windows Update services ---
net start bits
net start wuauserv
echo.
echo ============================================
echo  Now REBOOT your PC.
echo  After reboot, run install-windows-sandbox.bat
echo  as administrator to re-enable everything.
echo ============================================
echo.
pause
