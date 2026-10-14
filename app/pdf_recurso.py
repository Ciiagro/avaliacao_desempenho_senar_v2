import io
from xml.sax.saxutils import escape

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
from .utils import formatar_data_local, separar_resposta_por_item

AZUL_ITEM = colors.HexColor("#1a5f7a")
FUNDO_ITEM = colors.HexColor("#f3f7f9")


def _texto_pdf(texto):
    """Texto digitado por uma pessoa, seguro pro Paragraph (sem tags soltas)
    e mantendo as quebras de linha."""
    return escape(texto or "-").replace("\n", "<br/>")


def _blocos_por_item(blocos, estilo_titulo, estilo_corpo):
    """Cada item (título + texto) num bloco com barra azul na lateral, igual
    à tela do sistema. `blocos` é uma lista de (título, texto)."""
    elementos = []
    for titulo, texto in blocos:
        conteudo = []
        if titulo:
            conteudo.append([Paragraph(escape(titulo).upper(), estilo_titulo)])
        conteudo.append([Paragraph(_texto_pdf(texto), estilo_corpo)])
        tabela = Table(conteudo, colWidths=[17.8 * cm])
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), FUNDO_ITEM),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, AZUL_ITEM),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, 0), 6),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                ]
            )
        )
        elementos.append(tabela)
        elementos.append(Spacer(1, 5))
    return elementos


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
    titulo_item = ParagraphStyle(
        "TituloItem", parent=celula, fontName="Helvetica-Bold", fontSize=8, textColor=AZUL_ITEM
    )

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
    story.append(Spacer(1, 6))
    itens = [(i.fator.nome, i.motivo) for i in recurso.itens_contestados]
    if itens:
        story.extend(_blocos_por_item(itens, titulo_item, corpo))
    else:
        story.append(Paragraph(_texto_pdf(recurso.motivo), corpo))
    story.append(Spacer(1, 12))

    resposta_gestor = next(
        (e for e in reversed(recurso.eventos) if e.tipo == "resposta_gestor"), None
    )
    repasse = next(
        (e for e in reversed(recurso.eventos) if e.tipo == "repasse_comissao_funcionario"), None
    )
    story.append(Paragraph("Resposta ao recurso", secao))
    # Primeiro a mensagem da Comissão que repassou a resposta; em seguida, a
    # avaliação do gestor (mesma ordem que o empregado vê no sistema).
    if repasse:
        story.append(
            Paragraph(
                f"<b>A Comissão repassou a resposta do gestor</b> em "
                f"{formatar_data_local(repasse.criado_em)}"
                + (f": &ldquo;{_texto_pdf(repasse.texto)}&rdquo;" if repasse.texto else "."),
                corpo,
            )
        )
        story.append(Spacer(1, 8))
    if resposta_gestor:
        decisao_texto = "revisou" if resposta_gestor.decisao == "revisou" else "manteve"
        story.append(
            Paragraph(f"<b>Avaliação do gestor ({decisao_texto})</b>", corpo)
        )
        story.append(Spacer(1, 4))
        nomes = [i.fator.nome for i in recurso.itens_contestados]
        blocos = separar_resposta_por_item(resposta_gestor.texto, nomes)
        if blocos and blocos[0][0]:
            story.extend(_blocos_por_item(blocos, titulo_item, corpo))
        else:
            story.append(Paragraph(_texto_pdf(resposta_gestor.texto), corpo))
    elif not repasse:
        story.append(Paragraph("-", corpo))
    story.append(Spacer(1, 12))

    resultado_final = dados_resultado.get("resultado_final")
    conceito = dados_resultado.get("conceito")
    story.append(Paragraph("Resultado final, após a resposta do gestor ao recurso", secao))
    texto_resultado = (
        f"{resultado_final:.2f} ({conceito})" if resultado_final is not None else "Ainda não disponível."
    )
    story.append(Paragraph(texto_resultado, corpo))
    story.append(Spacer(1, 12))

    # ---- Notas que foram alteradas ----
    if recurso.revisoes_notas:
        story.append(Paragraph("Fatores que foram alterados", secao))
        
        # Cabeçalho da tabela
        dados_tabela = [
            [
                Paragraph("<b>Fator</b>", celula_nome),
                Paragraph("<b>Nota Anterior</b>", celula_nome),
                Paragraph("<b>Nota Nova</b>", celula_nome),
            ]
        ]
        
        # Linhas com os dados
        for rev in recurso.revisoes_notas:
            dados_tabela.append([
                Paragraph(rev.fator.nome, celula),
                Paragraph(str(rev.nota_anterior or "-"), celula),
                Paragraph(f"<b>{rev.nota_nova}</b>", celula),
            ])
        
        tabela_notas = Table(dados_tabela, colWidths=[7 * cm, 4.5 * cm, 4.5 * cm])
        tabela_notas.setStyle(
            TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f5e9")),
                ("BACKGROUND", (2, 1), (2, -1), colors.HexColor("#f1f8e9")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2e7d32")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(tabela_notas)
        story.append(Spacer(1, 18))
    else:
        story.append(Spacer(1, 6))

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
