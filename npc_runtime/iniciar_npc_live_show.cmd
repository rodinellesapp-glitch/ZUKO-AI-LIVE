@echo off
setlocal
cd /d "%~dp0"
python -B npc_live_show.py --start-godot --start-local-ai
if errorlevel 1 pause
