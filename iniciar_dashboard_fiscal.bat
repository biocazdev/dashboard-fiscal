@echo off
title Dashboard Fiscal Protheus
cd /d "%~dp0"

echo ============================================
echo   Dashboard Fiscal Protheus - Biocaz
echo ============================================
echo.

set "PYTHON=C:\LDO\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Ambiente virtual nao encontrado em: %PYTHON%
    echo Verifique o caminho do .venv.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Arquivo .env nao encontrado.
    echo Copie o arquivo .env.example para .env e preencha as credenciais.
    pause
    exit /b 1
)

echo Conectando via VPN (se necessario) antes de continuar...
echo.
echo Iniciando o Streamlit...
echo.

"%PYTHON%" -m streamlit run app.py

echo.
pause
