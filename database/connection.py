"""Conexão com o SQL Server.

Esta camada é a única responsável por abrir conexões com o banco.

Segurança (seção 25 da especificação):
- Credenciais vêm apenas do ``.env`` (nunca do código).
- Erros são registrados em log sem expor senha ou connection string.
"""

import logging

import pyodbc

from config import settings

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Erro amigável quando não é possível conectar ao banco."""


def _montar_connection_string() -> str:
    """Monta a connection string ODBC a partir das configurações."""
    if not settings.DB_SERVER or not settings.DB_DATABASE:
        raise DatabaseConnectionError(
            "Configuração de banco incompleta. "
            "Verifique o arquivo .env (DB_SERVER/DB_DATABASE)."
        )

    return (
        f"DRIVER={{{settings.DB_DRIVER}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE={settings.DB_DATABASE};"
        f"UID={settings.DB_USER};"
        f"PWD={settings.DB_PASSWORD};"
        # O driver ODBC 18+ passou a exigir certificado TLS válido no
        # servidor por padrão; muitos SQL Server internos (como este, numa
        # rede corporativa fechada) usam certificado autoassinado, que
        # falharia a validação. TrustServerCertificate=yes desliga essa
        # checagem - aceitável aqui porque a conexão já roda dentro da
        # rede da empresa, mas não seria recomendado se o banco estivesse
        # exposto pela internet.
        "TrustServerCertificate=yes;"
    )


def get_connection() -> pyodbc.Connection:
    """Abre e retorna uma conexão com o SQL Server.

    Raises:
        DatabaseConnectionError: quando a conexão não puder ser estabelecida.
    """
    try:
        return pyodbc.connect(
            _montar_connection_string(),
            timeout=settings.DB_TIMEOUT,
        )
    except Exception as exc:
        # Só loga server/database (informação operacional útil para
        # diagnosticar "caiu a rede" vs. "servidor errado no .env") - de
        # propósito NÃO loga a exceção original (`exc`) nem a connection
        # string, porque o driver pyodbc às vezes inclui usuário/senha na
        # mensagem de erro, e isso não pode parar no arquivo de log.
        logger.error(
            "Falha ao conectar ao SQL Server (server=%s, database=%s).",
            settings.DB_SERVER,
            settings.DB_DATABASE,
        )
        # `from exc` preserva a causa original só na exceção em memória
        # (visível se alguém rodar com um debugger), não no log.
        raise DatabaseConnectionError(
            "Não foi possível conectar ao banco de dados. "
            "Verifique o arquivo .env e a disponibilidade do servidor."
        ) from exc
