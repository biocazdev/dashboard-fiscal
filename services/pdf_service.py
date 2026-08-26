"""Relatório PDF com a estrutura visual do dashboard fiscal.

Gera um único documento A4 completo, reunindo o conteúdo de todas as abas
da tela (não apenas a aba em que o usuário está no momento do clique):
- Cabeçalho com título, filial, período e a logo da Biocaz.
- Bloco "Movimentação": Faturamento, Entradas, Notas de Saída/Entrada e Ticket Médio.
- Bloco "Tributos": ICMS Saída/Entrada, Saldo de ICMS, IBS/CBS Saída/Entrada
  e PIS/COFINS Saída/Entrada.
- Bloco "Conciliação Fiscal x Contábil": cartões de resumo (conciliados,
  não contabilizados, divergentes, valores e pendência).
- Detalhamento das notas (entradas e saídas) em tabela, quando houver.
- Bloco "Retenções (IR/PIS/COFINS/CSLL)": cartões de resumo e tabela dos
  títulos de contas a pagar com retenção, quando houver.

Dependências: reportlab (ver requirements.txt).
"""

import io
import os
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from utils.formatters import data_brasil, moeda, quantidade

# Paleta institucional (mesma do app.py)
_VERDE = colors.HexColor("#43AA8A")
_AZUL = colors.HexColor("#0C1B7D")
_PRETO = colors.HexColor("#000000")
_CINZA = colors.HexColor("#505050")
_CINZA_CLARO = colors.HexColor("#EBEBEB")
_BORDA = colors.HexColor("#C5C5C5")

_LOGO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logo.png"
)

# Largura útil da página (A4 menos as margens esquerda+direita de 18mm cada,
# as mesmas passadas ao SimpleDocTemplate lá embaixo) - usada para calcular a
# largura das colunas/cartões proporcionalmente, em vez de valores fixos.
_LARGURA_UTIL = A4[0] - 36 * mm


def _estilos() -> dict[str, ParagraphStyle]:
    """Conjunto de estilos de parágrafo usados no relatório."""
    return {
        "titulo": ParagraphStyle(
            name="titulo",
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=20,
            textColor=_AZUL,
        ),
        "subtitulo": ParagraphStyle(
            name="subtitulo",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=_AZUL,
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
        ),
        "info": ParagraphStyle(
            name="info",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=_CINZA,
        ),
        "nota": ParagraphStyle(
            name="nota",
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=_CINZA,
        ),
        "card_rotulo": ParagraphStyle(
            name="card_rotulo",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=_AZUL,
            alignment=TA_CENTER,
        ),
        "card_valor": ParagraphStyle(
            name="card_valor",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=_VERDE,
            alignment=TA_CENTER,
            spaceBefore=2,
        ),
        "cell": ParagraphStyle(
            name="cell",
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=_PRETO,
        ),
        "cell_header": ParagraphStyle(
            name="cell_header",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
        ),
    }


def _card(
    rotulo: str,
    valor: str,
    largura: float,
    estilos: dict[str, ParagraphStyle],
) -> Table:
    """Cria um cartão (caixa com rótulo e valor) no estilo dos cards da tela.

    O reportlab (platypus) não tem um flowable "caixa com borda e duas
    linhas de texto" pronto - o jeito idiomático de conseguir isso é usar
    uma Table de 1 coluna x 2 linhas (rótulo em cima, valor embaixo) com
    ``BOX`` desenhando a borda ao redor. Essa mini-tabela é depois colocada
    lado a lado com outras (uma célula de uma Table maior, nos blocos
    "Movimentação"/"Tributos"/"Retenções"/"Conciliação"), formando a fileira
    de cartões que aparece na tela.
    """
    celula = Table(
        [
            [Paragraph(rotulo, estilos["card_rotulo"])],
            [Paragraph(valor, estilos["card_valor"])],
        ],
        colWidths=[largura],
        style=TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, _BORDA),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        ),
    )
    return celula


def _cabecalho(
    filial: str,
    data_inicial: date,
    data_final: date,
    estilos: dict[str, ParagraphStyle],
    fornecedor: str | None = None,
    cliente: str | None = None,
) -> Table:
    """Cabeçalho do relatório: título, dados do filtro e logo."""
    linha_info = (
        f"Filial <b>{filial}</b> &nbsp;|&nbsp; "
        f"Período: <b>{data_brasil(data_inicial)} a {data_brasil(data_final)}</b>"
    )
    if fornecedor:
        linha_info += f" &nbsp;|&nbsp; Fornecedor: <b>{fornecedor}</b>"
    if cliente:
        linha_info += f" &nbsp;|&nbsp; Cliente: <b>{cliente}</b>"

    esquerda = [
        Paragraph("Dashboard Fiscal", estilos["titulo"]),
        Spacer(1, 2),
        Paragraph(linha_info, estilos["info"]),
    ]

    if os.path.isfile(_LOGO):
        from reportlab.lib.utils import ImageReader

        try:
            # Lê as dimensões originais do arquivo para calcular a largura
            # proporcional à altura fixa desejada (18mm) - evita logo
            # esticada/distorcida se o PNG não tiver a proporção exata
            # assumida.
            largura, altura = ImageReader(_LOGO).getSize()
            altura_alvo = 18 * mm
            largura_alvo = largura * (altura_alvo / altura)
            logo = Image(_LOGO, width=largura_alvo, height=altura_alvo)
            logo.hAlign = "RIGHT"
            cab = Table(
                [[esquerda, logo]],
                colWidths=[_LARGURA_UTIL - 40 * mm, 40 * mm],
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ]
                ),
            )
            return cab
        except Exception:
            # Logo presente mas ilegível/corrompida (ex.: arquivo inválido) -
            # não deve impedir a geração do relatório; cai para o cabeçalho
            # sem logo abaixo.
            pass
    # Sem arquivo de logo (ou falha ao carregá-lo): cabeçalho só com o
    # texto, ocupando a largura útil inteira.
    return Table(
        [[esquerda]],
        colWidths=[_LARGURA_UTIL],
        style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]),
    )


def _bloco_movimentacao(indicadores: dict, estilos) -> Table:
    """Bloco 'Movimentação' com cinco cartões na mesma linha.

    ``indicadores`` é o mesmo dict retornado por
    ``fiscal_service.buscar_indicadores`` usado na tela - o PDF não
    recalcula nada, só reaproveita os valores já apurados para manter os
    dois lugares sempre consistentes.
    """
    largura_card = _LARGURA_UTIL / 5
    cartoes = [
        _card("Faturamento", moeda(indicadores["VALOR_NF_SAIDA"]), largura_card, estilos),
        _card("Entradas", moeda(indicadores["VALOR_NF_ENTRADA"]), largura_card, estilos),
        _card(
            "Notas de Saída",
            quantidade(indicadores["QTD_NF_SAIDA"]),
            largura_card,
            estilos,
        ),
        _card(
            "Notas de Entrada",
            quantidade(indicadores["QTD_NF_ENTRADA"]),
            largura_card,
            estilos,
        ),
        _card("Ticket Médio", moeda(indicadores["TICKET_MEDIO"]), largura_card, estilos),
    ]
    tabela = Table([cartoes], colWidths=[largura_card] * 5)
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tabela


def _bloco_tributos(indicadores: dict, estilos) -> Table:
    """Bloco 'Tributos': ICMS, saldo de ICMS, IBS/CBS e PIS/COFINS (3 linhas de 4).

    São 11 indicadores ao todo, organizados em uma grade de 4 colunas (3
    linhas de 4 cartões) - não há uma ordem imposta pelo negócio além de
    manter ICMS agrupado primeiro (mais relevante) e o saldo logo ao lado
    dos dois valores que o compõem. PIS/COFINS usam ``.get(..., 0.0)``
    porque são calculados só quando os campos nativos de SD1/SD2 existem
    na instalação (podem não vir no dict em bases mais antigas).
    """
    largura_card = _LARGURA_UTIL / 4
    linha1 = [
        _card("ICMS Saída", moeda(indicadores["ICMS_SAIDA"]), largura_card, estilos),
        _card("ICMS Entrada", moeda(indicadores["ICMS_ENTRADA"]), largura_card, estilos),
        _card("Saldo de ICMS", moeda(indicadores["SALDO_ICMS"]), largura_card, estilos),
        _card("IBS Saída", moeda(indicadores["IBS_SAIDA"]), largura_card, estilos),
    ]
    linha2 = [
        _card("CBS Saída", moeda(indicadores["CBS_SAIDA"]), largura_card, estilos),
        _card("IBS Entrada", moeda(indicadores["IBS_ENTRADA"]), largura_card, estilos),
        _card("CBS Entrada", moeda(indicadores["CBS_ENTRADA"]), largura_card, estilos),
        _card("PIS Saída", moeda(indicadores.get("PIS_SAIDA", 0.0)), largura_card, estilos),
    ]
    # 11 cartões não enchem exatamente 3 linhas de 4 (12 células) - a
    # última célula fica como string vazia só para completar a grade;
    # a Table exige que todas as linhas tenham o mesmo número de colunas.
    linha3 = [
        _card("PIS Entrada", moeda(indicadores.get("PIS_ENTRADA", 0.0)), largura_card, estilos),
        _card("COFINS Saída", moeda(indicadores.get("COFINS_SAIDA", 0.0)), largura_card, estilos),
        _card("COFINS Entrada", moeda(indicadores.get("COFINS_ENTRADA", 0.0)), largura_card, estilos),
        "",
    ]
    tabela = Table([linha1, linha2, linha3], colWidths=[largura_card] * 4)
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tabela


def _bloco_detalhamento(detalhe, estilos) -> list:
    """Tabela do detalhamento das notas que compõem os indicadores.

    ``detalhe`` é o DataFrame já filtrado (mesmo filial/período/parceiro
    da tela). Retorna sempre uma *lista* de flowables (nunca um único
    objeto) para poder ser espalhada (``*_bloco_detalhamento(...)``) direto
    na lista de conteúdo do documento em ``gerar_relatorio_pdf`` - sem
    notas, a lista tem só um Paragraph avisando; com notas, só a Table.
    """
    if detalhe is None or detalhe.empty:
        return [Paragraph("Nenhuma nota fiscal no período e filial selecionados.", estilos["info"])]

    colunas = ["Tipo", "Documento", "Série", "Emissão", "Cliente/Fornecedor", "Valor", "ICMS"]
    # Larguras somam _LARGURA_UTIL (20+24+12+22+49+23.5+23.5 = 174mm) -
    # "Cliente/Fornecedor" recebe a maior fatia por ser o texto mais longo
    # e variável da linha.
    larguras = [20 * mm, 24 * mm, 12 * mm, 22 * mm, 49 * mm, 23.5 * mm, 23.5 * mm]

    linhas = [[Paragraph(c, estilos["cell_header"]) for c in colunas]]
    for _, row in detalhe.iterrows():
        linhas.append(
            [
                Paragraph(str(row["TIPO"]), estilos["cell"]),
                Paragraph(str(row["DOC"]).strip(), estilos["cell"]),
                Paragraph(str(row["SERIE"]).strip(), estilos["cell"]),
                Paragraph(data_brasil(row["EMISSAO"]), estilos["cell"]),
                Paragraph(str(row["PARCEIRO"]).strip(), estilos["cell"]),
                Paragraph(moeda(row["VALOR"]), estilos["cell"]),
                Paragraph(moeda(row["ICMS"]), estilos["cell"]),
            ]
        )

    # repeatRows=1 repete a linha de cabeçalho no topo de cada página nova
    # em que a tabela continua, quando o detalhamento é longo o bastante
    # para quebrar página automaticamente.
    tabela = Table(linhas, colWidths=larguras, repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
                # Zebra striping (linhas alternadas branco/cinza claro) só
                # nas linhas de dados (a partir da 1, pulando o cabeçalho),
                # para facilitar a leitura de tabelas longas.
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _CINZA_CLARO]),
                ("GRID", (0, 0), (-1, -1), 0.4, _BORDA),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [tabela]


def _bloco_retencoes(resumo: dict, detalhe, estilos) -> list:
    """Cartões de resumo de retenções (IR/PIS/COFINS/CSLL) e tabela de títulos.

    ``resumo`` traz os totais já agregados (titulos/ir/pis/cofins/csll/
    total) e ``detalhe`` é o DataFrame de ``retencao_service.buscar_retencoes``
    - nenhum cálculo de retenção é refeito aqui, só formatação para PDF.
    Sempre retorna uma lista de flowables (título da seção + cartões +
    total, com ou sem a tabela de títulos ao final) para ser estendida
    direto na lista de conteúdo do documento.
    """
    largura_card = _LARGURA_UTIL / 5
    cartoes = [
        _card("Títulos", str(resumo.get("titulos", 0)), largura_card, estilos),
        _card("IR retido", moeda(resumo.get("ir", 0)), largura_card, estilos),
        _card("PIS retido", moeda(resumo.get("pis", 0)), largura_card, estilos),
        _card("COFINS retido", moeda(resumo.get("cofins", 0)), largura_card, estilos),
        _card("CSLL retido", moeda(resumo.get("csll", 0)), largura_card, estilos),
    ]
    linha1 = Table([cartoes], colWidths=[largura_card] * 5)
    linha1.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    conteudo = [
        Paragraph("Retenções (IR/PIS/COFINS/CSLL)", estilos["subtitulo"]),
        Spacer(1, 2 * mm),
        linha1,
        Spacer(1, 3 * mm),
        Paragraph(f"Total retido: <b>{moeda(resumo.get('total', 0))}</b>", estilos["info"]),
        Spacer(1, 4 * mm),
    ]

    # Sem títulos com retenção no período: encerra o bloco só com os
    # cartões (que mostrarão zero) e o aviso, sem tentar montar a tabela.
    if detalhe is None or detalhe.empty:
        conteudo.append(
            Paragraph(
                "Nenhum título com retenção no período e filial(is) selecionados.",
                estilos["info"],
            )
        )
        return conteudo

    colunas = ["Emissão", "Documento", "Fornecedor", "IR", "PIS", "COFINS", "CSLL", "Total"]
    larguras = [18 * mm, 20 * mm, 42 * mm, 17 * mm, 17 * mm, 17 * mm, 17 * mm, 26 * mm]

    linhas = [[Paragraph(c, estilos["cell_header"]) for c in colunas]]
    for _, row in detalhe.iterrows():
        # NOME_FORNECEDOR pode vir vazio (ver retencao_service - join com
        # SA2 sem componente de loja pode não achar o cadastro); nesse
        # caso mostra só o código em vez de "código - " pendurado.
        _fornecedor_txt = (
            f"{row['FORNECEDOR']} - {row['NOME_FORNECEDOR']}"
            if row.get("NOME_FORNECEDOR")
            else str(row["FORNECEDOR"])
        )
        linhas.append(
            [
                Paragraph(data_brasil(row["EMISSAO"]), estilos["cell"]),
                Paragraph(str(row["DOCUMENTO"]).strip(), estilos["cell"]),
                Paragraph(_fornecedor_txt, estilos["cell"]),
                Paragraph(moeda(row["VALOR_IR"]), estilos["cell"]),
                Paragraph(moeda(row["VALOR_PIS"]), estilos["cell"]),
                Paragraph(moeda(row["VALOR_COFINS"]), estilos["cell"]),
                Paragraph(moeda(row["VALOR_CSLL"]), estilos["cell"]),
                Paragraph(moeda(row["VALOR_TOTAL_RETIDO"]), estilos["cell"]),
            ]
        )

    tabela = Table(linhas, colWidths=larguras, repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _CINZA_CLARO]),
                ("GRID", (0, 0), (-1, -1), 0.4, _BORDA),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    conteudo.append(tabela)
    return conteudo


def _bloco_conciliacao(resumo: dict, estilos) -> list:
    """Cartões de resumo da conciliação fiscal x contábil.

    ``resumo`` é o dict de ``conciliacao_service`` (mesmos totais exibidos
    nos cartões da aba de Conciliação) - reaproveitado sem recálculo. Duas
    linhas de 4 cartões: a primeira com as contagens (total, conciliados,
    não contabilizados, divergentes), a segunda com os valores monetários
    e a pendência (documentos + valor ainda não conciliados).
    """
    largura_card = _LARGURA_UTIL / 4
    pct = resumo.get("pct_conciliado", 0)
    cartoes = [
        _card("Total", str(resumo.get("total", 0)), largura_card, estilos),
        _card("Conciliados", f"{resumo.get('conciliados', 0)}  ({pct:.0%})", largura_card, estilos),
        _card("Não contabilizados", str(resumo.get("nao_contabilizados", 0)), largura_card, estilos),
        _card("Divergentes", str(resumo.get("divergentes", 0)), largura_card, estilos),
    ]
    linha1 = Table([cartoes], colWidths=[largura_card] * 4)
    linha1.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    cartoes2 = [
        _card("Valor Fiscal", moeda(resumo.get("valor_fiscal", 0)), largura_card, estilos),
        _card("Valor Contábil", moeda(resumo.get("valor_contabil", 0)), largura_card, estilos),
        _card("Diferença", moeda(resumo.get("diferenca", 0)), largura_card, estilos),
        _card(
            "Pendência",
            f"{resumo.get('pend_docs', 0)} doc • {moeda(resumo.get('pend_valor', 0))}",
            largura_card,
            estilos,
        ),
    ]
    linha2 = Table([cartoes2], colWidths=[largura_card] * 4)
    linha2.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return [
        Paragraph("Conciliação Fiscal x Contábil", estilos["subtitulo"]),
        Spacer(1, 2 * mm),
        linha1,
        Spacer(1, 3 * mm),
        linha2,
    ]


# Disclaimer técnico impresso no rodapé de toda página do relatório -
# deixa registrado, para quem ler o PDF fora do contexto do dashboard, de
# onde vêm os números e que devem ser validados contra o SX3 da instalação
# (cada Protheus pode ter parametrização própria dos campos fiscais).
_NOTA_GERENCIAL = (
    "Indicadores gerenciais baseados em SF1 (entradas) e SF2 (saídas). "
    "IBS/CBS calculados pelo Configurador de Tributos (F2D); PIS/COFINS via "
    "campos nativos de SD1/SD2. Validar os campos no dicionário de dados "
    "(SX3) da instalação Protheus."
)


def _desenhar_rodape(canvas_obj, numero: int, total: int) -> None:
    """Desenha o rodapé (Biocaz, emissão e paginação) em uma página.

    O rodapé é desenhado pelo canvas (fora do fluxo de conteúdo), portanto
    nunca gera página em branco e aparece em todas as páginas.
    """
    largura, _ = A4
    linha_y = 14 * mm
    texto_y = 9.5 * mm
    nota_y = 6 * mm
    margem = 18 * mm

    canvas_obj.saveState()
    canvas_obj.setStrokeColor(_BORDA)
    canvas_obj.setLineWidth(0.6)
    canvas_obj.line(margem, linha_y, largura - margem, linha_y)

    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(_CINZA)
    canvas_obj.drawString(
        margem, texto_y, "Biocaz  |  Dashboard Fiscal Protheus"
    )

    # Hora de emissão é calculada no momento em que a página é
    # efetivamente desenhada (dentro de _CanvasNumerado.save()), não em
    # que o botão foi clicado - a diferença é de milissegundos, irrelevante
    # aqui.
    emissao = f"Emissão do relatório: {datetime.now():%d/%m/%Y às %H:%M}"
    canvas_obj.drawRightString(largura - margem, texto_y, emissao)

    # Centraliza manualmente o texto de paginação: mede a largura real do
    # texto renderizado nesta fonte/tamanho (stringWidth) e desloca meia
    # largura para a esquerda do centro da página - drawString não tem
    # opção nativa de centralizar em torno de um ponto.
    texto_pagina = f"Página {numero} de {total}"
    centro = largura / 2
    canvas_obj.drawString(
        centro - stringWidth(texto_pagina, "Helvetica", 8) / 2, texto_y, texto_pagina
    )

    canvas_obj.setFont("Helvetica-Oblique", 6.5)
    canvas_obj.setFillColor(_CINZA)
    canvas_obj.drawString(margem, nota_y, _NOTA_GERENCIAL)
    canvas_obj.restoreState()


class _CanvasNumerado(canvas.Canvas):
    """Canvas que grava o estado de cada página para desenhar 'Página X de Y'.

    Truque clássico do reportlab para exibir o total de páginas: no
    momento em que cada página é finalizada, o total ainda é desconhecido
    (o documento pode continuar gerando mais páginas depois). A solução é
    adiar o desenho do rodapé para uma segunda passagem, feita só quando o
    documento inteiro já foi montado e o total de páginas é conhecido.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        # Em vez de finalizar a página de verdade (que já desenharia o
        # conteúdo mas não saberia dizer "de quantas"), guarda uma cópia
        # do estado interno do canvas (__dict__) desta página e começa a
        # próxima - nada é escrito no PDF final ainda.
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        # Só aqui, com o documento inteiro processado, o número total de
        # páginas é conhecido. Restaura o estado salvo de cada página, uma
        # a uma, desenha o rodapé (agora com "Página X de <total>" correto)
        # por cima do conteúdo já preparado, e então finaliza cada página
        # de verdade (super().showPage()) antes de salvar o arquivo.
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            _desenhar_rodape(self, self._pageNumber, total)
            super().showPage()
        super().save()


def gerar_relatorio_pdf(
    filial: str,
    data_inicial: date,
    data_final: date,
    indicadores: dict,
    detalhamento=None,
    fornecedor: str | None = None,
    cliente: str | None = None,
    conciliacao_resumo: dict | None = None,
    retencoes_resumo: dict | None = None,
    retencoes_detalhe=None,
    secao: str = "completo",
) -> bytes:
    """Gera o relatório PDF completo (todas as abas) e retorna o conteúdo em bytes.

    O relatório sempre traz, nesta ordem, o que é exibido em cada aba da tela:
    Movimentação e Tributos (Visão Geral), Conciliação Fiscal x Contábil,
    Detalhamento das notas (Documentos) e Retenções (IR/PIS/COFINS/CSLL) —
    pronto para impressão/visualização de tudo em um único documento.

    Args:
        filial: código da filial consultada.
        data_inicial/data_final: período coberto pelo relatório.
        indicadores: dicionário retornado por ``buscar_indicadores``.
        detalhamento: DataFrame opcional com as notas do período (Documentos).
        fornecedor: código do fornecedor filtrado (opcional).
        cliente: código do cliente filtrado (opcional).
        conciliacao_resumo: dict retornado por ``conciliacao_service.resumo``.
        retencoes_resumo: dict com os totais de retenção (titulos, ir, pis,
            cofins, csll, total).
        retencoes_detalhe: DataFrame retornado por
            ``retencao_service.buscar_retencoes``.
        secao: mantido por compatibilidade; não altera mais o conteúdo do
            relatório (o relatório sempre é gerado completo).

    Returns:
        Conteúdo binário do PDF (pronto para ``st.download_button``).
    """
    estilos = _estilos()

    # `conteudo` é a lista de flowables que o SimpleDocTemplate vai
    # desenhar em sequência, quebrando página automaticamente onde
    # necessário. Convenção usada abaixo: .append() para um único
    # flowable (ou um PageBreak), .extend()/spread (*lista) quando um
    # bloco (_bloco_xxx) devolve uma lista de flowables - nunca aninha uma
    # lista dentro de outra por engano.
    conteudo = [
        # KeepTogether garante que cabeçalho+linha divisória não sejam
        # separados por uma quebra de página automática (ficariam com o
        # título sozinho no topo de uma página e o resto na anterior).
        KeepTogether(
            [
                _cabecalho(filial, data_inicial, data_final, estilos, fornecedor, cliente),
                Spacer(1, 2 * mm),
                HRFlowable(width="100%", thickness=1, color=_BORDA),
                Spacer(1, 2 * mm),
            ]
        ),
    ]

    # Aba "Visão Geral": Movimentação + Tributos. Fica na mesma página do
    # cabeçalho (sem PageBreak antes) porque normalmente cabe inteira.
    conteudo.extend(
        [
            KeepTogether(
                [
                    Paragraph("Movimentação", estilos["subtitulo"]),
                    _bloco_movimentacao(indicadores, estilos),
                ]
            ),
            KeepTogether(
                [
                    Paragraph("Tributos", estilos["subtitulo"]),
                    _bloco_tributos(indicadores, estilos),
                ]
            ),
        ]
    )

    # Cada aba seguinte começa em página nova, com título e primeiro bloco de
    # conteúdo sempre juntos (KeepTogether) - evita título "órfão" no rodapé
    # de uma página com o conteúdo começando isolado na página seguinte.
    # conciliacao_resumo é opcional (None/{} quando a tela não calculou
    # conciliação, ex.: filtro sem dados) - nesse caso a seção inteira
    # (título, cartões e o PageBreak que a antecede) é omitida do PDF, em
    # vez de imprimir uma página só com zeros.
    if conciliacao_resumo:
        conteudo.append(PageBreak())
        conteudo.append(KeepTogether(_bloco_conciliacao(conciliacao_resumo, estilos)))

    # Detalhamento das notas: sempre entra (mesmo vazio, _bloco_detalhamento
    # já devolve um aviso nesse caso) - por isso não tem o mesmo `if` de
    # guarda que a conciliação e as retenções têm.
    conteudo.append(PageBreak())
    conteudo.extend(
        [
            Paragraph("Detalhamento das notas", estilos["subtitulo"]),
            *_bloco_detalhamento(detalhamento, estilos),
        ]
    )

    # `retencoes_resumo or {}` protege _bloco_retencoes de receber None
    # quando a tela não passou o resumo (ex.: chamada antiga/parcial) -
    # com dict vazio, os cartões mostram zero em vez de estourar KeyError.
    conteudo.append(PageBreak())
    conteudo.extend(_bloco_retencoes(retencoes_resumo or {}, retencoes_detalhe, estilos))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Dashboard Fiscal - Relatório Completo - Filial {filial}",
        author="Dashboard Fiscal Protheus",
    )
    # canvasmaker=_CanvasNumerado é o que ativa o rodapé com paginação
    # "Página X de Y" em duas passagens (ver _CanvasNumerado acima) - sem
    # isso, o SimpleDocTemplate usaria o Canvas padrão do reportlab, sem
    # rodapé nenhum.
    doc.build(conteudo, canvasmaker=_CanvasNumerado)
    return buffer.getvalue()
