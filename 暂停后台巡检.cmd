@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0src\launcher\launch.ps1" -Action Pause %*
set "_stater_exit=%errorlevel%"
pause
exit /b %_stater_exit%
