@echo off
setlocal
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py "%~dp0..\.gittools\release\release.py" %*
) else (
  python "%~dp0..\.gittools\release\release.py" %*
)
exit /b %ERRORLEVEL%
