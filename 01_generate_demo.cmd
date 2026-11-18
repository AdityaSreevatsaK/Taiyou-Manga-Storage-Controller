@echo off
setlocal
cd /d "%~dp0"
py -3 -m taiyou_manga fixtures --output "demo_manga"
pause
