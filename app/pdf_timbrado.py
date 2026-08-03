import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm

# Caminho do logo extraído do timbrado oficial (word/media/image1.jpeg do timbrado.docx)
LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "img", "logo_senar.png")

VERDE_SENAR = colors.HexColor("#00B050")
AZUL_TEXTO = colors.HexColor("#16273f")

# Altura reservada no topo da página para o timbrado (ajuste o topMargin do
# SimpleDocTemplate para pelo menos esse valor).
ALTURA_TIMBRADO = 2.6 * cm


def desenhar_timbrado(canvas, doc):
    """Callback onPage do SimpleDocTemplate: desenha o cabeçalho timbrado
    (logo + texto institucional) no topo de cada página.

    Uso:
        doc.build(story, onFirstPage=desenhar_timbrado, onLaterPages=desenhar_timbrado)
    """
    canvas.saveState()

    largura_pagina, altura_pagina = A4

    # --- Logo ---
    logo_largura = 3.6 * cm
    logo_altura = logo_largura * (195 / 625)  # proporção original da imagem
    logo_x = doc.leftMargin
    logo_y = altura_pagina - 1.2 * cm - logo_altura

    if os.path.exists(LOGO_PATH):
        canvas.drawImage(
            LOGO_PATH,
            logo_x,
            logo_y,
            width=logo_largura,
            height=logo_altura,
            preserveAspectRatio=True,
            mask="auto",
        )

    # --- Texto institucional ao lado do logo ---
    texto_x = logo_x + logo_largura + 0.4 * cm
    texto_y = logo_y + logo_altura / 2 + 0.15 * cm

    canvas.setFont("Helvetica-Bold", 12)
    canvas.setFillColor(VERDE_SENAR)
    canvas.drawString(texto_x, texto_y, "Serviço Nacional de Aprendizagem Rural")
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(texto_x, texto_y - 0.5 * cm, "SENAR-AR/CE")

    # --- Linha divisória abaixo do timbrado ---
    linha_y = altura_pagina - ALTURA_TIMBRADO + 0.2 * cm
    canvas.setStrokeColor(AZUL_TEXTO)
    canvas.setLineWidth(1)
    canvas.line(doc.leftMargin, linha_y, largura_pagina - doc.rightMargin, linha_y)

    canvas.restoreState()
