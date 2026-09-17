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
from .utils import formatar_data_local


def gerar_pdf_resultado_final(dados):
    """Gera o PDF do Resultado Final, no mesmo layout da tabulação em Excel:
    tabela de fatores (Auto x Gestor), soma, média, resultado final ponderado
    e conceito (A/B/C)."""
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
    titulo = ParagraphStyle("Titulo", parent=styles["Title"], fontSize=14, spaceAfter=2)
    subtitulo = ParagraphStyle("Subtitulo", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    celula = ParagraphStyle("Celula", parent=styles["Normal"], fontSize=8.5, leading=11)
    celula_nome = ParagraphStyle("CelulaNome", parent=celula, fontName="Helvetica-Bold")
    celula_centro = ParagraphStyle("CelulaCentro", parent=celula, alignment=1)
    celula_cabecalho = ParagraphStyle(
        "CelulaCabecalho", parent=celula_nome, textColor=colors.white
    )

    avaliado = dados["avaliado"]
    ciclo = dados["ciclo"]

    story = [
        Paragraph("Resultado final da avaliação de desempenho", titulo),
        Paragraph(f"{avaliado.nome} &mdash; Exercício {ciclo.exercicio}", subtitulo),
        Spacer(1, 12),
    ]

    linhas = [
        [
            Paragraph("Nº", celula_cabecalho),
            Paragraph("Fator", celula_cabecalho),
            Paragraph("(I) Autoavaliação", celula_cabecalho),
            Paragraph("(II) Avaliação do Gestor", celula_cabecalho),
        ]
    ]
    for fator in dados["fatores"]:
        nota_auto = dados["respostas_auto"].get(fator.id)
        nota_gestor = dados["respostas_gestor"].get(fator.id)
        linhas.append(
            [
                Paragraph(f"{fator.ordem:02d}", celula),
                Paragraph(fator.nome, celula_nome),
                Paragraph(str(nota_auto) if nota_auto is not None else "-", celula_centro),
                Paragraph(str(nota_gestor) if nota_gestor is not None else "-", celula_centro),
            ]
        )

    soma_auto = dados["soma_auto"]
    soma_gestor = dados["soma_gestor"]
    linhas.append(
        [
            "",
            Paragraph("SOMA", celula_nome),
            Paragraph(str(soma_auto) if soma_auto is not None else "-", celula_centro),
            Paragraph(str(soma_gestor) if soma_gestor is not None else "-", celula_centro),
        ]
    )
    media_auto = dados["media_auto"]
    media_gestor = dados["media_gestor"]
    linhas.append(
        [
            "",
            Paragraph(f"MÉDIA (SOMA/{len(dados['fatores'])})", celula_nome),
            Paragraph(f"{media_auto:.2f}" if media_auto is not None else "-", celula_centro),
            Paragraph(f"{media_gestor:.2f}" if media_gestor is not None else "-", celula_centro),
        ]
    )

    tabela_fatores = Table(linhas, colWidths=[1.2 * cm, 8.5 * cm, 3.4 * cm, 3.9 * cm], repeatRows=1)
    tabela_fatores.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16273f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#eef0f4")),
                ("SPAN", (0, -2), (1, -2)),
                ("SPAN", (0, -1), (1, -1)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -3), [colors.white, colors.HexColor("#f5f6f8")]),
            ]
        )
    )
    story.append(tabela_fatores)
    story.append(Spacer(1, 14))

    resultado_final = dados["resultado_final"]
    resultado_texto = f"{resultado_final:.2f}" if resultado_final is not None else "-"
    linhas_resultado = [
        [
            Paragraph("RESULTADO FINAL DA AVALIAÇÃO", celula_nome),
            Paragraph("I x 0,30 + II x 0,70 =", celula),
            Paragraph(resultado_texto, ParagraphStyle("Resultado", parent=celula_nome, fontSize=12, alignment=1)),
        ]
    ]
    tabela_resultado = Table(linhas_resultado, colWidths=[6.5 * cm, 6 * cm, 4.5 * cm])
    tabela_resultado.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(tabela_resultado)
    story.append(Spacer(1, 10))

    conceito = dados["conceito"]

    def marca(letra):
        return "(X)" if conceito == letra else "( )"

    linhas_conceito = [
        [
            Paragraph("CONCEITO", celula_nome),
            Paragraph(f"{marca('A')} A &mdash; entre 10,0 e 8,0 (inclusive)", celula),
        ],
        ["", Paragraph(f"{marca('B')} B &mdash; entre 7,9 e 7,0 (inclusive)", celula)],
        ["", Paragraph(f"{marca('C')} C &mdash; abaixo de 7,0", celula)],
    ]
    tabela_conceito = Table(linhas_conceito, colWidths=[6.5 * cm, 10.5 * cm])
    tabela_conceito.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("SPAN", (0, 0), (0, 2)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(tabela_conceito)
    story.append(Spacer(1, 20))

    avaliacao_gestor = dados["avaliacao_gestor"]
    avaliacao_auto = dados["avaliacao_auto"]

    # ---- Comentários / avaliação subjetiva (autoavaliação e do avaliador) ----
    titulo_secao = ParagraphStyle(
        "TituloSecao", parent=styles["Heading3"], fontSize=11, spaceBefore=0, spaceAfter=4,
        textColor=colors.HexColor("#16273f"),
    )
    rotulo_comentario = ParagraphStyle(
        "RotuloComentario", parent=celula, fontName="Helvetica-Bold", spaceBefore=4, spaceAfter=1,
    )
    texto_comentario = ParagraphStyle("TextoComentario", parent=celula, spaceAfter=4)

    def bloco_comentarios(avaliacao):
        campos = [
            ("Pontos fortes", avaliacao.pontos_fortes if avaliacao else None),
            ("Oportunidades de desenvolvimento", avaliacao.oportunidades_desenvolvimento if avaliacao else None),
            ("Plano de ação", avaliacao.plano_acao if avaliacao else None),
            ("Resultados alcançados", avaliacao.resultados_alcancados if avaliacao else None),
        ]
        elementos = []
        for rotulo, valor in campos:
            elementos.append(Paragraph(rotulo + ":", rotulo_comentario))
            elementos.append(Paragraph((valor or "-").replace("\n", "<br/>"), texto_comentario))
        return elementos

    story.append(Paragraph("Comentários &mdash; Autoavaliação", titulo_secao))
    story.extend(bloco_comentarios(avaliacao_auto))
    story.append(Spacer(1, 10))

    nome_avaliador = avaliacao_gestor.avaliador.nome if avaliacao_gestor else "-"
    story.append(Paragraph(f"Comentários &mdash; Avaliação do gestor ({nome_avaliador})", titulo_secao))
    story.extend(bloco_comentarios(avaliacao_gestor))
    story.append(Spacer(1, 16))

    # ---- Ciência do avaliado ----
    resultado_registro = dados.get("resultado_registro")
    if resultado_registro and resultado_registro.ciente_avaliado and resultado_registro.ciente_em:
        data_ciencia = formatar_data_local(resultado_registro.ciente_em)
        if resultado_registro.decisao_avaliado == "recorreu":
            texto_ciencia = (
                f"O(a) avaliado(a) deu ciência eletrônica do recebimento em {data_ciencia} "
                "e optou por recorrer do resultado."
            )
        else:
            texto_ciencia = (
                f"O(a) avaliado(a) deu ciência eletrônica do recebimento em {data_ciencia} "
                "e concordou com o resultado."
            )
    else:
        texto_ciencia = "Ciência do(a) avaliado(a) ainda não registrada."

    linhas_ciencia = [[Paragraph("Ciência do avaliado:", celula_nome), Paragraph(texto_ciencia, celula)]]
    tabela_ciencia = Table(linhas_ciencia, colWidths=[4.5 * cm, 12.5 * cm])
    tabela_ciencia.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f6f8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(tabela_ciencia)
    story.append(Spacer(1, 16))

    nome_avaliado_assinatura = avaliacao_auto.avaliado.nome if avaliacao_auto else avaliado.nome

    texto_assinatura_avaliador = nome_avaliador
    if avaliacao_gestor and avaliacao_gestor.assinado_em:
        texto_assinatura_avaliador += f" — assinado em {formatar_data_local(avaliacao_gestor.assinado_em)}"

    texto_assinatura_avaliado = nome_avaliado_assinatura
    if resultado_registro and resultado_registro.ciente_avaliado and resultado_registro.ciente_em:
        texto_assinatura_avaliado += f" — assinado em {formatar_data_local(resultado_registro.ciente_em)}"
    else:
        texto_assinatura_avaliado += " — assinatura pendente"

    linhas_assinatura = [
        [Paragraph("Assinatura do Avaliador:", celula_nome), Paragraph(texto_assinatura_avaliador, celula)],
        [Paragraph("Assinatura do Avaliado:", celula_nome), Paragraph(texto_assinatura_avaliado, celula)],
    ]
    tabela_assinatura = Table(linhas_assinatura, colWidths=[4.5 * cm, 12.5 * cm])
    tabela_assinatura.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#cccccc")),
            ]
        )
    )
    story.append(tabela_assinatura)

    doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    buffer.seek(0)
    return buffer


# Metas de referência usadas na planilha da empresa (percentual esperado de
# cada conceito). Mantidas iguais às do excel_resultado_final.py — ajuste os
# dois lugares juntos se a meta mudar de um exercício para outro.
META_CONCEITO_A = 0.20
META_CONCEITO_B = 0.65
META_CONCEITO_C = 0.15


def gerar_pdf_resultado_final_lista(ciclo, linhas, somente_concluidos=True):
    """Gera o PDF consolidado de todos os funcionários do ciclo, no mesmo
    formato da tabulação da empresa: MAT, NOME, ADMISSÃO, NOTA, CONCEITO,
    seguido da tabela de referência x real dos conceitos.

    `linhas` é a mesma lista montada em `admin.montar_linhas_resultado_final`.
    """
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
    celula_cabecalho = ParagraphStyle("CelulaCabecalho", parent=celula_nome, textColor=colors.white, alignment=1)

    story = [
        Paragraph(f"AVALIAÇÃO DE DESEMPENHO - Exercício {ciclo.exercicio}", titulo),
        Paragraph("RESULTADO FINAL", subtitulo),
        Spacer(1, 12),
    ]

    linhas_a_exportar = [l for l in linhas if not somente_concluidos or l["pronto"]]

    tabela_linhas = [
        [
            Paragraph("MAT", celula_cabecalho),
            Paragraph("NOME", celula_cabecalho),
            Paragraph("ADMISSÃO", celula_cabecalho),
            Paragraph("NOTA", celula_cabecalho),
            Paragraph("CONCEITO", celula_cabecalho),
            Paragraph("CIÊNCIA / ASSINATURA", celula_cabecalho),
        ]
    ]

    TEXTO_ASSINATURA = {
        "confirmada": "Confirmada",
        "assinada_recurso": "Assinada (recurso)",
        "recurso_pendente": "Recurso em andamento",
        "pendente": "Pendente",
    }

    contagem_conceitos = {"A": 0, "B": 0, "C": 0}
    for i, linha in enumerate(linhas_a_exportar, start=1):
        f = linha["funcionario"]
        resultado_final = linha["resultado_final"]
        conceito = linha["conceito"]
        if conceito in contagem_conceitos:
            contagem_conceitos[conceito] += 1

        texto_assinatura = TEXTO_ASSINATURA.get(linha.get("assinatura_status"), "Pendente")
        if linha.get("assinatura_em"):
            texto_assinatura += f" ({formatar_data_local(linha['assinatura_em'], com_hora=False)})"

        tabela_linhas.append(
            [
                Paragraph(str(f.matricula or i), celula_centro),
                Paragraph(f.nome, celula),
                Paragraph(
                    f.data_admissao.strftime("%d/%m/%Y") if f.data_admissao else "-", celula_centro
                ),
                Paragraph(f"{resultado_final:.2f}" if resultado_final is not None else "-", celula_centro),
                Paragraph(conceito or "-", celula_centro),
                Paragraph(texto_assinatura, celula_centro),
            ]
        )

    tabela = Table(
        tabela_linhas,
        colWidths=[1.4 * cm, 5.6 * cm, 2.5 * cm, 1.6 * cm, 2.9 * cm, 3.6 * cm],
        repeatRows=1,
    )
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16273f")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f6f8")]),
            ]
        )
    )
    story.append(tabela)
    story.append(Spacer(1, 18))

    total = sum(contagem_conceitos.values()) or 1
    metas = {"A": META_CONCEITO_A, "B": META_CONCEITO_B, "C": META_CONCEITO_C}

    linhas_resumo = [
        [
            Paragraph("RESULTADO FINAL", celula_nome),
            "",
            "",
        ],
        [
            Paragraph("CONCEITOS", celula_nome),
            Paragraph("REFERÊNCIA", celula_nome),
            Paragraph("REAL", celula_nome),
        ],
    ]
    for letra in ("A", "B", "C"):
        real = contagem_conceitos[letra] / total
        linhas_resumo.append(
            [
                Paragraph(f"CONCEITO {letra}", celula),
                Paragraph(f"{metas[letra] * 100:.0f}%", celula_centro),
                Paragraph(f"{real * 100:.0f}%", celula_centro),
            ]
        )
    linhas_resumo.append(
        [
            Paragraph("TOTAL", celula_nome),
            Paragraph("100%", celula_centro),
            Paragraph("100%", celula_centro),
        ]
    )

    tabela_resumo = Table(linhas_resumo, colWidths=[6 * cm, 4 * cm, 4 * cm])
    tabela_resumo.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (2, 0)),
                ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#eef0f4")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#a9c9dd")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(tabela_resumo)

    doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    buffer.seek(0)
    return buffer
