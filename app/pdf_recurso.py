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


def gerar_pdf_recurso(recurso, dados_resultado):
    """Gera o comprovante em PDF de um recurso encerrado: motivo aberto
    pelo empregado, resposta do gestor, resultado final já refletindo
    qualquer revisão de nota feita durante o recurso, e a assinatura
    eletrônica do empregado confirmando que recebeu essa resposta (o único
    passo que ele tem depois que a Comissão repassa — não há mais recorrer
    a uma instância seguinte)."""
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
    titulo = ParagraphStyle("Titulo", parent=styles["Title"], fontSize=15, spaceAfter=2)
    subtitulo = ParagraphStyle(
        "Subtitulo", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#555555")
    )
    secao = ParagraphStyle("Secao", parent=styles["Heading2"], fontSize=12, spaceBefore=14, spaceAfter=6)
    corpo = ParagraphStyle("Corpo", parent=styles["Normal"], fontSize=10, leading=14)
    celula = ParagraphStyle("Celula", parent=styles["Normal"], fontSize=9, leading=13)
    celula_nome = ParagraphStyle("CelulaNome", parent=celula, fontName="Helvetica-Bold")

    story = []

    story.append(Paragraph("Recurso da Avaliação de Desempenho", titulo))
    story.append(
        Paragraph(f"Exercício {recurso.ciclo.exercicio} &mdash; {recurso.avaliado.nome}", subtitulo)
    )
    story.append(Spacer(1, 14))

    story.append(Paragraph("Motivo do recurso, aberto pelo empregado", secao))
    story.append(
        Paragraph(
            f"Aberto em {formatar_data_local(recurso.criado_em)}. Resultado contestado: "
            f"{recurso.resultado_final_em_texto or '-'}.",
            corpo,
        )
    )
    story.append(Spacer(1, 4))
    story.append(Paragraph((recurso.motivo or "-").replace("\n", "<br/>"), corpo))
    story.append(Spacer(1, 12))

    resposta_gestor = next(
        (e for e in reversed(recurso.eventos) if e.tipo == "resposta_gestor"), None
    )
    story.append(Paragraph("Resposta do gestor", secao))
    if resposta_gestor:
        decisao_texto = (
            "revisou a avaliação" if resposta_gestor.decisao == "revisou" else "manteve a avaliação"
        )
        story.append(
            Paragraph(
                f"O gestor {decisao_texto} em {formatar_data_local(resposta_gestor.criado_em)}:",
                corpo,
            )
        )
        story.append(Spacer(1, 4))
        story.append(Paragraph((resposta_gestor.texto or "-").replace("\n", "<br/>"), corpo))
    else:
        story.append(Paragraph("-", corpo))
    story.append(Spacer(1, 12))

    resultado_final = dados_resultado.get("resultado_final")
    conceito = dados_resultado.get("conceito")
    story.append(Paragraph("Resultado final, após a resposta do gestor ao recurso", secao))
    texto_resultado = (
        f"{resultado_final:.2f} ({conceito})" if resultado_final is not None else "Ainda não disponível."
    )
    story.append(Paragraph(texto_resultado, corpo))
    story.append(Spacer(1, 18))

    # ---- Assinatura eletrônica do empregado ----
    if recurso.ciente_funcionario and recurso.ciente_funcionario_em:
        texto_assinatura = (
            f"{recurso.avaliado.nome} confirmou o recebimento desta resposta e assinou "
            f"eletronicamente em {formatar_data_local(recurso.ciente_funcionario_em)}, "
            "encerrando definitivamente o recurso."
        )
    else:
        texto_assinatura = "Assinatura eletrônica do empregado ainda não registrada."

    linhas_assinatura = [
        [Paragraph("Assinatura do empregado:", celula_nome), Paragraph(texto_assinatura, celula)]
    ]
    tabela_assinatura = Table(linhas_assinatura, colWidths=[4.5 * cm, 12.5 * cm])
    tabela_assinatura.setStyle(
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
    story.append(tabela_assinatura)

    doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    buffer.seek(0)
    return buffer
