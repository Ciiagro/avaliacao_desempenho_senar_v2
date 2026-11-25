import io
import unicodedata

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from .pdf_timbrado import ALTURA_TIMBRADO, desenhar_timbrado
from .progressao_acompanhamento import GRUPOS

META = {"A": 0.20, "B": 0.65, "C": 0.15}


def _chave_ordem(l):
    """Ordem alfabética pelo nome, ignorando acentos e maiúsculas."""
    nome = unicodedata.normalize("NFKD", l["nome"] or "")
    return "".join(c for c in nome if not unicodedata.combining(c)).casefold()


def gerar_pdf_acompanhamento(dados):
    """PDF no modelo do Resultado Final da empresa (MAT, NOME, ADMISSÃO,
    NOTA, CONCEITO) do último ano do par, com as linhas coloridas conforme
    a situação de progressão, legenda, observações e tabela referência x real."""
    ano = dados["ano"]
    a, b = dados["par"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=ALTURA_TIMBRADO + 0.4 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=styles["Title"], fontSize=14, spaceAfter=2, alignment=1)
    subtitulo = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#16273f"),
        alignment=1, fontName="Helvetica-Bold",
    )
    celula = ParagraphStyle("Celula", parent=styles["Normal"], fontSize=8.5, leading=11)
    celula_nome = ParagraphStyle("CelulaNome", parent=celula, fontName="Helvetica-Bold")
    celula_centro = ParagraphStyle("CelulaCentro", parent=celula, alignment=1)
    celula_cab = ParagraphStyle("CelulaCab", parent=celula_nome, textColor=colors.white, alignment=1)
    obs = ParagraphStyle("Obs", parent=styles["Normal"], fontSize=8, leading=10)

    cores = {g[0]: colors.HexColor(g[3]) for g in GRUPOS}

    story = [
        Paragraph(f"AVALIAÇÃO DE DESEMPENHO - Exercício {b}", titulo),
        Paragraph("RESULTADO FINAL", subtitulo),
        Spacer(1, 12),
    ]

    todos = sorted(dados["todos"], key=_chave_ordem)
    linhas = [[
        Paragraph("MAT", celula_cab), Paragraph("NOME", celula_cab), Paragraph("ADMISSÃO", celula_cab),
        Paragraph("NOTA", celula_cab), Paragraph("CONCEITO", celula_cab),
    ]]
    estilos_cor = []
    contagem = {"A": 0, "B": 0, "C": 0}
    for i, l in enumerate(todos, start=1):
        if l["conceito_b"] in contagem:
            contagem[l["conceito_b"]] += 1
        linhas.append([
            Paragraph(str(l["matricula"] or i), celula_centro),
            Paragraph(l["nome"], celula),
            Paragraph(l["admissao"].strftime("%d/%m/%Y") if l["admissao"] else "-", celula_centro),
            Paragraph(f"{l['nota_b']:.2f}", celula_centro),
            Paragraph(l["conceito_b"] or "-", celula_centro),
        ])

    if len(linhas) == 1:
        story.append(Paragraph(f"Nenhuma avaliação concluída em {b}.", celula))
    else:
        tabela = Table(linhas, colWidths=[1.6 * cm, 8.0 * cm, 3.0 * cm, 2.4 * cm, 2.6 * cm], repeatRows=1)
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16273f")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f6f8")]),
        ]))
        story.append(tabela)
    story.append(Spacer(1, 14))

    total = sum(contagem.values()) or 1
    resumo = [
        [Paragraph("RESULTADO FINAL", celula_nome), "", ""],
        [Paragraph("CONCEITOS", celula_nome), Paragraph("REFERÊNCIA", celula_nome), Paragraph("REAL", celula_nome)],
    ]
    for letra in ("A", "B", "C"):
        resumo.append([
            Paragraph(f"CONCEITO {letra}", celula),
            Paragraph(f"{META[letra] * 100:.0f}%", celula_centro),
            Paragraph(f"{contagem[letra] / total * 100:.0f}%", celula_centro),
        ])
    resumo.append([Paragraph("TOTAL", celula_nome), Paragraph("100%", celula_centro), Paragraph("100%", celula_centro)])
    tab_resumo = Table(resumo, colWidths=[6 * cm, 4 * cm, 4 * cm])
    tab_resumo.setStyle(TableStyle([
        ("SPAN", (0, 0), (2, 0)),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#eef0f4")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#a9c9dd")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    ideal = [
        Paragraph("IDEAL DE ACORDO COM A TABELA DE REFERÊNCIA", obs),
        Paragraph(f"20% A = {round(total * 0.20):02d}", obs),
        Paragraph(f"65% B = {round(total * 0.65):02d}", obs),
        Paragraph(f"15% C = {round(total * 0.15):02d}", obs),
    ]
    story.append(KeepTogether([
        tab_resumo,
        Spacer(1, 10),
    ] + ideal))

    doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    buffer.seek(0)
    return buffer


def gerar_pdf_tabela_progressao(linhas):
    """PDF com a mesma tabela da tela de Progressão de Nível: nome, notas de
    2023/2024/2025, par e decisão/situação. `linhas` já vem com os textos
    prontos (ver admin.exportar_progressao_nivel_pdf)."""
    from datetime import datetime

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=ALTURA_TIMBRADO + 0.4 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=styles["Title"], fontSize=14, spaceAfter=2, alignment=1)
    subtitulo = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#16273f"),
        alignment=1, fontName="Helvetica-Bold",
    )
    celula = ParagraphStyle("Celula", parent=styles["Normal"], fontSize=8.5, leading=11)
    celula_nome = ParagraphStyle("CelulaNome", parent=celula, fontName="Helvetica-Bold")
    celula_centro = ParagraphStyle("CelulaCentro", parent=celula, alignment=1)
    celula_cab = ParagraphStyle("CelulaCab", parent=celula_nome, textColor=colors.white, alignment=1)

    story = [
        Paragraph("PROGRESSÃO DE NÍVEL", titulo),
        Paragraph(f"Posição em {datetime.now().strftime('%d/%m/%Y')}", subtitulo),
        Spacer(1, 12),
    ]

    def nota(v):
        return f"{v:.2f}" if v is not None else "-"

    dados = [[
        Paragraph("NOME", celula_cab), Paragraph("NOTA 2023", celula_cab), Paragraph("NOTA 2024", celula_cab),
        Paragraph("NOTA 2025", celula_cab), Paragraph("PAR", celula_cab), Paragraph("DECISÃO", celula_cab),
    ]]
    for l in linhas:
        dados.append([
            Paragraph(l["nome"], celula),
            Paragraph(nota(l["nota_2023"]), celula_centro),
            Paragraph(nota(l["nota_2024"]), celula_centro),
            Paragraph(nota(l["nota_2025"]), celula_centro),
            Paragraph(l["par"], celula_centro),
            Paragraph(l["decisao"], celula),
        ])

    tabela = Table(dados, colWidths=[5.6 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 2.2 * cm, 5.1 * cm], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16273f")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f6f8")]),
    ]))
    story.append(tabela)

    doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    buffer.seek(0)
    return buffer
