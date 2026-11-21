@echo off
rem Islanding GUI: double-click this file to start it. The page opens in the browser
rem at http://localhost:8080. To stop the GUI and its Julia worker, close this window
rem or press Ctrl+C in it. Arguments go to app.py, for example: start_gui.bat --port 8090
title Islanding GUI
cd /d "%~dp0"
python app.py %*
rem keep the window open when the GUI could not start, so the message can be read.
rem 3 and -1073741510 are its exit codes after Ctrl+Break and Ctrl+C, not failures.
if %errorlevel% neq 0 if %errorlevel% neq 3 if %errorlevel% neq -1073741510 pause
