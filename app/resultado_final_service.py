"""
Monta os dados do "Resultado final da avaliação" (autoavaliação x0,30 +
avaliação do gestor x0,70) para um empregado num ciclo, no mesmo formato da
tabulação usada pela empresa. Usado tanto para exibir na tela quanto para
gerar o PDF e o Excel para download.
"""

from .models import Avaliacao, VinculoAvaliacao, ResultadoFinal
from .utils import media_avaliacao, calcular_resultado_final, conceito_resultado


def montar_dados_resultado_final(ciclo, avaliado):
    resultado_registro = ResultadoFinal.query.filter_by(
        ciclo_id=ciclo.id, avaliado_id=avaliado.id
    ).first()

    avaliacao_auto = Avaliacao.query.filter_by(
        ciclo_id=ciclo.id, avaliado_id=avaliado.id, avaliador_id=avaliado.id, tipo="auto"
    ).first()

    vinculo = VinculoAvaliacao.query.filter_by(
        ciclo_id=ciclo.id, avaliado_id=avaliado.id
    ).first()
    avaliacao_gestor = None
    if vinculo:
        avaliacao_gestor = Avaliacao.query.filter_by(
            ciclo_id=ciclo.id,
            avaliado_id=avaliado.id,
            avaliador_id=vinculo.avaliador_id,
            tipo="gestor",
        ).first()

    media_auto = media_avaliacao(avaliacao_auto)
    media_gestor = media_avaliacao(avaliacao_gestor)
    resultado_final = calcular_resultado_final(media_auto, media_gestor)
    conceito = conceito_resultado(resultado_final)

    formulario = None
    if avaliacao_auto:
        formulario = avaliacao_auto.formulario
    elif avaliacao_gestor:
        formulario = avaliacao_gestor.formulario

    fatores = formulario.fatores if formulario else []
    respostas_auto = (
        {r.fator_id: r.pontuacao for r in avaliacao_auto.respostas} if avaliacao_auto else {}
    )
    respostas_gestor = (
        {r.fator_id: r.pontuacao for r in avaliacao_gestor.respostas} if avaliacao_gestor else {}
    )

    soma_auto = sum(respostas_auto.values()) if respostas_auto else None
    soma_gestor = sum(respostas_gestor.values()) if respostas_gestor else None

    return {
        "avaliado": avaliado,
        "ciclo": ciclo,
        "fatores": fatores,
        "respostas_auto": respostas_auto,
        "respostas_gestor": respostas_gestor,
        "soma_auto": soma_auto,
        "soma_gestor": soma_gestor,
        "media_auto": media_auto,
        "media_gestor": media_gestor,
        "resultado_final": resultado_final,
        "conceito": conceito,
        "avaliacao_auto": avaliacao_auto,
        "avaliacao_gestor": avaliacao_gestor,
        "avaliador": vinculo.avaliador if vinculo else None,
        "resultado_registro": resultado_registro,
    }
