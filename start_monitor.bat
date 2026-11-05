@echo off
REM HIKVISION VIDEO MONITOR - lancement (double-clic). Fermer cette fenetre arrete la supervision.
cd /d "%~dp0"
title HIKVISION VIDEO MONITOR

REM Prerequis communs a tout le projet (requirements.txt).
set "DEPS=import requests, openpyxl, dotenv"

REM On ne retient qu'un interpreteur qui possede REELLEMENT ces modules :
REM "py -3" peut pointer vers un Python systeme sans les dependances.

REM 1) Environnement virtuel du projet, s'il existe.
if exist ".venv\Scripts\python.exe" goto venv

REM 2) Interpreteur du projet (celui ou les dependances ont ete installees).
set "PYEXE=%LOCALAPPDATA%\Python\PythonCore-3.14-64\python.exe"
if exist "%PYEXE%" (
  "%PYEXE%" -c "%DEPS%" >nul 2>&1
  if not errorlevel 1 goto useexe
)

REM 3) Launcher officiel puis PATH, uniquement s'ils ont les dependances.
py -3 -c "%DEPS%" >nul 2>&1
if not errorlevel 1 goto usepy
python -c "%DEPS%" >nul 2>&1
if not errorlevel 1 goto usepython

echo.
echo Aucun Python disposant des dependances du projet n'a ete trouve.
echo Installez-les avec :
echo    "%LOCALAPPDATA%\Python\PythonCore-3.14-64\python.exe" -m pip install -r requirements.txt
echo.
pause
exit /b 1

REM --- Adresse du dashboard, lue dans config/.env (et non codee en dur) ---
:venv
set "PYRUN=".venv\Scripts\python.exe""
goto adresse
:useexe
set "PYRUN="%PYEXE%""
goto adresse
:usepy
set "PYRUN=py -3"
goto adresse
:usepython
set "PYRUN=python"

:adresse
set "HOST=127.0.0.1"
set "PORT=8765"
for /f "usebackq tokens=1,* delims==" %%A in ("config\.env") do (
  if /i "%%A"=="DASHBOARD_HOST" set "HOST=%%B"
  if /i "%%A"=="DASHBOARD_PORT" set "PORT=%%B"
)
if "%HOST%"=="0.0.0.0" set "HOST=127.0.0.1"
title HIKVISION VIDEO MONITOR - http://%HOST%:%PORT%
echo Dashboard : http://%HOST%:%PORT%/
start "" http://%HOST%:%PORT%/
%PYRUN% src\main.py
pause
