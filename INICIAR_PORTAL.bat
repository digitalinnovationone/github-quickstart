@echo off
cd /d "%~dp0"
py -3 -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo Dependencias ausentes. Se o pip nao estiver disponivel, execute:
    echo py -3 -m ensurepip --upgrade
    echo Depois execute: py -3 -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" "http://127.0.0.1:5000"
py -3 portal_palworld.py
if errorlevel 1 (
    echo.
    echo O portal nao iniciou. Verifique a configuracao e tente novamente.
    pause
)
