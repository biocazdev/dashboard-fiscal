"""Armazenamento local (SQLite) das anotações por documento.

O Protheus é acessado somente leitura neste projeto - não é possível gravar
observações de volta nele. Este módulo guarda as anotações do contador
(ex.: "aguardando NF do fornecedor") em um arquivo SQLite local, ao lado da
aplicação (``ANOTACOES_DB`` no ``.env``), separado do banco fiscal.

Fica isolado em seu próprio módulo (como ``database/connection.py`` faz para
o SQL Server) para deixar claro que é uma fonte de dados independente.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)

# A chave (filial, tipo, documento, serie) identifica um documento do
# dashboard de forma única - "tipo" distingue nota de entrada/saída/título
# etc., já que documento+série sozinhos podem se repetir entre tipos
# diferentes. UNIQUE nessa combinação é o que permite o "upsert" (inserir
# ou atualizar) usado em salvar_nota().
_SCHEMA = """
CREATE TABLE IF NOT EXISTS anotacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filial TEXT NOT NULL,
    tipo TEXT NOT NULL,
    documento TEXT NOT NULL,
    serie TEXT NOT NULL DEFAULT '',
    observacao TEXT NOT NULL DEFAULT '',
    autor TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    UNIQUE(filial, tipo, documento, serie)
);
"""


@contextmanager
def _conexao():
    """Abre a conexão com o arquivo SQLite local (cria o arquivo/tabela se preciso).

    Usada como ``with _conexao() as conn:`` em cada função abaixo - o
    ``@contextmanager`` garante que a conexão sempre seja fechada
    (``finally: conn.close()``) mesmo se uma consulta lançar erro no meio,
    e que o commit só aconteça se o bloco todo rodar sem exceção (o
    ``conn.commit()`` fica depois do ``yield``, então uma exceção dentro do
    ``with`` pula direto para o ``finally`` sem commitar).
    """
    conn = sqlite3.connect(settings.ANOTACOES_DB)
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def buscar_nota(filial: str, tipo: str, documento: str, serie: str = "") -> dict | None:
    """Retorna a anotação atual de um documento, se existir."""
    with _conexao() as conn:
        cur = conn.execute(
            "SELECT observacao, autor, criado_em, atualizado_em FROM anotacoes "
            "WHERE filial = ? AND tipo = ? AND documento = ? AND serie = ?",
            (filial, tipo, documento, serie),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "observacao": row[0],
        "autor": row[1],
        "criado_em": row[2],
        "atualizado_em": row[3],
    }


def salvar_nota(
    filial: str, tipo: str, documento: str, serie: str, observacao: str, autor: str
) -> None:
    """Cria ou atualiza a anotação de um documento (uma anotação vigente por documento)."""
    agora = datetime.now().isoformat(timespec="seconds")
    with _conexao() as conn:
        # "Upsert": tenta inserir uma linha nova; se já existir uma com a
        # mesma chave única (filial+tipo+documento+serie), atualiza os
        # campos em vez de dar erro de duplicidade. `excluded.coluna`
        # refere-se ao valor que SERIA inserido (a linha nova) - por isso
        # `criado_em` não é sobrescrito aqui (mantém a data da primeira
        # vez que a nota foi salva), só `observacao`/`autor`/`atualizado_em`.
        conn.execute(
            """
            INSERT INTO anotacoes (filial, tipo, documento, serie, observacao, autor, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filial, tipo, documento, serie) DO UPDATE SET
                observacao = excluded.observacao,
                autor = excluded.autor,
                atualizado_em = excluded.atualizado_em
            """,
            (filial, tipo, documento, serie, observacao, autor, agora, agora),
        )


def remover_nota(filial: str, tipo: str, documento: str, serie: str = "") -> None:
    """Remove a anotação de um documento (ex.: pendência resolvida)."""
    with _conexao() as conn:
        conn.execute(
            "DELETE FROM anotacoes WHERE filial = ? AND tipo = ? AND documento = ? AND serie = ?",
            (filial, tipo, documento, serie),
        )


def listar_notas(filiais: list[str]) -> list[dict]:
    """Lista todas as anotações vigentes das filiais informadas."""
    if not filiais:
        return []
    # Monta "?, ?, ?" com um "?" para cada filial (não insere o VALOR das
    # filiais na string SQL - isso continua parametrizado via `filiais`
    # logo abaixo). Necessário porque o SQLite (como a maioria dos drivers
    # SQL) não aceita passar uma lista inteira como um único parâmetro "?"
    # para um IN (...) - precisa de um placeholder por item.
    placeholders = ", ".join("?" for _ in filiais)
    with _conexao() as conn:
        cur = conn.execute(
            f"SELECT filial, tipo, documento, serie, observacao, autor, atualizado_em "
            f"FROM anotacoes WHERE filial IN ({placeholders}) ORDER BY atualizado_em DESC",
            filiais,
        )
        # cur.description traz metadados de cada coluna do resultado
        # (nome, tipo, etc.) - c[0] é o nome. Monta um dict por linha
        # (nome_coluna -> valor) em vez de tuplas posicionais, para o
        # restante do código não depender da ordem das colunas no SELECT.
        colunas = [c[0] for c in cur.description]
        return [dict(zip(colunas, row)) for row in cur.fetchall()]
