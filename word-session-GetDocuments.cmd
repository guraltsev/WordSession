@echo off
%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File "%~dp0\word-session.ps1" -Pause GetDocuments

IF ERRORLEVEL 1 (
    echo An error occurred.
    PAUSE
)