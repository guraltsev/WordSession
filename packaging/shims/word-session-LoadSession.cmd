@echo off
if "%~1"=="" (
    "%~dp0word-session.exe" restore latest
) else (
    "%~dp0word-session.exe" restore "%~1"
)

if errorlevel 1 pause
