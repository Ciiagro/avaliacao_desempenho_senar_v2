import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .pdf_timbrado import ALTURA_TIMBRADO, desenhar_timbrado
from .utils import formatar_data_local as _formatar_data_local

NOTA_LABEL = {10: "Supera", 8: "Desenvolvimento Pleno", 6: "Em Desenvolvimento", 4: "A Desenvolver"}


def gerar_pdf_avaliacao(avaliacao):
    """Gera o PDF de uma avaliação concluída, no estilo do formulário original."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=ALTURA_TIMBRADO + 0.4 * cm,
        bottomMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
    )

    styles = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=styles["Title"], fontSize=15, spaceAfter=2)
    subtitulo = ParagraphStyle("Subtitulo", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#555555"))
    secao = ParagraphStyle("Secao", parent=styles["Heading2"], fontSize=12, spaceBefore=14, spaceAfter=6)
    rotulo = ParagraphStyle(
        "Rotulo",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=colors.HexColor("#16273f"),
        fontName="Helvetica-Bold",
        spaceBefore=8,
    )
    corpo = ParagraphStyle("Corpo", parent=styles["Normal"], fontSize=10, leading=14)
    celula = ParagraphStyle("Celula", parent=styles["Normal"], fontSize=8.5, leading=11)
    celula_nome = ParagraphStyle("CelulaNome", parent=celula, fontName="Helvetica-Bold")
    celula_cabecalho = ParagraphStyle(
        "CelulaCabecalho", parent=celula_nome, textColor=colors.white, alignment=1, fontSize=6.8, leading=8.2
    )
    celula_marcacao = ParagraphStyle(
        "CelulaMarcacao", parent=celula, alignment=1, fontSize=13, leading=13
    )

    story = []

    story.append(Paragraph("Avaliação de Desempenho", titulo))
    story.append(Paragraph(avaliacao.formulario.nome, subtitulo))
    story.append(Spacer(1, 10))

    tipo_label = "Autoavaliação" if avaliacao.tipo == "auto" else "Avaliação do gestor"
    info_rows = [
        ["Empregado avaliado:", avaliacao.avaliado.nome],
        ["Cargo:", avaliacao.avaliado.cargo.nome if avaliacao.avaliado.cargo else "-"],
        ["Avaliador:", avaliacao.avaliador.nome],
        ["Tipo:", tipo_label],
    ]
    tabela_info = Table(info_rows, colWidths=[4 * cm, 12 * cm])
    tabela_info.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(tabela_info)

    story.append(Paragraph("Parte I &mdash; Fatores de desempenho", secao))

    respostas = {r.fator_id: r.pontuacao for r in avaliacao.respostas}

    # Ordem das opções de nota, da esquerda para a direita (igual ao formulário
    # preenchido pelo avaliador na tela).
    opcoes_nota = [10, 8, 6, 4]

    linhas = [
        [
            Paragraph("Nº", celula_cabecalho),
            Paragraph("Fator", celula_cabecalho),
            *[
                Paragraph(f"{valor} &mdash; {NOTA_LABEL[valor]}", celula_cabecalho)
                for valor in opcoes_nota
            ],
        ]
    ]
    for fator in avaliacao.formulario.fatores:
        nota = respostas.get(fator.id)
        descricao_fator = [
            Paragraph(fator.nome, celula_nome),
            Paragraph(fator.descricao or "", celula),
        ]
        marcacoes = [
            Paragraph("&#9679;" if nota == valor else "", celula_marcacao)
            for valor in opcoes_nota
        ]
        linhas.append(
            [
                Paragraph(f"{fator.ordem:02d}", celula),
                descricao_fator,
                *marcacoes,
            ]
        )

    tabela_fatores = Table(
        linhas,
        colWidths=[1 * cm, 7.6 * cm, 2.3 * cm, 2.3 * cm, 2.3 * cm, 2.3 * cm],
        repeatRows=1,
    )
    tabela_fatores.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#363739")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#646567")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6f6")]),
            ]
        )
    )
    story.append(tabela_fatores)

    story.append(Paragraph("Parte II", secao))

    campos_parte2 = [
        ("Pontos fortes", avaliacao.pontos_fortes),
        ("Oportunidade de desenvolvimento", avaliacao.oportunidades_desenvolvimento),
        ("Plano de desenvolvimento — Ação", avaliacao.plano_acao),
        ("Resultados alcançados durante o ano", avaliacao.resultados_alcancados),
    ]
    for rotulo_texto, valor in campos_parte2:
        story.append(Paragraph(rotulo_texto, rotulo))
        story.append(Paragraph((valor or "-").replace("\n", "<br/>"), corpo))

    story.append(Spacer(1, 20))
    if avaliacao.assinado_por:
        assinatura_texto = (
            f"Assinado eletronicamente por <b>{avaliacao.assinado_por}</b> em "
            f"{_formatar_data_local(avaliacao.assinado_em)}."
        )
    else:
        assinatura_texto = "Avaliação ainda não assinada eletronicamente."
    story.append(Paragraph(assinatura_texto, ParagraphStyle("Assinatura", parent=corpo, textColor=colors.HexColor("#1f5a29"))))

    doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    buffer.seek(0)
    return buffer
