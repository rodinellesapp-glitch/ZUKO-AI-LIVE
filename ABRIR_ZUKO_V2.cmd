@echo off
setlocal
cd /d "%~dp0"
python -B abrir_zuko_v2.py
if errorlevel 1 pause
