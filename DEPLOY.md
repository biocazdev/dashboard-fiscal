# ============================================================
# Dashboard Fiscal Protheus - Guia de Publicacao
# ============================================================
#
# ATENCAO: Este dashboard conecta ao SQL Server do Protheus via ODBC.
# Nao e possivel rodar no Streamlit Community Cloud porque ele nao
# tem acesso a bancos de dados on-premise.
#
# Opcoes de deploy:
#   1. Servidor local da empresa (recomendado)
#   2. Docker no servidor da empresa
#   3. Cloud VM com VPN/Private Link ao SQL Server
#
# ============================================================

# ----------------------------------------------------------
# REQUISITOS PREVIOS
# ----------------------------------------------------------
# 1. Servidor com acesso rede ao SQL Server do Protheus
# 2. Python 3.12+ ou Docker
# 3. Driver ODBC 18 for SQL Server
# 4. Arquivo .env configurado (copie .env.example)

# ----------------------------------------------------------
# OPCAO 1: RODAR DIRETO NO SERVIDOR (sem Docker)
# ----------------------------------------------------------

# 1.1 Copie a pasta Fiscal para o servidor
#     Ex.: C:\Fiscal ou /opt/fiscal

# 1.2 Crie o ambiente virtual
#     Windows:
#       python -m venv .venv
#       .venv\Scripts\activate
#     Linux:
#       python3 -m venv .venv
#       source .venv/bin/activate

# 1.3 Instale as dependencias
#     pip install -r requirements.txt

# 1.4 Instale o driver ODBC (se ainda nao tiver)
#     Windows: baixe em https://learn.microsoft.com/pt-br/sql/connect/odbc/download-odbc-driver-for-sql-server
#     Linux (Debian/Ubuntu):
#       curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
#       curl https://packages.microsoft.com/config/debian/12/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
#       sudo apt-get update
#       sudo ACCEPT_EULA=Y apt-get install msodbcsql18

# 1.5 Configure o .env
#     copy .env.example .env    (Windows)
#     cp .env.example .env      (Linux)
#     Preencha com os dados do SQL Server

# 1.6 Rode o dashboard
#     streamlit run app.py --server.port 8501 --server.address 0.0.0.0
#
#     Ou use o .bat no Windows:
#       iniciar_dashboard_fiscal.bat

# ----------------------------------------------------------
# OPCAO 2: DOCKER (recomendado para servidores)
# ----------------------------------------------------------

# 2.1 Copie a pasta Fiscal para o servidor

# 2.2 Configure o .env
#     cp .env.example .env
#     Preencha as credenciais do SQL Server

# 2.3 Suba o container
#     docker compose up -d --build

# 2.4 Acesse o dashboard
#     http://SERVIDOR:8501

# 2.5 Para parar
#     docker compose down

# 2.6 Para ver logs
#     docker compose logs -f

# ----------------------------------------------------------
# OPCAO 3: WINDOWS COMO SERVICO (Windows Server)
# ----------------------------------------------------------

# Para rodar como servico no Windows (inicia automaticamente):

# 3.1 Instale o NSSM (Non-Sucking Service Manager):
#     https://nssm.cc/download

# 3.2 Crie o servico:
#     nssm install DashboardFiscal "C:\Fiscal\.venv\Scripts\python.exe"
#     nssm set DashboardFiscal Parameters "-m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true"
#     nssm set DashboardFiscal AppDirectory "C:\Fiscal"
#     nssm set DashboardFiscal DisplayName "Dashboard Fiscal Protheus"
#     nssm set DashboardFiscal Description "Dashboard Fiscal Biocaz - Protheus"
#     nssm set DashboardFiscal Start SERVICE_AUTO_START

# 3.3 Inicie o servico:
#     nssm start DashboardFiscal

# 3.4 Para gerenciar:
#     nssm edit DashboardFiscal

# ----------------------------------------------------------
# PORTA E ACESSO
# ----------------------------------------------------------
# Porta padrao: 8501
# Acesse: http://SERVIDOR:8501
#
# Se precisar mudar a porta, altere no:
#   - Dockerfile (ENTRYPOINT)
#   - docker-compose.yml (ports)
#   - Ou na linha de comando do streamlit run

# ----------------------------------------------------------
# SEGURANCA
# ----------------------------------------------------------
# - NUNCA versionar o arquivo .env (esta no .gitignore)
# - O usuario do SQL Server deve ter permissao SOMENTE de leitura
# - Em producao, use HTTPS (reverse proxy nginx/caddy)
# - Limite o acesso a rede interna da empresa
# - O arquivo anotacoes.db fica local (nao no banco)

# ----------------------------------------------------------
# SOLUCAO DE PROBLEMAS
# ----------------------------------------------------------
# "Erro de conexao com o banco":
#   - Verifique se o .env esta correto
#   - Verifique se o servidor SQL Server esta acessivel
#   - Verifique se o driver ODBC esta instalado
#   - Teste: python -c "import pyodbc; print(pyodbc.drivers())"
#
# "ModuleNotFoundError":
#   - Execute: pip install -r requirements.txt
#
# "Porta em uso":
#   - mude a porta: streamlit run app.py --server.port 8502
