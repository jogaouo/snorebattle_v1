@echo off
setlocal
cd /d "%~dp0"
set "PYGAME_HIDE_SUPPORT_PROMPT=1"
if not exist "%~dp0runtime\python.exe" (
  echo Missing project runtime: runtime\python.exe
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" "%~dp0main.py" %*
set "gameExit=%errorlevel%"
if not "%gameExit%"=="0" pause
exit /b %gameExit%
