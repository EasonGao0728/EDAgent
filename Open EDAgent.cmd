@echo off
setlocal
title EDAgent Workbench
powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0tools\start-silicon-workbench.ps1" -Prepare -Open
if not errorlevel 1 exit /b 0
echo.
echo Startup failed. Read the message above, then press any key to close.
pause >nul
exit /b 1
