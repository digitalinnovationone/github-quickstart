@echo off
cd /d "%~dp0"
py -3 configurador_palworld.py
if errorlevel 1 (
    echo.
    echo Nao foi possivel iniciar. Instale o Python 3 e tente novamente.
    pause
)
