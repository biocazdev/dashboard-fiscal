@echo off
title Deploy Dashboard Fiscal - Biocaz
cd /d "%~dp0"

echo ============================================
echo   Deploy Dashboard Fiscal Protheus
echo ============================================
echo.

:: Verifica Docker
where docker >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Docker nao encontrado!
    echo.
    echo Instale o Docker Desktop em:
    echo https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

:: Verifica docker compose
docker compose version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Docker Compose nao encontrado!
    echo Atualize o Docker Desktop para a versao mais recente.
    pause
    exit /b 1
)

:: Verifica .env
if not exist ".env" (
    echo Arquivo .env nao encontrado!
    echo.
    echo Copie o .env.example e preencha as credenciais:
    echo   copy .env.example .env
    echo.
    pause
    exit /b 1
)

echo [1/3] Building image Docker...
docker compose build
if %ERRORLEVEL% neq 0 (
    echo Erro ao buildar a imagem!
    pause
    exit /b 1
)

echo.
echo [2/3] Parando container anterior (se existir)...
docker compose down

echo.
echo [3/3] Iniciando dashboard...
docker compose up -d
if %ERRORLEVEL% neq 0 (
    echo Erro ao iniciar o container!
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Dashboard publicado com sucesso!
echo ============================================
echo.
echo   Acesse: http://localhost:8501
echo   Ou:     http://SEU_SERVIDOR:8501
echo.
echo   Ver logs:    docker compose logs -f
echo   Parar:       docker compose down
echo   Reiniciar:   docker compose restart
echo.

:: Pega o IP da maquina
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%a
)
set IP=%IP: =%

echo   Seu IP na rede: %IP%
echo   Outros podem acessar: http://%IP%:8501
echo.

pause
