@echo off
rem Specio Catalog - launcher (no console window if pythonw exists)
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw gui\main_window.py
) else (
    start "" python gui\main_window.py
)
