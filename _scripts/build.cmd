@echo off
rem Build dist\WordSession and the zip; pass -NoSync to skip 'uv sync' (see build.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
exit /b %ERRORLEVEL%
