@echo off
setlocal
cd /d "%~dp0"
python -B abrir_painel_npc.py
if errorlevel 1 pause
