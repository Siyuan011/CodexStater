@echo off
setlocal
set "_stater_pause=1"
for %%A in (%*) do (
    if /I "%%~A"=="-NonInteractive" set "_stater_pause="
    if /I "%%~A"=="-Check" set "_stater_pause="
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0launch.ps1" -Action launch %*
set "_stater_exit=%errorlevel%"
if not "%_stater_exit%"=="0" if defined _stater_pause pause
exit /b %_stater_exit%
