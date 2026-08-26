"""Conexão com o SQL Server.

Esta camada é a única responsável por abrir conexões com o banco.

Suporta dois drivers:
- ``pymssql``: conexão pura Python (usado no Streamlit Community Cloud).
- ``pyodbc``: conexão via ODBC (usado localmente e em Docker).

A detecção é automática: tenta ``pymssql`` primeiro; se não estiver
instalado, usa ``pyodbc``.

Segurança (seção 25 da especificação):
- Credenciais vêm apenas de ``.env`` ou ``st.secrets`` (nunca do código).
- Erros são registrados em log sem expor senha ou connection string.
"""

import logging

from config import settings

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Erro amigável quando não é possível conectar ao banco."""


def _try_pymssql():
    """Tenta importar pymssql e retorna o módulo, ou None."""
    try:
        import pymssql
        return pymssql
    except ImportError:
        return None


def _try_pyodbc():
    """Tenta importar pyodbc e retorna o módulo, ou None."""
    try:
        import pyodbc
        return pyodbc
    except ImportError:
        return None


_PYMSSQL = _try_pymssql()
_PYODBC = _try_pyodbc()


def _montar_params_pymssql() -> dict:
    """Monta os parâmetros de conexão para pymssql."""
    if not settings.DB_SERVER or not settings.DB_DATABASE:
        raise DatabaseConnectionError(
            "Configuração de banco incompleta. "
            "Verifique as variáveis de ambiente ou st.secrets "
            "(DB_SERVER/DB_DATABASE)."
        )
    params: dict = {
        "server": settings.DB_SERVER,
        "database": settings.DB_DATABASE,
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "timeout": settings.DB_TIMEOUT,
        "login_timeout": settings.DB_TIMEOUT,
    }
    return params


def _montar_connection_string_pyodbc() -> str:
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
        "TrustServerCertificate=yes;"
    )


def get_connection():
    """Abre e retorna uma conexão com o SQL Server.

    Tenta pymssql primeiro (cloud), depois pyodbc (local/Docker).

    Raises:
        DatabaseConnectionError: quando a conexão não puder ser estabelecida.
    """
    # 1) pymssql (Streamlit Cloud e ambientes sem ODBC driver)
    if _PYMSSQL is not None:
        try:
            params = _montar_params_pymssql()
            return _PYMSSQL.connect(**params)
        except Exception as exc:
            logger.error(
                "Falha ao conectar via pymssql (server=%s, database=%s).",
                settings.DB_SERVER,
                settings.DB_DATABASE,
            )
            raise DatabaseConnectionError(
                "Não foi possível conectar ao banco de dados (pymssql). "
                "Verifique as credenciais e a disponibilidade do servidor."
            ) from exc

    # 2) pyodbc (local, Docker, servidores com ODBC driver)
    if _PYODBC is not None:
        try:
            return _PYODBC.connect(
                _montar_connection_string_pyodbc(),
                timeout=settings.DB_TIMEOUT,
            )
        except Exception as exc:
            logger.error(
                "Falha ao conectar via pyodbc (server=%s, database=%s).",
                settings.DB_SERVER,
                settings.DB_DATABASE,
            )
            raise DatabaseConnectionError(
                "Não foi possível conectar ao banco de dados (pyodbc). "
                "Verifique o arquivo .env e a disponibilidade do servidor."
            ) from exc

    # 3) Nenhum driver disponível
    raise DatabaseConnectionError(
        "Nenhum driver de banco disponível. "
        "Instale pymssql (pip install pymssql) ou pyodbc (pip install pyodbc)."
    )
