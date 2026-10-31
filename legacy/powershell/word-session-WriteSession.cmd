@echo off
%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File "%~dp0\word-session.ps1" WriteSession

IF ERRORLEVEL 1 (
    echo An error occurred.
    PAUSE
)