@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
    echo Python nao encontrado. Instale em python.org e marque "Adicionar ao PATH".
    pause
    exit /b 1
)
echo Verificando dependencias...
python -m pip install --quiet flask
echo Iniciando o sistema...
python app.py
pause