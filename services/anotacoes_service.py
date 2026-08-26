"""Serviço de anotações locais por documento (bloco "Produtividade").

Camada fina sobre ``database/anotacoes_db.py``: resolve o autor da anotação
e mantém a mesma convenção das outras camadas (nenhuma lógica de UI aqui).
"""

import getpass
import os

import pandas as pd

from database import anotacoes_db


def _usuario_atual() -> str:
    """Nome do usuário do Windows logado na máquina, usado como autor da nota.

    O dashboard não tem login próprio - a "autoria" da anotação é apenas
    informativa (para saber quem escreveu o quê), por isso usa o usuário
    do sistema operacional em vez de pedir cadastro. ``USERNAME`` é a
    variável de ambiente do Windows (ambiente de uso real do contador),
    ``USER`` cobre Linux/Mac (ex.: desenvolvimento/testes), e
    ``getpass.getuser()`` é o último fallback antes de assumir
    "desconhecido" (nunca lança exceção para não impedir salvar a nota).
    """
    return os.getenv("USERNAME") or os.getenv("USER") or getpass.getuser() or "desconhecido"


def buscar_nota(filial: str, tipo: str, documento: str, serie: str = "") -> dict | None:
    """Retorna a anotação atual de um documento, se existir.

    Repassa direto para ``anotacoes_db`` (SQLite local) - só normaliza os
    parâmetros (str + strip) para evitar que espaços em branco vindos dos
    campos vazios de largura fixa do Protheus quebrem a busca pela chave
    (filial+tipo+documento+série). Retorna ``None`` quando não há
    anotação salva para o documento.
    """
    return anotacoes_db.buscar_nota(str(filial).strip(), tipo, str(documento).strip(), str(serie).strip())


def salvar_nota(filial: str, tipo: str, documento: str, serie: str, observacao: str) -> None:
    """Salva (cria ou atualiza) a anotação de um documento com o usuário atual como autor.

    ``anotacoes_db.salvar_nota`` faz o upsert (insere se não existir,
    atualiza se já existir anotação para a mesma chave) - aqui só resolve
    o autor e normaliza os parâmetros antes de repassar. Efeito colateral:
    grava no SQLite local (não altera nada no Protheus).
    """
    anotacoes_db.salvar_nota(
        str(filial).strip(),
        tipo,
        str(documento).strip(),
        str(serie).strip(),
        observacao.strip(),
        _usuario_atual(),
    )


def remover_nota(filial: str, tipo: str, documento: str, serie: str = "") -> None:
    """Remove a anotação de um documento.

    Efeito colateral: exclui o registro do SQLite local. Não é erro
    remover uma anotação que não existe - ``anotacoes_db`` trata isso como
    no-op.
    """
    anotacoes_db.remover_nota(str(filial).strip(), tipo, str(documento).strip(), str(serie).strip())


def listar_notas(filiais: list[str]) -> pd.DataFrame:
    """Lista as anotações vigentes das filiais informadas, como DataFrame.

    Usada para exibir a aba de anotações e para cruzar anotações com os
    outros DataFrames da tela. Sem anotações no período/filiais, devolve
    um DataFrame vazio mas com as colunas já nomeadas - evita erro de
    "coluna não existe" em quem consome o retorno esperando essas colunas.
    """
    registros = anotacoes_db.listar_notas([str(f).strip() for f in filiais])
    if not registros:
        return pd.DataFrame(
            columns=["filial", "tipo", "documento", "serie", "observacao", "autor", "atualizado_em"]
        )
    return pd.DataFrame(registros)
