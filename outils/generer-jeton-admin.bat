@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Python\PythonCore-3.14-64\python.exe" set "PY=%LOCALAPPDATA%\Python\PythonCore-3.14-64\python.exe"
if not defined PY set "PY=py -3"
%PY% "%~dp0jeton_admin.py"
echo.
echo  Fermez cette fenetre, puis redemarrez le service (tache planifiee ou exe).
pause
