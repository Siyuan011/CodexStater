@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0..\src\launcher\launch.ps1" -Action launch %*
set "_stater_exit=%errorlevel%"
if not "%_stater_exit%"=="0" pause
exit /b %_stater_exit%
