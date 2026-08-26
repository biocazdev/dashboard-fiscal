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
import threading
from collections import deque

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

# Estilo de placeholder de parâmetro esperado pela consulta SQL: pyodbc usa
# "?" (qmark) - é o estilo em que TODO o SQL deste projeto é escrito
# (database/queries.py, database/conciliacao_queries.py). O driver pymssql
# (usado no Streamlit Community Cloud, que não tem driver ODBC instalado)
# NÃO entende "?" como placeholder - ele espera o estilo "%s" (formatação
# Python) e, se receber "?" no texto do SQL, simplesmente manda o "?"
# literal para o SQL Server, que rejeita com "Incorrect syntax near '?'".
# Em vez de reescrever centenas de placeholders nos dois arquivos de
# consultas, a tradução acontece uma única vez, na hora de executar cada
# consulta (ver ``adaptar_placeholders()`` abaixo, usado em
# ``services/fiscal_service.py::_ler_sql()`` - único ponto do projeto que
# roda SQL contra o banco).
USANDO_PYMSSQL: bool = _PYMSSQL is not None


def adaptar_placeholders(sql: str) -> str:
    """Converte os placeholders "?" do SQL para o estilo que o driver ativo espera.

    Com pyodbc, "?" já é o formato nativo - o SQL volta sem alteração. Com
    pymssql, cada "?" vira "%s". A troca por substituição de texto simples
    é segura aqui porque: (1) nenhuma consulta deste projeto usa "?" fora
    de posição de parâmetro (não há "?" solto em comentário ou texto
    dentro das strings SQL_*); e (2) não existe nenhum "%" literal escrito
    no texto de nenhuma consulta - os curingas de LIKE (ex. "01%") sempre
    vêm como VALOR de parâmetro vindo do Python, nunca escritos direto no
    SQL, então não há risco de colisão com a formatação "%s" do pymssql.
    """
    return sql.replace("?", "%s") if USANDO_PYMSSQL else sql


def _parse_server_pymssql(valor: str) -> tuple[str, int | None]:
    """Converte DB_SERVER do formato pyodbc para (host, porta) do pymssql.

    ``DB_SERVER`` neste projeto é configurado no formato que o pyodbc
    espera dentro da connection string - ex.: ``tcp:181.41.163.164,10522``
    (prefixo "tcp:" + host + porta separada por VÍRGULA). O pymssql NÃO
    entende esse formato como uma string única: se você passar
    ``server="tcp:181.41.163.164,10522"`` direto para ``pymssql.connect()``,
    ele tenta resolver isso como se fosse um hostname literal (com "tcp:" e
    vírgula incluídos) e a conexão falha sempre, mesmo com credenciais
    corretas e o servidor no ar - foi exatamente esse bug que quebrou a
    conexão ao adicionar o pymssql como driver alternativo (para rodar no
    Streamlit Community Cloud, que não tem driver ODBC instalado).

    Por isso aqui host e porta são separados manualmente e passados como
    parâmetros distintos para o pymssql (que aceita ``server``/``port``
    separados, ou ``host:porta`` com dois-pontos - nunca vírgula).
    """
    texto = (valor or "").strip()
    if texto.lower().startswith("tcp:"):
        texto = texto[4:]
    # pyodbc usa vírgula (host,porta); por segurança também aceitamos
    # dois-pontos (host:porta), caso o .env seja preenchido nesse formato.
    separador = "," if "," in texto else (":" if ":" in texto else None)
    if separador is None:
        return texto, None
    host, porta_texto = texto.split(separador, 1)
    try:
        porta = int(porta_texto.strip())
    except ValueError:
        # Porta em formato inesperado - melhor deixar o pymssql usar a
        # porta padrão (1433) do que quebrar aqui com um erro confuso.
        porta = None
    return host.strip(), porta


def _montar_params_pymssql() -> dict:
    """Monta os parâmetros de conexão para pymssql."""
    if not settings.DB_SERVER or not settings.DB_DATABASE:
        raise DatabaseConnectionError(
            "Configuração de banco incompleta. "
            "Verifique as variáveis de ambiente ou st.secrets "
            "(DB_SERVER/DB_DATABASE)."
        )
    host, porta = _parse_server_pymssql(settings.DB_SERVER)
    params: dict = {
        "server": host,
        "database": settings.DB_DATABASE,
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "timeout": settings.DB_TIMEOUT,
        "login_timeout": settings.DB_TIMEOUT,
    }
    if porta:
        params["port"] = porta
    return params


# ---------------------------------------------------------------------------
# Connection pool para pymssql (que NÃO tem pooling automático)
# ---------------------------------------------------------------------------
# pymssql não retorna conexões a um pool como o pyodbc faz via ODBC Driver
# Manager. Sem pooling, cada chamada a _ler_sql abre e fecha uma conexão TCP
# ao SQL Server (~50-200ms de handshake por query). Este pool simples mantém
# até POOL_MAX_CONEXOES conexões vivas entre chamadas, reutilizando-as via
# fila thread-safe. pyodbc já tem pooling nativo, então este código só é
# ativo quando USANDO_PYMSSQL é True.
POOL_MAX_CONEXOES = 5
_pool_pymssql: deque = deque()
_pool_lock = threading.Lock()


def _obter_conexao_pymssql():
    """Retorna uma conexão do pool ou cria uma nova."""
    with _pool_lock:
        while _pool_pymssql:
            conn = _pool_pymssql.popleft()
            try:
                if not conn.closed:
                    return conn
            except Exception:
                pass
    return _PYMSSQL.connect(**_montar_params_pymssql())


def _devolver_ao_pool(conn):
    """Devolve uma conexão ao pool (se não estiver fechada e o pool não estiver cheio)."""
    try:
        if conn.closed:
            return
    except Exception:
        return
    with _pool_lock:
        if len(_pool_pymssql) < POOL_MAX_CONEXOES:
            _pool_pymssql.append(conn)
        else:
            try:
                conn.close()
            except Exception:
                pass


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
    Para pymssql, reutiliza conexões do pool para evitar overhead de TCP.

    Raises:
        DatabaseConnectionError: quando a conexão não puder ser estabelecida.
    """
    # 1) pymssql (Streamlit Cloud e ambientes sem ODBC driver)
    if _PYMSSQL is not None:
        try:
            return _obter_conexao_pymssql()
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


def release_connection(conn):
    """Devolve uma conexão ao pool (pymssql) ou fecha (pyodbc).

    Chame esta função em vez de conn.close() quando a consulta terminar.
    """
    if _PYMSSQL is not None and not getattr(conn, '_is_pyodbc', False):
        _devolver_ao_pool(conn)
    else:
        try:
            conn.close()
        except Exception:
            pass
