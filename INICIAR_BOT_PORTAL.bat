@echo off
cd /d "%~dp0"
py -3 -c "import discord" >nul 2>nul
if errorlevel 1 (
    echo Dependencias ausentes. Se o pip nao estiver disponivel, execute:
    echo py -3 -m ensurepip --upgrade
    echo Depois execute: py -3 -m pip install -r requirements.txt
    pause
    exit /b 1
)
py -3 bot_portal.py
if errorlevel 1 (
    echo.
    echo O bot nao iniciou. Confira o arquivo .env e as permissoes do Discord.
    pause
)
