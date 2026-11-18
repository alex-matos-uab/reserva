@echo off
title Criar executavel - Reserva UAB
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado. Instale em python.org.
    pause
    exit /b 1
)

echo Instalando dependencias (Flask e PyInstaller)...
python -m pip install --upgrade pip
python -m pip install flask pyinstaller
if errorlevel 1 ( echo Falha ao instalar. & pause & exit /b 1 )

echo.
echo Gerando executavel (pode levar 1 ou 2 minutos)...
pyinstaller --noconfirm --onefile --windowed --name "Reserva-UAB" ^
  --add-data "templates;templates" app.py
if errorlevel 1 ( echo Falha ao gerar. & pause & exit /b 1 )

echo.
echo ==================================================
echo  SUCESSO!
echo  O programa final esta na pasta: dist\Reserva-UAB.exe
echo ==================================================
pause