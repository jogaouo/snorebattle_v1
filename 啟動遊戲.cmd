@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYGAME_HIDE_SUPPORT_PROMPT=1"
set "PYTHONUTF8=1"
if not exist "%~dp0runtime\python.exe" (
  echo Missing project runtime: runtime\python.exe
  echo Extract the entire project before launching.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" -X utf8 "%~dp0bootstrap.py" %*
set "gameExit=%errorlevel%"
if not "%gameExit%"=="0" pause
exit /b %gameExit%
