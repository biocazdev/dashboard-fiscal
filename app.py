"""Dashboard Fiscal Protheus - interface Streamlit.

Responsabilidades (seção 12 da especificação):
- Interface Streamlit, filtros, cards, mensagens de erro e estado da tela.
- Nenhum SQL é montado aqui (ver database/queries.py).
- Nenhuma regra de negócio de cálculo vive aqui (ver services/fiscal_service.py).
"""

import io
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from services import (
    alertas_service,
    anotacoes_service,
    conciliacao_service,
    fiscal_service,
    pdf_service,
    qualidade_service,
    retencao_service,
)
from services.conciliacao_service import StatusConciliacao
from utils.formatters import data_brasil, moeda, quantidade
from utils.logger import configurar_logger

# O Streamlit reexecuta este script inteiro do zero a cada interação do
# usuário (troca de filtro, clique em botão, seleção em gráfico/tabela etc.),
# de cima para baixo. Por isso:
# - ``configurar_logger()`` precisa ter checagem de idempotência (ver
#   utils/logger.py) para não duplicar handlers de log a cada rerun;
# - o estado que precisa sobreviver entre execuções (filtros, seleção de
#   linha/ponto do gráfico, aba ativa etc.) é guardado em
#   ``st.session_state``, e não em variáveis Python comuns, que seriam
#   recriadas do zero a cada rerun;
# - consultas ao banco que não mudam a cada rerun usam ``@st.cache_data``
#   (ver "Camada de cache" logo abaixo) para não bater no SQL Server toda
#   hora.
configurar_logger()

st.set_page_config(
    page_title="Dashboard Fiscal",
    page_icon=":bar_chart:",
    layout="wide",
)

# CSS injetado via st.markdown para sobrescrever o tema padrão do Streamlit
# com a identidade visual da BioCAZ (cores extraídas da logo). Os seletores
# usam os atributos ``data-testid`` que o próprio Streamlit expõe em seus
# componentes internos (sidebar, métricas, botões etc.) - não há como
# estilizar esses elementos de outra forma sem reescrever os widgets.
# Cores institucionais (paleta extraída da logo Biocaz)
_BIOCAZ_VERDE = "#43AA8A"
_BIOCAZ_AZUL = "#0C1B7D"
_BIOCAZ_PRETO = "#000000"
_BIOCAZ_CINZA = "#505050"
_BIOCAZ_CINZA_CLARO = "#EBEBEB"
_BIOCAZ_BORDA = "#C5C5C5"

_CSS = f"""
<style>
    :root {{
        --biocaz-verde: {_BIOCAZ_VERDE};
        --biocaz-azul: {_BIOCAZ_AZUL};
        --biocaz-preto: {_BIOCAZ_PRETO};
        --biocaz-cinza: {_BIOCAZ_CINZA};
        --biocaz-cinza-claro: {_BIOCAZ_CINZA_CLARO};
        --biocaz-borda: {_BIOCAZ_BORDA};
    }}

    .stApp {{
        color: var(--biocaz-preto);
        background-color: #F5F7FB;
    }}

    .stApp h1 {{
        color: var(--biocaz-azul);
        font-weight: 700;
    }}
    .stApp h2,
    .stApp h3 {{
        color: var(--biocaz-azul);
    }}

    [data-testid="stSidebar"] {{
        background-color: #ffffff;
    }}
    [data-testid="stSidebar"] img {{
        padding: 0.5rem 0.5rem 0.25rem 0.5rem;
    }}
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] label {{
        color: var(--biocaz-azul);
        font-weight: 600;
    }}
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span {{
        color: var(--biocaz-preto);
    }}

    .stButton > button,
    .stButton > button[kind="primary"] {{
        background-color: var(--biocaz-verde);
        color: #ffffff;
        border: none;
        border-radius: 8px;
        font-weight: 600;
    }}
    .stButton > button:hover {{
        background-color: var(--biocaz-azul);
        color: #ffffff;
        border: none;
    }}

    [data-testid="stMetric"] {{
        background-color: #ffffff;
        border: 1px solid var(--biocaz-borda);
        border-radius: 10px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
        padding: 14px 16px;
    }}
    [data-testid="stMetricLabel"] p {{
        color: var(--biocaz-azul);
        font-weight: 600;
    }}
    [data-testid="stMetricValue"] {{
        color: var(--biocaz-verde);
    }}

    [data-testid="stCaptionContainer"] {{
        color: var(--biocaz-cinza);
    }}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

st.title("Dashboard Fiscal")


# ---------------------------------------------------------------------------
# Camada de cache (seção 24 da especificação)
# ---------------------------------------------------------------------------
# Cada função abaixo é apenas um wrapper fino em volta de uma função de
# services/*, decorado com ``@st.cache_data``. Isso existe porque o
# Streamlit reexecuta o script inteiro a cada interação: sem cache, TODA
# consulta ao SQL Server (Protheus) rodaria de novo a cada clique, mesmo
# quando filtros/período não mudaram. O ``ttl`` (segundos) varia por
# função: consultas mais "pesadas" ou que mudam pouco (evolução mensal,
# listas de filial/fornecedor/cliente) usam TTL maior; indicadores e
# detalhamento, que o usuário espera ver "quentes", usam TTL menor (~5 min).
# O botão "Atualizar" da sidebar chama ``st.cache_data.clear()`` para forçar
# a releitura antes do TTL expirar.
#
# A conexão com o banco nunca entra no cache (não é hashável e não faria
# sentido cachear); apenas os dados já processados (DataFrames/dicts) são
# cacheados. ``filiais`` é sempre recebida como tupla (e não lista) porque
# argumentos de função cacheada precisam ser hasháveis - listas não são.
@st.cache_data(ttl=300, show_spinner="Consultando os dados fiscais...")
def _indicadores_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
):
    """Cache dos indicadores por filial(is)/período/fornecedor/cliente (~5 min)."""
    return fiscal_service.buscar_indicadores(
        list(filiais), data_inicial, data_final, fornecedor, cliente, tipo_nfe
    )


@st.cache_data(ttl=600)
def _empresas_cached() -> list[str]:
    """Cache da lista de empresas do SM0."""
    return fiscal_service.buscar_empresas()


@st.cache_data(ttl=600)
def _filiais_cached(empresa: str | None) -> list[tuple[str, str]]:
    """Cache da lista de filiais (por empresa)."""
    return fiscal_service.buscar_filiais(empresa)


@st.cache_data(ttl=600)
def _periodo_cached(filiais: tuple[str, ...]) -> tuple[date | None, date | None]:
    """Cache do período (min/max) disponível no banco para as filiais."""
    return fiscal_service.buscar_periodo_disponivel(list(filiais))


@st.cache_data(ttl=600)
def _fornecedores_cached(filiais: tuple[str, ...]) -> list[tuple[str, str]]:
    """Cache dos fornecedores com notas nas filiais."""
    return fiscal_service.buscar_fornecedores(list(filiais))


@st.cache_data(ttl=600)
def _clientes_cached(filiais: tuple[str, ...]) -> list[tuple[str, str]]:
    """Cache dos clientes com notas de saída nas filiais."""
    return fiscal_service.buscar_clientes(list(filiais))


@st.cache_data(ttl=300, show_spinner="Carregando o detalhamento das notas...")
def _detalhamento_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
):
    """Cache das notas que compõem os indicadores (~5 minutos)."""
    return fiscal_service.buscar_detalhamento(
        list(filiais), data_inicial, data_final, fornecedor, cliente, tipo_nfe
    )


@st.cache_data(ttl=300, show_spinner="Conciliando documentos fiscais x contábeis...")
def _conciliacao_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
):
    """Cache da conciliação fiscal x contábil (~5 minutos)."""
    return conciliacao_service.conciliar(
        list(filiais), data_inicial, data_final, fornecedor, cliente
    )


@st.cache_data(ttl=300)
def _sem_origem_cached(filiais: tuple[str, ...], data_inicial: date, data_final: date):
    """Cache dos lançamentos contábeis sem documento fiscal (~5 minutos)."""
    return conciliacao_service.sem_origem_fiscal(
        list(filiais), data_inicial, data_final
    )


@st.cache_data(ttl=300)
def _lotes_saldo_cached(filiais: tuple[str, ...], data_inicial: date, data_final: date):
    """Cache do checklist de lotes contábeis com saldo diferente de zero."""
    return conciliacao_service.lotes_saldo_diferente_zero(
        list(filiais), data_inicial, data_final
    )


@st.cache_data(ttl=300, show_spinner="Consultando CFOP...")
def _cfop_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
):
    """Cache da quebra por CFOP (~5 minutos)."""
    return fiscal_service.buscar_cfop(
        list(filiais), data_inicial, data_final, fornecedor, cliente, tipo_nfe
    )


@st.cache_data(ttl=300)
def _status_documentos_cached(filiais: tuple[str, ...], data_inicial: date, data_final: date):
    """Cache da distribuição de F1_STATUS/F2_STATUS (diagnóstico de cancelamento)."""
    return fiscal_service.buscar_status_documentos(list(filiais), data_inicial, data_final)


@st.cache_data(ttl=600, show_spinner="Consultando a evolução mensal...")
def _evolucao_mensal_cached(
    filiais: tuple[str, ...],
    data_final: date,
    meses: int,
    fornecedor: str | None = None,
    cliente: str | None = None,
    tipo_nfe: str | None = None,
):
    """Cache da evolução mensal de indicadores (~10 minutos, período mais longo)."""
    return fiscal_service.buscar_evolucao_mensal(
        list(filiais), data_final, meses, fornecedor, cliente, tipo_nfe
    )


@st.cache_data(ttl=300, show_spinner="Consultando as retenções...")
def _retencoes_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
):
    """Cache dos títulos de contas a pagar com retenção (~5 minutos)."""
    return retencao_service.buscar_retencoes(
        list(filiais), data_inicial, data_final, fornecedor
    )


@st.cache_data(ttl=300, show_spinner="Consultando retenções geradas no Financeiro...")
def _validacao_financeiro_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
):
    """Cache da validação Retenções x Financeiro (~5 minutos)."""
    return retencao_service.buscar_validacao_financeiro(
        list(filiais), data_inicial, data_final, fornecedor
    )


@st.cache_data(ttl=600)
def _evolucao_mensal_conciliacao_cached(
    filiais: tuple[str, ...],
    data_inicial: date,
    data_final: date,
    fornecedor: str | None = None,
    cliente: str | None = None,
):
    """Cache do % de conciliação mensal (~10 minutos)."""
    return conciliacao_service.evolucao_mensal_conciliacao(
        list(filiais), data_inicial, data_final, fornecedor, cliente
    )


# ---------------------------------------------------------------------------
# Funções auxiliares de apresentação (gráficos, exportação, drill-down)
# ---------------------------------------------------------------------------
# Ficam fora de qualquer aba porque são reaproveitadas por mais de uma seção
# da página (ex.: exportação em Excel é usada tanto no resumo quanto na
# lista de exceções da conciliação).
def _grafico_por_periodo(por_periodo: pd.DataFrame) -> go.Figure:
    """Gráfico de barras empilhadas: conciliação por dia de emissão."""
    fig = go.Figure()
    config_serie = [
        (StatusConciliacao.CONCILIADO, "#43AA8A"),
        (StatusConciliacao.DIVERGENTE, "#F4A261"),
        (StatusConciliacao.NAO_CONTABILIZADO, "#E76F51"),
    ]
    rotulos = {
        StatusConciliacao.CONCILIADO: "Conciliado",
        StatusConciliacao.DIVERGENTE: "Divergente",
        StatusConciliacao.NAO_CONTABILIZADO: "Não contabilizado",
    }
    for status, cor in config_serie:
        if status in por_periodo.columns:
            fig.add_bar(
                x=[d.strftime("%d/%m/%Y") for d in por_periodo.index],
                y=por_periodo[status],
                name=rotulos[status],
                marker_color=cor,
            )
    fig.update_layout(
        barmode="stack",
        height=320,
        legend_title="Status",
        xaxis_title="Emissão",
        yaxis_title="Documentos",
        plot_bgcolor="#F5F7FB",
        paper_bgcolor="#F5F7FB",
        font_color="#000000",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


# Usada tanto para MoM (deslocamento=1, mês anterior) quanto para AoA
# (deslocamento=12, mesmo mês do ano passado) no card de evolução mensal.
def _delta_pct(serie: pd.Series, indice_atual: int, deslocamento: int) -> float | None:
    """Variação % entre ``serie[indice_atual]`` e ``serie[indice_atual - deslocamento]``.

    Retorna ``None`` quando não há histórico suficiente ou o valor de base é zero.
    """
    indice_base = indice_atual - deslocamento
    if indice_base < 0:
        return None
    base = serie.iloc[indice_base]
    atual = serie.iloc[indice_atual]
    if base == 0:
        return None
    return (atual - base) / base


def _grafico_evolucao_mensal(
    df: pd.DataFrame, metricas: list[str], mapa_colunas: dict[str, str]
) -> go.Figure:
    """Gráfico de evolução mensal: barras para valores, linha pontilhada p/ %.

    Usa eixo Y secundário porque "% Conciliado" fica numa escala (0-100)
    totalmente diferente dos valores monetários das demais métricas - se
    ficassem no mesmo eixo, a linha de percentual ficaria achatada perto
    de zero (ou as barras de valor ficariam ilegíveis).
    """
    tem_pct = "% Conciliado" in metricas
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    cores = ["#43AA8A", "#0C1B7D", "#F4A261", "#8AB17D", "#264653", "#E9C46A"]
    x = [d.strftime("%m/%Y") for d in df["MES"]]
    idx_cor = 0
    for rotulo in metricas:
        coluna = mapa_colunas[rotulo]
        if rotulo == "% Conciliado":
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=df[coluna],
                    name=rotulo,
                    mode="lines+markers",
                    line=dict(color="#E76F51", dash="dot"),
                ),
                secondary_y=True,
            )
        else:
            fig.add_trace(
                go.Bar(x=x, y=df[coluna], name=rotulo, marker_color=cores[idx_cor % len(cores)]),
                secondary_y=False,
            )
            idx_cor += 1
    fig.update_layout(
        barmode="group",
        height=360,
        legend_title="Métrica",
        plot_bgcolor="#F5F7FB",
        paper_bgcolor="#F5F7FB",
        font_color="#000000",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    if tem_pct:
        fig.update_yaxes(title_text="% Conciliado", secondary_y=True, range=[0, 100])
    else:
        fig.update_yaxes(visible=False, secondary_y=True)
    return fig


def _excel_conciliacao(
    df_conc: pd.DataFrame, df_sem_origem: pd.DataFrame, resumo: dict
) -> bytes:
    """Gera um Excel (.xlsx) com abas separadas: Resumo, Conciliados, Pendentes, Sem origem."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "Indicador": [
                    "Total de documentos",
                    "Conciliados",
                    "% Conciliado",
                    "Não contabilizados",
                    "Divergentes",
                    "Valor Fiscal",
                    "Valor Contábil",
                    "Diferença",
                    "Pendência (documentos)",
                    "Pendência (valor)",
                    "Tempo médio de contabilização (dias)",
                ],
                "Valor": [
                    resumo.get("total", 0),
                    resumo.get("conciliados", 0),
                    f"{resumo.get('pct_conciliado', 0):.1%}",
                    resumo.get("nao_contabilizados", 0),
                    resumo.get("divergentes", 0),
                    resumo.get("valor_fiscal", 0),
                    resumo.get("valor_contabil", 0),
                    resumo.get("diferenca", 0),
                    resumo.get("pend_docs", 0),
                    resumo.get("pend_valor", 0),
                    resumo.get("tempo_medio_dias") or "-",
                ],
            }
        ).to_excel(writer, sheet_name="Resumo", index=False)

        if df_conc is not None and not df_conc.empty:
            colunas_conc = [
                c
                for c in ["STATUS", "TIPO", "DOC", "SERIE", "PARCEIRO", "EMISSAO",
                          "IDADE_DIAS", "VALOR_FISCAL", "VALOR_CONTABIL", "DIFERENCA", "LOTE"]
                if c in df_conc.columns
            ]
            conciliados = df_conc[df_conc["STATUS"] == StatusConciliacao.CONCILIADO][colunas_conc]
            pendentes = df_conc[
                df_conc["STATUS"].isin(
                    [StatusConciliacao.NAO_CONTABILIZADO, StatusConciliacao.DIVERGENTE]
                )
            ][colunas_conc]
            conciliados.to_excel(writer, sheet_name="Conciliados", index=False)
            pendentes.to_excel(writer, sheet_name="Pendentes", index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name="Conciliados", index=False)
            pd.DataFrame().to_excel(writer, sheet_name="Pendentes", index=False)

        if df_sem_origem is not None and not df_sem_origem.empty:
            colunas_sem = [
                c
                for c in ["TIPO", "DOC", "ORIGEM_ROTULO", "PARCEIRO", "EMISSAO",
                          "IDADE_DIAS", "VALOR_CONTABIL", "LOTE"]
                if c in df_sem_origem.columns
            ]
            df_sem_origem[colunas_sem].to_excel(writer, sheet_name="Sem origem", index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name="Sem origem", index=False)

    return buffer.getvalue()


def _detalhe_documento(linha: pd.Series):
    """Drill-down de um documento: blocos FISCAL, CONTÁBIL, CONCILIAÇÃO e ANOTAÇÃO.

    Usa um container com borda (em vez de expander) porque já fica dentro
    do expander "Documentos" - o Streamlit não permite expander aninhado.
    """
    st.markdown(
        f"**Detalhe do documento {linha['DOC']} - "
        f"{conciliacao_service.rotulo_status(linha['STATUS'])}**"
    )
    with st.container(border=True):
        col_f, col_c, col_k = st.columns(3)
        with col_f:
            st.markdown("**FISCAL**")
            st.markdown(
                f"Tipo: **{linha['TIPO']}**  \n"
                f"Documento: **{linha['DOC']}**  \n"
                f"Série: **{linha['SERIE']}**  \n"
                f"Emissão: **{data_brasil(linha['EMISSAO'])}**  \n"
                f"Parceiro: **{linha['PARCEIRO']}**  \n"
                f"Valor NF: **{moeda(linha['VALOR_FISCAL'])}**"
            )
        with col_c:
            st.markdown("**CONTÁBIL**")
            st.markdown(
                f"Lote: **{linha['LOTE'] or '—'}**  \n"
                f"Data contabilização: **{data_brasil(linha['DATA_CONTABIL']) if linha['DATA_CONTABIL'] else '—'}**  \n"
                f"Valor contábil: **{moeda(linha['VALOR_CONTABIL'])}**  \n"
                f"Lançamentos: **{linha.get('QTDE_LANCAMENTOS', '—')}**"
            )
        with col_k:
            st.markdown("**CONCILIAÇÃO**")
            _idade = linha.get("IDADE_DIAS")
            st.markdown(
                f"Diferença: **{moeda(linha['DIFERENCA'])}**  \n"
                f"Status: **{conciliacao_service.rotulo_status(linha['STATUS'])}**  \n"
                f"Idade: **{f'{int(_idade)} dias' if pd.notna(_idade) else '—'}**"
            )

        st.divider()
        st.markdown("**ANOTAÇÃO** (fica salva só neste computador, não vai para o Protheus)")
        _filial_doc = str(linha.get("FILIAL", "")).strip()
        _tipo_doc = str(linha.get("TIPO", "")).strip()
        _doc_doc = str(linha.get("DOC", "")).strip()
        _serie_doc = str(linha.get("SERIE", "") or "").strip()
        _nota_atual = anotacoes_service.buscar_nota(_filial_doc, _tipo_doc, _doc_doc, _serie_doc)
        # A chave do widget precisa ser única por documento (filial+tipo+doc+
        # série é a chave natural da anotação) para o Streamlit não misturar
        # o texto de um documento com o de outro quando o usuário troca a
        # linha selecionada na tabela.
        _chave_nota = f"nota_{_filial_doc}_{_tipo_doc}_{_doc_doc}_{_serie_doc}"
        _novo_texto = st.text_area(
            "Observação (ex.: \"aguardando NF do fornecedor\")",
            value=_nota_atual["observacao"] if _nota_atual else "",
            key=_chave_nota,
            height=80,
            label_visibility="collapsed",
        )
        col_salvar, col_remover = st.columns([1, 1])
        with col_salvar:
            if st.button("💾 Salvar observação", key=f"salvar_{_chave_nota}"):
                anotacoes_service.salvar_nota(_filial_doc, _tipo_doc, _doc_doc, _serie_doc, _novo_texto)
                st.success("Observação salva.")
        with col_remover:
            if _nota_atual and st.button("🗑️ Remover observação", key=f"remover_{_chave_nota}"):
                anotacoes_service.remover_nota(_filial_doc, _tipo_doc, _doc_doc, _serie_doc)
                st.rerun()
        if _nota_atual:
            st.caption(f"Última edição: {_nota_atual['autor']} em {_nota_atual['atualizado_em']}")


def _render_conciliacao(filiais, data_inicial, data_final, fornecedor, cliente):
    """Aba 'Conciliação Fiscal x Contábil'.

    Compara os documentos fiscais (notas de entrada/saída) com os
    lançamentos contábeis correspondentes, mostrando o que já foi
    contabilizado, o que está divergente e o que ainda não tem lançamento.
    Nota: ``tipo_nfe_param`` não é parâmetro desta função - é lido como
    variável global, definida mais abaixo na sidebar. Isso só funciona
    porque a função só é chamada (na seção de abas) depois que a sidebar já
    rodou e populou essa variável no mesmo rerun do script.
    """
    st.subheader("Conciliação Fiscal x Contábil")

    try:
        df_conc = _conciliacao_cached(
            filiais, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
        )
    except Exception:
        st.error("Não foi possível consultar a conciliação fiscal x contábil.")
        return

    try:
        df_sem_origem = _sem_origem_cached(filiais, data_inicial, data_final)
    except Exception:
        df_sem_origem = pd.DataFrame()

    if df_conc.empty and df_sem_origem.empty:
        st.info("Nenhum documento fiscal no período e filial(is) selecionados.")
        return

    df_todos = pd.concat([df_conc, df_sem_origem], ignore_index=True)

    resumo = conciliacao_service.resumo(df_conc)
    pct = resumo["pct_conciliado"]

    with st.expander("📊 Resumo", expanded=True):
        st.progress(pct, text=f"{pct:.1%} dos documentos conciliados")
        st.caption(
            f"{resumo['conciliados']} de {resumo['total']} documentos com lançamento "
            "contábil dentro da tolerância."
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("✅ Conciliados", f"{resumo['conciliados']}  ({pct:.1%})")
        with col2:
            st.metric("❌ Não contabilizados", resumo["nao_contabilizados"])
        with col3:
            st.metric("⚠️ Divergentes", resumo["divergentes"])
        with col4:
            st.metric("🔍 Sem origem fiscal", len(df_sem_origem))

        col5, col6, col7, col8, col9 = st.columns(5)
        with col5:
            st.metric("Valor Fiscal", moeda(resumo["valor_fiscal"]))
        with col6:
            st.metric("Valor Contábil", moeda(resumo["valor_contabil"]))
        with col7:
            st.metric("Diferença", moeda(resumo["diferenca"]))
        with col8:
            st.metric(
                "Pendência contábil",
                f"{resumo['pend_docs']} doc • {moeda(resumo['pend_valor'])}",
            )
        with col9:
            _tempo_medio = resumo.get("tempo_medio_dias")
            st.metric(
                "⏱️ Prazo médio de contabilização",
                f"{_tempo_medio:.1f} dias" if _tempo_medio is not None else "—",
            )

        st.divider()

        col_excel, _ = st.columns([1, 3])
        with col_excel:
            st.download_button(
                "📊 Baixar Excel completo (Resumo + abas)",
                data=_excel_conciliacao(df_conc, df_sem_origem, resumo),
                file_name=f"conciliacao_{date.today():%Y%m%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # Recalcula df_todos (mesmo resultado do concat acima) porque este bloco
    # fica num expander separado do resumo e usa a variável isoladamente.
    df_todos = pd.concat([df_conc, df_sem_origem], ignore_index=True)

    # Documentos (exceções): oculto por padrão, expande sob demanda.
    with st.expander("📄 Ver documentos (filtrar, buscar e detalhar)", expanded=False):
        # Filtros rápidos: padrão abre em "Com problema" para auditoria
        filtro = st.segmented_control(
            "Status",
            options=[
                "⚠️ Com problema",
                "❌ Não contabilizados",
                "⚠️ Divergentes",
                "✅ Conciliados",
                "🔍 Sem origem fiscal",
                "Todos",
            ],
            default="⚠️ Com problema",
            selection_mode="single",
            key="filtro_conciliacao",
        )
        busca = st.text_input("🔍 Buscar por documento ou parceiro").strip()
        if filtro == "⚠️ Com problema":
            df_filtrado = df_todos[
                df_todos["STATUS"].isin(
                    [StatusConciliacao.NAO_CONTABILIZADO, StatusConciliacao.DIVERGENTE]
                )
            ]
        elif filtro == "❌ Não contabilizados":
            df_filtrado = df_todos[
                df_todos["STATUS"] == StatusConciliacao.NAO_CONTABILIZADO
            ]
        elif filtro == "⚠️ Divergentes":
            df_filtrado = df_todos[df_todos["STATUS"] == StatusConciliacao.DIVERGENTE]
        elif filtro == "✅ Conciliados":
            df_filtrado = df_todos[df_todos["STATUS"] == StatusConciliacao.CONCILIADO]
        elif filtro == "🔍 Sem origem fiscal":
            df_filtrado = df_todos[
                df_todos["STATUS"] == StatusConciliacao.SEM_ORIGEM_FISCAL
            ]
        else:
            df_filtrado = df_todos

        if busca:
            mascara = df_filtrado["DOC"].astype(str).str.contains(
                busca, case=False, regex=False
            ) | df_filtrado["PARCEIRO"].astype(str).str.contains(
                busca, case=False, regex=False
            )
            df_filtrado = df_filtrado[mascara]

        st.markdown(f"**Exceções ({len(df_filtrado)}):**")
        if df_filtrado.empty:
            st.info("Nenhuma exceção para os filtros selecionados.")
        else:
            colunas = [
                c
                for c in [
                    "STATUS",
                    "TIPO",
                    "DOC",
                    "SERIE",
                    "PARCEIRO",
                    "EMISSAO",
                    "IDADE_DIAS",
                    "VALOR_FISCAL",
                    "VALOR_CONTABIL",
                    "DIFERENCA",
                    "LOTE",
                    "ORIGEM_ROTULO",
                ]
                if c in df_filtrado.columns
            ]
            df_exibir = df_filtrado[colunas].rename(
                columns={
                    "STATUS": "Status",
                    "TIPO": "Tipo",
                    "DOC": "Documento",
                    "SERIE": "Série",
                    "PARCEIRO": "Parceiro",
                    "EMISSAO": "Emissão",
                    "IDADE_DIAS": "Idade (dias)",
                    "VALOR_FISCAL": "Valor Fiscal",
                    "VALOR_CONTABIL": "Valor Contábil",
                    "DIFERENCA": "Diferença",
                    "LOTE": "Lote",
                    "ORIGEM_ROTULO": "Origem",
                }
            )
            selecao = st.dataframe(
                df_exibir,
                hide_index=True,
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key="tabela_conciliacao",
                column_config={
                    "Status": st.column_config.TextColumn("Status"),
                    "Emissão": st.column_config.DateColumn("Emissão", format="DD/MM/YYYY"),
                    "Idade (dias)": st.column_config.NumberColumn("Idade (dias)", format="%d"),
                    "Valor Fiscal": st.column_config.NumberColumn(
                        "Valor Fiscal", format="R$ %.2f"
                    ),
                    "Valor Contábil": st.column_config.NumberColumn(
                        "Valor Contábil", format="R$ %.2f"
                    ),
                    "Diferença": st.column_config.NumberColumn("Diferença", format="R$ %.2f"),
                },
            )

            col_dl1, col_dl2, _ = st.columns([1, 1, 2])
            with col_dl1:
                st.download_button(
                    "⬇️ CSV (filtro atual)",
                    data=df_exibir.to_csv(index=False).encode("utf-8-sig"),
                    file_name="conciliacao_excecoes.csv",
                    mime="text/csv",
                    key="csv_excecoes",
                )
            with col_dl2:
                _buf_excel = io.BytesIO()
                df_exibir.to_excel(_buf_excel, index=False, engine="openpyxl")
                st.download_button(
                    "⬇️ Excel (filtro atual)",
                    data=_buf_excel.getvalue(),
                    file_name="conciliacao_excecoes.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="xlsx_excecoes",
                )

            if selecao.selection.rows and selecao.selection.rows[0] < len(df_filtrado):
                linha = df_filtrado.iloc[selecao.selection.rows[0]]
                _detalhe_documento(linha)

    st.divider()

    # Checklist de qualidade dos dados
    with st.expander("🔎 Checklist de qualidade dos dados", expanded=False):
        try:
            _detalhe_qualidade = _detalhamento_cached(
                filiais, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
            )
        except Exception:
            _detalhe_qualidade = pd.DataFrame()

        duplicadas = qualidade_service.notas_duplicadas(_detalhe_qualidade)
        invalidas = qualidade_service.notas_valor_invalido(_detalhe_qualidade)
        try:
            lotes = _lotes_saldo_cached(filiais, data_inicial, data_final)
        except Exception:
            lotes = pd.DataFrame()

        col_q1, col_q2, col_q3 = st.columns(3)
        with col_q1:
            st.metric("📑 Notas duplicadas", len(duplicadas))
        with col_q2:
            st.metric("🚫 Valor zerado/negativo", len(invalidas))
        with col_q3:
            st.metric("⚖️ Lotes CT2 com saldo ≠ 0", len(lotes))

        if not duplicadas.empty:
            st.markdown("**Notas duplicadas** (mesma filial + tipo + documento + série):")
            st.dataframe(duplicadas, hide_index=True, use_container_width=True)
        if not invalidas.empty:
            st.markdown("**Notas com valor zerado ou negativo:**")
            st.dataframe(invalidas, hide_index=True, use_container_width=True)
        if not lotes.empty:
            st.markdown("**Lotes contábeis (CT2) com saldo diferente de zero:**")
            st.dataframe(lotes, hide_index=True, use_container_width=True)
        if duplicadas.empty and invalidas.empty and lotes.empty:
            st.success("Nenhum problema encontrado nas checagens disponíveis.")

        st.divider()
        st.markdown("**Status das notas (F1_STATUS / F2_STATUS)**")
        try:
            _status_docs = _status_documentos_cached(filiais, data_inicial, data_final)
        except Exception:
            _status_docs = pd.DataFrame()
        if not _status_docs.empty:
            st.dataframe(
                _status_docs.rename(columns={"TIPO": "Tipo", "STATUS": "Status", "QTD": "Qtd."}),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Sem notas no período para levantar a distribuição de status.")

    st.divider()

    # Análise por período
    st.subheader("Análise por período")
    por_periodo = conciliacao_service.resumo_por_periodo(df_conc)
    if por_periodo.empty:
        st.info("Sem dados por período.")
    else:
        # ``on_select="rerun"`` faz o Streamlit reexecutar o script quando o
        # usuário clica numa barra, devolvendo o(s) ponto(s) clicado(s) em
        # ``_sel.selection``. Isso permite um clique no gráfico funcionar
        # como um filtro "drill-down" para a tabela de documentos abaixo.
        _sel = st.plotly_chart(
            _grafico_por_periodo(por_periodo),
            use_container_width=True,
            on_select="rerun",
            key="grafico_conciliacao",
        )

        if _sel and _sel.selection and _sel.selection.points:
            _ponto = _sel.selection.points[0]
            _data_str = _ponto.get("x", "")
            if _data_str:
                try:
                    from datetime import datetime as _dt

                    _data_cli = _dt.strptime(_data_str, "%d/%m/%Y").date()
                except ValueError:
                    _data_cli = None
                else:
                    # A seleção do gráfico só existe durante o rerun do
                    # clique (o Plotly não "lembra" sozinho). Por isso ela é
                    # guardada em session_state: assim a data clicada
                    # continua filtrando a tabela mesmo depois que o usuário
                    # interage com outro widget e a página roda de novo.
                    st.session_state["data_grafico_selecionada"] = _data_cli

        _data_sel = st.session_state.get("data_grafico_selecionada")

        if _data_sel:
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.info(
                    f"📅 Documentos do dia **{data_brasil(_data_sel)}** — "
                    "clique novamente na mesma barra ou em \"Limpar\" para remover."
                )
            with col_btn:
                if st.button("✕ Limpar", key="limpar_grafico"):
                    st.session_state.pop("data_grafico_selecionada", None)
                    st.rerun()

            _df_dia = df_todos[df_todos["EMISSAO"] == _data_sel].copy()
            if not _df_dia.empty:
                st.dataframe(
                    _df_dia[
                        [
                            "STATUS",
                            "TIPO",
                            "DOC",
                            "SERIE",
                            "PARCEIRO",
                            "VALOR_FISCAL",
                            "VALOR_CONTABIL",
                            "DIFERENCA",
                        ]
                    ].rename(
                        columns={
                            "STATUS": "Status",
                            "TIPO": "Tipo",
                            "DOC": "Documento",
                            "SERIE": "Série",
                            "PARCEIRO": "Parceiro",
                            "VALOR_FISCAL": "Valor Fiscal",
                            "VALOR_CONTABIL": "Valor Contábil",
                            "DIFERENCA": "Diferença",
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Status": st.column_config.TextColumn("Status"),
                        "Valor Fiscal": st.column_config.NumberColumn(
                            "Valor Fiscal", format="R$ %.2f"
                        ),
                        "Valor Contábil": st.column_config.NumberColumn(
                            "Valor Contábil", format="R$ %.2f"
                        ),
                        "Diferença": st.column_config.NumberColumn(
                            "Diferença", format="R$ %.2f"
                        ),
                    },
                )
            else:
                st.info("Nenhum documento fiscal para este dia.")

        st.caption(
            "Conciliação por dia de emissão. Clique em uma barra para ver os "
            "documentos daquele dia. Uma queda do percentual conciliado revela "
            "quando a contabilização parou."
        )


# ---------------------------------------------------------------------------
# Barra lateral - filtros
# ---------------------------------------------------------------------------
# Monta, em cascata, os filtros que controlam todo o resto da página:
# Empresa -> Filial -> Fornecedor/Cliente -> Tipo de NF-e -> Período. Cada
# nível só é exibido quando o nível anterior já tem uma seleção válida
# (ex.: não faz sentido listar fornecedores antes de escolher a filial),
# e as opções de cada combo vêm de consultas cacheadas (`_*_cached`) para
# não bater no banco a cada rerun. Os valores widgets com ``key=`` ficam
# automaticamente espelhados em ``st.session_state`` pelo próprio
# Streamlit, o que é usado abaixo para detectar mudança de filial e limpar
# filtros que dependiam da filial anterior.
with st.sidebar:
    st.image("logo.png", use_container_width=True)

    st.header("Filtros")
    st.caption("Período baseado na data de emissão das notas.")

    # Empresa (seção 31)
    try:
        empresas = _empresas_cached()
    except Exception:
        empresas = []

    if empresas:
        empresa = st.selectbox("Empresa", options=empresas)
    else:
        empresa = st.text_input("Empresa (código, opcional)").strip()

    # Filial (seção 30) - múltipla escolha para permitir visão consolidada
    try:
        filiais_disponiveis = _filiais_cached(empresa or None)
    except Exception:
        filiais_disponiveis = []

    if filiais_disponiveis:
        opcoes_filiais = {
            codigo: (f"{codigo} - {nome}" if nome and nome != codigo else codigo)
            for codigo, nome in filiais_disponiveis
        }
        lista_codigos = list(opcoes_filiais.keys())
        # Evita erro do multiselect se a filial salva em sessão não existir
        # mais nas opções atuais (ex.: usuário trocou de empresa).
        if "filiais" in st.session_state:
            st.session_state["filiais"] = [
                f for f in st.session_state["filiais"] if f in lista_codigos
            ]
        filiais_selecionadas = st.multiselect(
            "Filial",
            options=lista_codigos,
            format_func=opcoes_filiais.get,
            default=lista_codigos[:1],
            key="filiais",
            help="Selecione mais de uma filial para uma visão consolidada.",
        )
    else:
        filiais_texto = st.text_input(
            "Filial (código, opcional - separe várias por vírgula)"
        ).strip()
        filiais_selecionadas = [f.strip() for f in filiais_texto.split(",") if f.strip()]

    _filiais_atual = tuple(filiais_selecionadas)

    # Quando a(s) filial(is) mudam, zera as datas, o fornecedor e o cliente.
    # Sem isso, ao trocar de filial o usuário ficaria vendo um fornecedor/
    # período que fazia sentido para a filial anterior, mas pode nem existir
    # (ou ter outro significado) na nova - "_filiais_anterior" é uma chave
    # de controle em session_state (não um widget) só para lembrar, entre um
    # rerun e outro, qual era a seleção de filial da última vez.
    if st.session_state.get("_filiais_anterior") != _filiais_atual:
        st.session_state.pop("data_inicial", None)
        st.session_state.pop("data_final", None)
        st.session_state.pop("fornecedor", None)
        st.session_state.pop("cliente", None)
        st.session_state["_filiais_anterior"] = _filiais_atual

    # Fornecedor (filtra as notas de entrada por F1_FORNECE)
    fornecedor: str | None = None
    if _filiais_atual:
        try:
            fornecedores = _fornecedores_cached(_filiais_atual)
        except Exception:
            fornecedores = []

        if fornecedores:
            opcoes_fornecedores = {"Todos": None}
            for codigo, nome in fornecedores:
                rotulo = f"{codigo} - {nome}" if nome and nome != codigo else codigo
                opcoes_fornecedores[rotulo] = codigo
            rotulo_fornecedor = st.selectbox(
                "Fornecedor",
                options=list(opcoes_fornecedores.keys()),
                key="fornecedor",
            )
            fornecedor = opcoes_fornecedores[rotulo_fornecedor]
        else:
            fornecedor_texto = st.text_input("Fornecedor (código, opcional)").strip()
            fornecedor = fornecedor_texto or None

    # Cliente (filtra as notas de saída por F2_CLIENTE)
    cliente: str | None = None
    if _filiais_atual:
        try:
            clientes = _clientes_cached(_filiais_atual)
        except Exception:
            clientes = []

        if clientes:
            opcoes_clientes = {"Todos": None}
            for codigo, nome in clientes:
                rotulo = f"{codigo} - {nome}" if nome and nome != codigo else codigo
                opcoes_clientes[rotulo] = codigo
            rotulo_cliente = st.selectbox(
                "Cliente",
                options=list(opcoes_clientes.keys()),
                key="cliente",
            )
            cliente = opcoes_clientes[rotulo_cliente]
        else:
            cliente_texto = st.text_input("Cliente (código, opcional)").strip()
            cliente = cliente_texto or None

    # Tipo de NF-e: filtra por Entrada ou Saída
    tipo_nfe = st.selectbox(
        "Tipo de NF-e",
        options=["Todos", "Entrada", "Saída"],
        key="tipo_nfe",
    )
    tipo_nfe_param = None if tipo_nfe == "Todos" else tipo_nfe

    # Período: datas disponíveis no banco para as filiais selecionadas
    hoje = date.today()
    if _filiais_atual:
        try:
            data_min_db, data_max_db = _periodo_cached(_filiais_atual)
        except Exception:
            data_min_db = data_max_db = None
    else:
        data_min_db = data_max_db = None

    if data_min_db and data_max_db:
        st.caption(
            f"Período disponível no banco: "
            f"{data_brasil(data_min_db)} a {data_brasil(data_max_db)}"
        )
        # Ajusta os limites para não ultrapassar hoje nos inputs
        data_inicial_padrao = min(data_min_db, hoje)
        data_final_padrao = min(data_max_db, hoje)
    else:
        data_inicial_padrao = hoje.replace(year=hoje.year - 1)
        data_final_padrao = hoje

    if data_inicial_padrao > data_final_padrao:
        data_inicial_padrao = data_final_padrao

    # Corrige valores salvos em sessão que ficaram fora do novo intervalo.
    # Necessário porque ``st.date_input`` com ``key=`` reusa o valor salvo
    # em session_state entre reruns; se o usuário trocou de filial/empresa
    # e o período disponível no banco mudou, a data antiga poderia ficar
    # fora dos novos limites min/max e o widget quebraria.
    for _chave, _padrao, _chk_min, _chk_max in (
        ("data_inicial", data_inicial_padrao, None, hoje),
        ("data_final", data_final_padrao, data_inicial_padrao, hoje),
    ):
        if _chave in st.session_state:
            _val = st.session_state[_chave]
            if (_chk_min is not None and _val < _chk_min) or _val > _chk_max:
                st.session_state[_chave] = _padrao

    data_inicial = st.date_input(
        "Data inicial",
        value=data_inicial_padrao,
        max_value=hoje,
        format="DD/MM/YYYY",
        key="data_inicial",
    )
    data_final = st.date_input(
        "Data final",
        value=data_final_padrao,
        min_value=data_inicial,
        max_value=hoje,
        format="DD/MM/YYYY",
        key="data_final",
    )

    atualizar = st.button("Atualizar", type="primary", use_container_width=True)

    if atualizar:
        # Força a releitura do banco mesmo dentro do TTL do cache - útil
        # quando o contador sabe que algo mudou no Protheus e não quer
        # esperar os ~5/10 minutos de cache expirarem sozinhos.
        st.cache_data.clear()
        st.session_state.pop("pdf_pronto", None)

    if st.button("📥 Gerar relatório em PDF", use_container_width=True):
        _filial_pdf = ", ".join(_filiais_atual) if _filiais_atual else ""
        with st.spinner("Gerando o relatório..."):
            # Indicadores e detalhamento são buscados direto em
            # fiscal_service (sem passar pelo wrapper cacheado) para
            # garantir que o PDF sempre reflita os filtros atuais no
            # instante do clique, sem depender do estado do cache; já a
            # conciliação e as retenções abaixo reaproveitam o cache porque
            # normalmente já foram consultadas ao renderizar as outras
            # abas nesse mesmo rerun.
            _ind = fiscal_service.buscar_indicadores(
                list(_filiais_atual), data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
            )
            _det = fiscal_service.buscar_detalhamento(
                list(_filiais_atual), data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
            )
            _conc_df = _conciliacao_cached(
                _filiais_atual, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
            )
            _conc_resumo = conciliacao_service.resumo(_conc_df)

            _ret_df = _retencoes_cached(_filiais_atual, data_inicial, data_final, fornecedor)
            _ret_resumo = {
                "titulos": len(_ret_df),
                "ir": _ret_df["VALOR_IR"].sum() if not _ret_df.empty else 0,
                "pis": _ret_df["VALOR_PIS"].sum() if not _ret_df.empty else 0,
                "cofins": _ret_df["VALOR_COFINS"].sum() if not _ret_df.empty else 0,
                "csll": _ret_df["VALOR_CSLL"].sum() if not _ret_df.empty else 0,
                "total": _ret_df["VALOR_TOTAL_RETIDO"].sum() if not _ret_df.empty else 0,
            }

            _pdf_bytes = pdf_service.gerar_relatorio_pdf(
                filial=_filial_pdf,
                data_inicial=data_inicial,
                data_final=data_final,
                fornecedor=fornecedor,
                cliente=cliente,
                indicadores=_ind,
                detalhamento=_det,
                conciliacao_resumo=_conc_resumo,
                retencoes_resumo=_ret_resumo,
                retencoes_detalhe=_ret_df,
            )
        _nome_pdf = f"RelFiscal_{date.today():%d_%m_%Y}.pdf"
        st.success(f"Relatório **{_nome_pdf}** gerado com sucesso!")
        st.sidebar.download_button(
            "📥 Baixar PDF",
            data=_pdf_bytes,
            file_name=_nome_pdf,
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )

    st.divider()
    if st.button("🗑️ Limpar filtros", use_container_width=True):
        # Os widgets acima já foram desenhados neste rerun com os valores
        # antigos de session_state; só apagar as chaves não muda o que já
        # está na tela. Por isso o ``st.rerun()`` é necessário: ele força
        # um novo rerun do zero, e aí os widgets voltam a ler os valores
        # padrão (já que as chaves não existem mais em session_state).
        for _k in (
            "fornecedor",
            "cliente",
            "data_inicial",
            "data_final",
            "data_grafico_selecionada",
            "tipo_nfe",
        ):
            st.session_state.pop(_k, None)
        st.rerun()


# ---------------------------------------------------------------------------
# Validações dos filtros
# ---------------------------------------------------------------------------
# ``st.stop()`` interrompe a execução do script neste ponto - nada abaixo
# (cards, abas, gráficos) chega a rodar. É a forma idiomática do Streamlit
# de "sair mais cedo" numa página que roda de cima para baixo a cada
# interação, evitando que o restante do código tente usar filtros
# inválidos/incompletos.
if not _filiais_atual:
    st.warning("Selecione ao menos uma filial para visualizar os indicadores.")
    st.stop()

if data_inicial > data_final:
    st.error("A data inicial não pode ser maior que a data final.")
    st.stop()


# ---------------------------------------------------------------------------
# Consulta dos indicadores
# ---------------------------------------------------------------------------
# Esta é a consulta "principal": os indicadores agregados (faturamento,
# tributos etc.) usados nos cards da aba Visão Geral. Fica fora de qualquer
# aba porque também alimenta a legenda de filtros logo abaixo e os alertas.
# O try/except cobre falha de conexão com o SQL Server (banco fora do ar,
# credenciais erradas no .env etc.) e mostra uma mensagem amigável em vez
# de deixar o traceback estourar na tela do usuário.
try:
    indicadores = _indicadores_cached(
        _filiais_atual, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
    )
except Exception:
    st.error("Não foi possível consultar os dados fiscais.")
    st.caption("Verifique a conexão com o banco e as configurações do arquivo .env.")
    st.stop()

if not indicadores:
    st.info("Nenhum registro encontrado para os filtros selecionados.")
    st.stop()

if len(_filiais_atual) == 1:
    _rotulo_filiais = f"Filial {_filiais_atual[0]}"
else:
    _rotulo_filiais = f"{len(_filiais_atual)} filiais ({', '.join(_filiais_atual)})"

_legenda_filtros = f"{_rotulo_filiais} | {data_brasil(data_inicial)} a {data_brasil(data_final)}"
if fornecedor:
    _legenda_filtros += f" | Fornecedor {fornecedor}"
if cliente:
    _legenda_filtros += f" | Cliente {cliente}"
st.caption(_legenda_filtros)

sem_registros = (
    indicadores["QTD_NF_ENTRADA"] == 0 and indicadores["QTD_NF_SAIDA"] == 0
)

# ---------------------------------------------------------------------------
# Alertas visuais (semáforo) - limites configuráveis no .env
# ---------------------------------------------------------------------------
# Reaproveita consultas já cacheadas (conciliação e detalhamento) para
# montar uma lista de alertas (críticos em vermelho, atenção em amarelo)
# sobre a saúde dos dados do período: documentos não conciliados acima do
# limite, notas duplicadas, valores inválidos etc. A regra de quando algo
# vira alerta e o nível de severidade fica em alertas_service (não aqui) -
# esta seção só decide como exibir o que o serviço já calculou.
try:
    _df_conc_alertas = _conciliacao_cached(
        _filiais_atual, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
    )
except Exception:
    _df_conc_alertas = pd.DataFrame()
_resumo_alertas = conciliacao_service.resumo(_df_conc_alertas)

try:
    _detalhe_alertas = _detalhamento_cached(
        _filiais_atual, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
    )
except Exception:
    _detalhe_alertas = pd.DataFrame()

_alertas = alertas_service.montar_alertas(
    indicadores=indicadores,
    resumo_conciliacao=_resumo_alertas,
    df_conciliacao=_df_conc_alertas,
    qtd_duplicadas=len(qualidade_service.notas_duplicadas(_detalhe_alertas)),
    qtd_invalidas=len(qualidade_service.notas_valor_invalido(_detalhe_alertas)),
)
if _alertas:
    _qtd_criticos = sum(1 for _a in _alertas if _a["nivel"] == "critico")
    _qtd_atencao = len(_alertas) - _qtd_criticos
    _icone_resumo = "🔴" if _qtd_criticos else "🟡"
    _plural = "alerta" if len(_alertas) == 1 else "alertas"
    _label_resumo = f"{_icone_resumo} {len(_alertas)} {_plural}"
    if _qtd_criticos:
        _label_resumo += f" ({_qtd_criticos} crítico(s))"
    with st.expander(_label_resumo, expanded=False):
        for _alerta in _alertas:
            if _alerta["nivel"] == "critico":
                st.error(f"🔴 {_alerta['mensagem']}")
            else:
                st.warning(f"🟡 {_alerta['mensagem']}")

st.divider()

# ---------------------------------------------------------------------------
# Abas: Visão Geral | Conciliação Fiscal x Contábil | Documentos | Retenções
# | Retenções x Financeiro
# ---------------------------------------------------------------------------
# Cada bloco ``with tab_*:`` abaixo grava a aba atual em
# ``st.session_state["aba_ativa"]``. Isso já foi usado no passado para o
# botão de PDF decidir o que incluir no relatório conforme a aba em que o
# usuário estava; hoje o PDF sempre inclui conciliação e retenções
# independente da aba (ver DOCUMENTACAO.md, seção 13), então essa chave
# ficou sem leitor - mantida aqui por não ter custo e por poder voltar a
# ser útil (ex.: lembrar a última aba visitada entre reruns).
tab_visao, tab_conciliacao, tab_documentos, tab_retencoes, tab_val_financeiro = st.tabs(
    [
        "📊 Visão Geral",
        "🔄 Conciliação Fiscal x Contábil",
        "📄 Documentos",
        "🧾 Retenções",
        "🏦 Retenções x Financeiro",
    ]
)

# ------------------------------- Visão Geral -------------------------------
# Painel de indicadores agregados do período: volume de notas de entrada/
# saída, tributos (ICMS, IBS/CBS, PIS/COFINS), quebra por CFOP e evolução
# mensal comparativa. Não mostra documento a documento (isso fica na aba
# "Documentos") - é a foto resumida para quem quer só o panorama fiscal.
with tab_visao:
    st.session_state["aba_ativa"] = "visao_geral"
    st.subheader("Movimentação")

    _qtd_e = indicadores["QTD_NF_ENTRADA"]
    _qtd_s = indicadores["QTD_NF_SAIDA"]
    _qtd_total = _qtd_e + _qtd_s
    _pct_e = (_qtd_e / _qtd_total * 100) if _qtd_total else 0
    _pct_s = (_qtd_s / _qtd_total * 100) if _qtd_total else 0
    with st.expander("📊 Movimentação", expanded=True):
        st.markdown(
            f"🟢 Entrada: **{_qtd_e}** ({_pct_e:.0f}%) &nbsp;|&nbsp; "
            f"🔵 Saída: **{_qtd_s}** ({_pct_s:.0f}%)"
        )

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("💰 Faturamento", moeda(indicadores["VALOR_NF_SAIDA"]))
        with col2:
            st.metric("🛒 Entradas", moeda(indicadores["VALOR_NF_ENTRADA"]))
        with col3:
            st.metric("🚚 Notas de Saída", quantidade(indicadores["QTD_NF_SAIDA"]))
        with col4:
            st.metric("📦 Notas de Entrada", quantidade(indicadores["QTD_NF_ENTRADA"]))
        with col5:
            st.metric("📊 Ticket Médio", moeda(indicadores["TICKET_MEDIO"]))

    with st.expander("🏛️ Tributos", expanded=True):
        col6, col7, col8, col9 = st.columns(4)
        with col6:
            st.metric("🧾 ICMS Saída", moeda(indicadores["ICMS_SAIDA"]))
        with col7:
            st.metric("🧾 ICMS Entrada", moeda(indicadores["ICMS_ENTRADA"]))
        with col8:
            st.metric("⚖️ Saldo de ICMS", moeda(indicadores["SALDO_ICMS"]))
        with col9:
            st.metric("🏛️ IBS Saída", moeda(indicadores["IBS_SAIDA"]))

        col10, col11, col12, col13 = st.columns(4)
        with col10:
            st.metric("🏦 CBS Saída", moeda(indicadores["CBS_SAIDA"]))
        with col11:
            st.metric("🏛️ IBS Entrada", moeda(indicadores["IBS_ENTRADA"]))
        with col12:
            st.metric("🏦 CBS Entrada", moeda(indicadores["CBS_ENTRADA"]))
        with col13:
            st.metric("📗 PIS Saída", moeda(indicadores["PIS_SAIDA"]))

        col14, col15, col16 = st.columns(3)
        with col14:
            st.metric("📗 PIS Entrada", moeda(indicadores["PIS_ENTRADA"]))
        with col15:
            st.metric("📘 COFINS Saída", moeda(indicadores["COFINS_SAIDA"]))
        with col16:
            st.metric("📘 COFINS Entrada", moeda(indicadores["COFINS_ENTRADA"]))

    with st.expander("📋 CFOP (natureza das operações)", expanded=False):
        try:
            df_cfop = _cfop_cached(
                _filiais_atual, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
            )
        except Exception:
            st.warning("Não foi possível consultar a quebra por CFOP.")
            df_cfop = pd.DataFrame()

        if df_cfop.empty:
            st.info("Nenhum CFOP encontrado no período e filial(is) selecionados.")
        else:
            st.dataframe(
                df_cfop.rename(
                    columns={
                        "TIPO": "Tipo",
                        "CFOP": "CFOP",
                        "QTD_NOTAS": "Notas",
                        "QTD_ITENS": "Itens",
                        "VALOR_TOTAL": "Valor Total",
                    }
                ),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Valor Total": st.column_config.NumberColumn(
                        "Valor Total", format="R$ %.2f"
                    ),
                },
            )

    with st.expander("📈 Evolução mensal (comparativo)", expanded=False):
        col_meses, col_metricas = st.columns([1, 2])
        with col_meses:
            _meses_sel = st.selectbox(
                "Período",
                options=[6, 12, 24],
                index=1,
                format_func=lambda n: f"Últimos {n} meses",
                key="evolucao_meses",
            )
        # Mapa "rótulo exibido" -> "nome da coluna no DataFrame". As colunas
        # com prefixo "_" (IBS+CBS, PIS+COFINS, % Conciliado) não existem no
        # retorno de fiscal_service - são calculadas logo abaixo, somando
        # colunas já existentes, só para agrupar métricas correlatas num
        # único item de seleção (o usuário pensa em "IBS+CBS", não em duas
        # métricas separadas).
        _metricas_opcoes = {
            "Faturamento (saída)": "VALOR_NF_SAIDA",
            "Entradas": "VALOR_NF_ENTRADA",
            "ICMS Saída": "ICMS_SAIDA",
            "ICMS Entrada": "ICMS_ENTRADA",
            "IBS+CBS Saída": "_IBS_CBS_SAIDA",
            "IBS+CBS Entrada": "_IBS_CBS_ENTRADA",
            "PIS+COFINS Saída": "_PIS_COFINS_SAIDA",
            "PIS+COFINS Entrada": "_PIS_COFINS_ENTRADA",
            "% Conciliado": "_PCT_CONCILIADO",
        }
        with col_metricas:
            _metricas_sel = st.multiselect(
                "Métricas",
                options=list(_metricas_opcoes.keys()),
                default=["Faturamento (saída)", "Entradas"],
                key="evolucao_metricas",
            )

        try:
            _df_evo = _evolucao_mensal_cached(
                _filiais_atual, data_final, _meses_sel, fornecedor, cliente, tipo_nfe_param
            )
        except Exception:
            st.warning("Não foi possível consultar a evolução mensal.")
            _df_evo = pd.DataFrame()

        if _df_evo.empty:
            st.info("Sem dados suficientes para montar a evolução mensal.")
        elif not _metricas_sel:
            st.info("Selecione ao menos uma métrica para ver o gráfico.")
        else:
            _df_evo = _df_evo.copy()
            _df_evo["_IBS_CBS_SAIDA"] = _df_evo["IBS_SAIDA"] + _df_evo["CBS_SAIDA"]
            _df_evo["_IBS_CBS_ENTRADA"] = _df_evo["IBS_ENTRADA"] + _df_evo["CBS_ENTRADA"]
            _df_evo["_PIS_COFINS_SAIDA"] = _df_evo["PIS_SAIDA"] + _df_evo["COFINS_SAIDA"]
            _df_evo["_PIS_COFINS_ENTRADA"] = _df_evo["PIS_ENTRADA"] + _df_evo["COFINS_ENTRADA"]

            # O % de conciliação mensal vem de uma consulta separada (mais
            # cara, cruza fiscal x contábil mês a mês) e só é buscada quando
            # o usuário realmente pede essa métrica - evita o custo extra
            # de consultar conciliação todo mês quando ninguém vai olhar.
            if "% Conciliado" in _metricas_sel:
                _janela_ini, _janela_fim = fiscal_service.janela_evolucao_mensal(
                    data_final, _meses_sel
                )
                try:
                    _df_pct_mensal = _evolucao_mensal_conciliacao_cached(
                        _filiais_atual, _janela_ini, _janela_fim, fornecedor, cliente
                    )
                except Exception:
                    _df_pct_mensal = pd.DataFrame()
                # "ANOMES" (ex.: 202601) é a chave comum entre as duas
                # consultas - usada para juntar o % de conciliação de cada
                # mês aos indicadores mensais sem precisar de um merge de
                # DataFrame completo.
                _pct_dict = (
                    dict(zip(_df_pct_mensal["ANOMES"], _df_pct_mensal["PCT_CONCILIADO"]))
                    if not _df_pct_mensal.empty
                    else {}
                )
                _df_evo["_PCT_CONCILIADO"] = _df_evo["ANOMES"].map(
                    lambda a: _pct_dict.get(a, 0.0) * 100
                )
            else:
                _df_evo["_PCT_CONCILIADO"] = 0.0

            st.plotly_chart(
                _grafico_evolucao_mensal(_df_evo, _metricas_sel, _metricas_opcoes),
                use_container_width=True,
                key="grafico_evolucao_mensal",
            )

            _idx_ultimo = len(_df_evo) - 1
            _cols_delta = st.columns(len(_metricas_sel))
            for _col, _rotulo in zip(_cols_delta, _metricas_sel):
                with _col:
                    _coluna = _metricas_opcoes[_rotulo]
                    _valor_atual = _df_evo[_coluna].iloc[_idx_ultimo]
                    _delta_mom = _delta_pct(_df_evo[_coluna], _idx_ultimo, 1)
                    _delta_yoy = _delta_pct(_df_evo[_coluna], _idx_ultimo, 12)
                    _texto_valor = (
                        f"{_valor_atual:.1f}%" if _rotulo == "% Conciliado" else moeda(_valor_atual)
                    )
                    st.metric(
                        _rotulo,
                        _texto_valor,
                        delta=f"{_delta_mom:+.0%} vs mês anterior" if _delta_mom is not None else None,
                    )
                    if _delta_yoy is not None:
                        st.caption(f"{_delta_yoy:+.0%} vs mesmo mês ano passado")
            st.caption(
                "MoM = variação em relação ao mês anterior. AoA (mesmo mês ano "
                "passado) só aparece quando o período selecionado cobre 13+ meses."
            )

    if sem_registros:
        st.info("Nenhuma nota fiscal encontrada no período e filial(is) selecionados.")

# ------------------------- Conciliação Fiscal x Contábil -------------------------
with tab_conciliacao:
    st.session_state["aba_ativa"] = "conciliacao"
    _render_conciliacao(_filiais_atual, data_inicial, data_final, fornecedor, cliente)

# -------------------------------- Documentos --------------------------------
# Lista "crua" de notas de entrada e saída do período (uma linha por nota),
# sem cruzar com contabilidade - é o extrato para quem quer conferir/
# exportar o detalhamento fiscal em si, diferente da aba de Conciliação
# (que já compara fiscal x contábil).
with tab_documentos:
    st.session_state["aba_ativa"] = "documentos"
    with st.expander("Ver detalhamento das notas (entradas e saídas)"):
        try:
            detalhe = _detalhamento_cached(
                _filiais_atual, data_inicial, data_final, fornecedor, cliente, tipo_nfe_param
            )
        except Exception:
            st.warning("Não foi possível carregar o detalhamento das notas.")
            detalhe = None

        if detalhe is not None and not detalhe.empty:
            st.dataframe(
                detalhe,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "TIPO": "Tipo",
                    "DOC": "Documento",
                    "SERIE": "Série",
                    "EMISSAO": st.column_config.DateColumn(
                        "Emissão", format="DD/MM/YYYY"
                    ),
                    "PARCEIRO": "Cliente/Fornecedor",
                    "LOJA_PARCEIRO": "Loja",
                    "VALOR": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "ICMS": st.column_config.NumberColumn("ICMS", format="R$ %.2f"),
                },
            )

            col_csv, col_xlsx, col_meta = st.columns([1, 1, 2])
            with col_csv:
                st.download_button(
                    "Baixar CSV",
                    data=detalhe.to_csv(index=False).encode("utf-8-sig"),
                    file_name="detalhamento_notas.csv",
                    mime="text/csv",
                )
            with col_xlsx:
                _buf_det = io.BytesIO()
                detalhe.to_excel(_buf_det, index=False, engine="openpyxl")
                st.download_button(
                    "Baixar Excel",
                    data=_buf_det.getvalue(),
                    file_name="detalhamento_notas.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with col_meta:
                total_entrada = detalhe.loc[
                    detalhe["TIPO"] == "Entrada", "VALOR"
                ].sum()
                total_saida = detalhe.loc[detalhe["TIPO"] == "Saida", "VALOR"].sum()
                st.caption(
                    f"Total de entradas: {moeda(total_entrada)} | "
                    f"Total de saídas: {moeda(total_saida)}"
                )
        elif detalhe is not None:
            st.info("Nenhuma nota encontrada no período e filial(is) selecionados.")

# -------------------------------- Retenções ---------------------------------
# Mostra os títulos de contas a pagar (fornecedor) que tiveram IR/PIS/
# COFINS/CSLL retidos na fonte - só isso, sem checar se a retenção já foi
# efetivamente gerada/paga no módulo financeiro (essa checagem é a próxima
# aba, "Retenções x Financeiro").
with tab_retencoes:
    st.session_state["aba_ativa"] = "retencoes"
    st.subheader("Retenções sobre pagamentos a fornecedores PJ")

    try:
        df_retencoes = _retencoes_cached(_filiais_atual, data_inicial, data_final, fornecedor)
    except Exception:
        st.warning("Não foi possível consultar as retenções.")
        df_retencoes = pd.DataFrame()

    if df_retencoes.empty:
        st.info(
            "Nenhum título com retenção de IR/PIS/COFINS/CSLL encontrado no "
            "período e filial(is) selecionados."
        )
    else:
        with st.expander("📊 Resumo", expanded=True):
            col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns(5)
            with col_r1:
                st.metric("💼 Títulos", quantidade(len(df_retencoes)))
            with col_r2:
                st.metric("🧾 IR retido", moeda(df_retencoes["VALOR_IR"].sum()))
            with col_r3:
                st.metric("📗 PIS retido", moeda(df_retencoes["VALOR_PIS"].sum()))
            with col_r4:
                st.metric("📘 COFINS retido", moeda(df_retencoes["VALOR_COFINS"].sum()))
            with col_r5:
                st.metric("🏛️ CSLL retido", moeda(df_retencoes["VALOR_CSLL"].sum()))
            st.metric("💰 Total retido", moeda(df_retencoes["VALOR_TOTAL_RETIDO"].sum()))

        with st.expander("📋 Ver títulos com retenção", expanded=False):
            rotulo_fornecedor_retencao = df_retencoes.apply(
                lambda r: f"{r['FORNECEDOR']} - {r['NOME_FORNECEDOR']}"
                if r["NOME_FORNECEDOR"]
                else r["FORNECEDOR"],
                axis=1,
            )
            df_exibir_retencoes = df_retencoes.assign(FORNECEDOR_ROTULO=rotulo_fornecedor_retencao)[
                [
                    "EMISSAO", "DOCUMENTO", "FORNECEDOR_ROTULO", "CNPJ", "NATUREZA", "COD_R",
                    "BASE_IR", "VALOR_IR", "BASE_PIS", "VALOR_PIS",
                    "BASE_COFINS", "VALOR_COFINS", "BASE_CSLL", "VALOR_CSLL",
                    "VALOR_TOTAL_RETIDO",
                ]
            ]

            st.dataframe(
                df_exibir_retencoes,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "EMISSAO": st.column_config.DateColumn("Emissão", format="DD/MM/YYYY"),
                    "DOCUMENTO": "Documento",
                    "FORNECEDOR_ROTULO": "Fornecedor",
                    "CNPJ": "CNPJ/CPF",
                    "NATUREZA": "Natureza",
                    "COD_R": "Cod. R",
                    "BASE_IR": st.column_config.NumberColumn("IR Base", format="R$ %.2f"),
                    "VALOR_IR": st.column_config.NumberColumn("IR Valor", format="R$ %.2f"),
                    "BASE_PIS": st.column_config.NumberColumn("PIS Base", format="R$ %.2f"),
                    "VALOR_PIS": st.column_config.NumberColumn("PIS", format="R$ %.2f"),
                    "BASE_COFINS": st.column_config.NumberColumn("COFINS Base", format="R$ %.2f"),
                    "VALOR_COFINS": st.column_config.NumberColumn("COFINS", format="R$ %.2f"),
                    "BASE_CSLL": st.column_config.NumberColumn("CSLL Base", format="R$ %.2f"),
                    "VALOR_CSLL": st.column_config.NumberColumn("CSLL", format="R$ %.2f"),
                    "VALOR_TOTAL_RETIDO": st.column_config.NumberColumn("Total Retido", format="R$ %.2f"),
                },
            )

            col_csv_ret, col_xlsx_ret, col_meta_ret = st.columns([1, 1, 2])
            with col_csv_ret:
                st.download_button(
                    "Baixar CSV",
                    data=df_exibir_retencoes.to_csv(index=False).encode("utf-8-sig"),
                    file_name="retencoes.csv",
                    mime="text/csv",
                )
            with col_xlsx_ret:
                _buf_ret = io.BytesIO()
                df_exibir_retencoes.to_excel(_buf_ret, index=False, engine="openpyxl")
                st.download_button(
                    "Baixar Excel",
                    data=_buf_ret.getvalue(),
                    file_name="retencoes.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with col_meta_ret:
                st.caption(f"{len(df_retencoes)} título(s) com retenção no período.")

# --------------------------- Retenções x Financeiro ---------------------------
# Para cada título com retenção (aba anterior), verifica se o Protheus
# realmente gerou o título "irmão" de imposto no Financeiro e se ele já foi
# baixado (pago). É o cruzamento que revela retenção calculada mas nunca
# recolhida - ver a lógica de status em retencao_service.
with tab_val_financeiro:
    st.session_state["aba_ativa"] = "validacao_financeiro"
    st.subheader("Retenções x Financeiro")

    try:
        df_val_fin = _validacao_financeiro_cached(
            _filiais_atual, data_inicial, data_final, fornecedor
        )
    except Exception:
        st.warning("Não foi possível consultar a validação Retenções x Financeiro.")
        df_val_fin = pd.DataFrame()

    if df_val_fin.empty:
        st.info(
            "Nenhum título com retenção de IR/PIS/COFINS/CSLL encontrado no "
            "período e filial(is) selecionados."
        )
    else:
        _qtd_ok = int((df_val_fin["STATUS"] == retencao_service._STATUS_OK).sum())
        _qtd_aguardando = int(
            (df_val_fin["STATUS"] == retencao_service._STATUS_AGUARDANDO_BAIXA).sum()
        )
        _qtd_divergente = int((df_val_fin["STATUS"] == retencao_service._STATUS_DIVERGENTE).sum())
        _qtd_nao_gerado = int((df_val_fin["STATUS"] == retencao_service._STATUS_NAO_GERADO).sum())

        with st.expander("📊 Resumo", expanded=True):
            col_v1, col_v2, col_v3, col_v4, col_v5 = st.columns(5)
            with col_v1:
                st.metric("💼 Títulos com retenção", quantidade(len(df_val_fin)))
            with col_v2:
                st.metric("🔴 Não gerado no Financeiro", quantidade(_qtd_nao_gerado))
            with col_v3:
                st.metric("🟡 Divergente", quantidade(_qtd_divergente))
            with col_v4:
                st.metric("🔵 Aguardando baixa", quantidade(_qtd_aguardando))
            with col_v5:
                st.metric("🟢 OK", quantidade(_qtd_ok))
            st.caption(
                "Cada retenção (IR/PIS/COFINS/CSLL) é gerada pelo Protheus como "
                "um título \"irmão\" na própria SE2010 (mesmo número, tipo TX), "
                "com baixa própria - independente da baixa do título original. "
                "🔴 Não gerado = nenhum título de taxa encontrado ainda. "
                "🟡 Divergente = encontrado, mas o valor não bate com o retido. "
                "🔵 Aguardando baixa = gerado e o valor bate, só falta pagar - "
                "não é tratado como problema. 🟢 OK = gerado, valor batendo e já pago."
            )

        with st.expander("📋 Ver títulos e status", expanded=False):
            filtro_val_fin = st.segmented_control(
                "Status",
                options=[
                    "⚠️ Com problema",
                    "🔴 Não gerado",
                    "🟡 Divergente",
                    "🔵 Aguardando baixa",
                    "🟢 OK",
                    "Todos",
                ],
                default="⚠️ Com problema",
                selection_mode="single",
                key="filtro_validacao_financeiro",
            )
            if filtro_val_fin == "⚠️ Com problema":
                df_val_fin_filtrado = df_val_fin[
                    df_val_fin["STATUS"].isin(
                        [
                            retencao_service._STATUS_NAO_GERADO,
                            retencao_service._STATUS_DIVERGENTE,
                        ]
                    )
                ]
            elif filtro_val_fin == "🔴 Não gerado":
                df_val_fin_filtrado = df_val_fin[
                    df_val_fin["STATUS"] == retencao_service._STATUS_NAO_GERADO
                ]
            elif filtro_val_fin == "🟡 Divergente":
                df_val_fin_filtrado = df_val_fin[
                    df_val_fin["STATUS"] == retencao_service._STATUS_DIVERGENTE
                ]
            elif filtro_val_fin == "🔵 Aguardando baixa":
                df_val_fin_filtrado = df_val_fin[
                    df_val_fin["STATUS"] == retencao_service._STATUS_AGUARDANDO_BAIXA
                ]
            elif filtro_val_fin == "🟢 OK":
                df_val_fin_filtrado = df_val_fin[
                    df_val_fin["STATUS"] == retencao_service._STATUS_OK
                ]
            else:
                df_val_fin_filtrado = df_val_fin

            rotulo_fornecedor_val_fin = df_val_fin_filtrado.apply(
                lambda r: f"{r['FORNECEDOR']} - {r['NOME_FORNECEDOR']}"
                if r["NOME_FORNECEDOR"]
                else r["FORNECEDOR"],
                axis=1,
            )
            df_exibir_val_fin = df_val_fin_filtrado.assign(
                FORNECEDOR_ROTULO=rotulo_fornecedor_val_fin
            )[
                [
                    "EMISSAO", "DOCUMENTO", "FORNECEDOR_ROTULO",
                    "VALOR_TITULO", "VALOR_RETIDO", "VALOR_LIQUIDO_ESPERADO",
                    "QTD_TITULOS_RETENCAO", "VALOR_GERADO_FINANCEIRO",
                    "QTD_BAIXADOS", "DATA_ULTIMA_BAIXA", "DIFERENCA",
                    "STATUS",
                ]
            ]

            st.dataframe(
                df_exibir_val_fin,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "EMISSAO": st.column_config.DateColumn("Emissão", format="DD/MM/YYYY"),
                    "DOCUMENTO": "Documento",
                    "FORNECEDOR_ROTULO": "Fornecedor",
                    "VALOR_TITULO": st.column_config.NumberColumn("Valor Título", format="R$ %.2f"),
                    "VALOR_RETIDO": st.column_config.NumberColumn("Total Retido", format="R$ %.2f"),
                    "VALOR_LIQUIDO_ESPERADO": st.column_config.NumberColumn(
                        "Líquido Esperado", format="R$ %.2f"
                    ),
                    "QTD_TITULOS_RETENCAO": "Qtd. Retenções Geradas",
                    "VALOR_GERADO_FINANCEIRO": st.column_config.NumberColumn(
                        "Valor Gerado no Financeiro", format="R$ %.2f"
                    ),
                    "QTD_BAIXADOS": "Qtd. Já Baixadas",
                    "DATA_ULTIMA_BAIXA": st.column_config.DateColumn(
                        "Última Baixa", format="DD/MM/YYYY"
                    ),
                    "DIFERENCA": st.column_config.NumberColumn("Diferença", format="R$ %.2f"),
                    "STATUS": "Status",
                },
            )

            col_csv_vf, col_xlsx_vf, col_meta_vf = st.columns([1, 1, 2])
            with col_csv_vf:
                st.download_button(
                    "Baixar CSV",
                    data=df_exibir_val_fin.to_csv(index=False).encode("utf-8-sig"),
                    file_name="retencoes_x_financeiro.csv",
                    mime="text/csv",
                )
            with col_xlsx_vf:
                _buf_vf = io.BytesIO()
                df_exibir_val_fin.to_excel(_buf_vf, index=False, engine="openpyxl")
                st.download_button(
                    "Baixar Excel",
                    data=_buf_vf.getvalue(),
                    file_name="retencoes_x_financeiro.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with col_meta_vf:
                st.caption(f"{len(df_exibir_val_fin)} de {len(df_val_fin)} título(s) exibido(s).")
