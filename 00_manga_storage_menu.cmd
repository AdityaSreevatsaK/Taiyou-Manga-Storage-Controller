@echo off
setlocal
cd /d "%~dp0"
py -3 -m taiyou_manga menu
if errorlevel 1 (
  echo.
  echo Setup may be required: py -3 -m pip install -e .
)
pause
