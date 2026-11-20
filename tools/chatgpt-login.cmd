@echo off
cd /d "%~dp0.."
start "" "%~dp0..\.venv-agent\Scripts\pythonw.exe" -m macro_agent.login_window
