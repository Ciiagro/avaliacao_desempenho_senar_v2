"""
Regra de progressão de nível: para subir de nivel_hierarquico, o funcionário
precisa de conceito A em dois exercícios seguidos (um "par"). Uma vez que um
par já foi usado numa progressão (ou que um evento tipo mudança de função
aconteceu), esses anos não podem ser reaproveitados — o próximo par só pode
começar depois daquele ponto. Por isso a régua "anda pra frente" e nunca
reusa terreno já usado; ver ProgressaoPontoPartida.

IMPORTANTE (performance): toda a leitura do banco é feita em um punhado de
consultas em lote (carregar_dados_progressao), uma única vez — não uma
consulta por funcionário/ciclo. Calcular linha por linha do jeito ingênuo
vira uma cascata de idas ao banco (N+1) e deixa a tela extremamente lenta
com muitos funcionários e/ou muitos ciclos.
"""

from collections import defaultdict

from sqlalchemy.orm import joinedload

from .models import (
    Avaliacao,
    CicloAvaliacao,
    EventoFuncionario,
    HistoricoPreSistema,
    Progressao,
    ProgressaoPontoPartida,
)
from .utils import calcular_resultado_final, conceito_resultado, media_avaliacao

CONCEITO_EXIGIDO = "A"  # única letra que conta para progressão, por enquanto


def carregar_dados_progressao():
    """Faz todas as consultas ao banco de uma vez só (independente de
    quantos funcionários/ciclos existirem) e devolve um dict com tudo já
    organizado para consulta em memória.
    """
    ciclos = CicloAvaliacao.query.all()

    # Uma única consulta com as respostas já carregadas junto (evita 1
    # consulta extra por avaliação na hora de calcular a média).
    avaliacoes = (
        Avaliacao.query.options(joinedload(Avaliacao.respostas))
        .filter(Avaliacao.status == "concluida", Avaliacao.tipo.in_(("auto", "gestor")))
        .all()
    )

    # media_por_ciclo_funcionario[(ciclo_id, avaliado_id, tipo)] = média
    # (assume no máximo uma avaliação 'auto' e uma 'gestor' concluída por
    # avaliado em cada ciclo — a mesma premissa já usada no resultado final)
    media_por_ciclo_funcionario = {}
    for a in avaliacoes:
        media = media_avaliacao(a)
        if media is not None:
            media_por_ciclo_funcionario[(a.ciclo_id, a.avaliado_id, a.tipo)] = media

    avaliados_por_ciclo = defaultdict(set)
    for (ciclo_id, avaliado_id, _tipo) in media_por_ciclo_funcionario:
        avaliados_por_ciclo[ciclo_id].add(avaliado_id)

    conceito_ciclo_funcionario = {}
    nota_ciclo_funcionario = {}
    for ciclo in ciclos:
        for avaliado_id in avaliados_por_ciclo.get(ciclo.id, ()):
            media_auto = media_por_ciclo_funcionario.get((ciclo.id, avaliado_id, "auto"))
            media_gestor = media_por_ciclo_funcionario.get((ciclo.id, avaliado_id, "gestor"))
            resultado = calcular_resultado_final(media_auto, media_gestor)
            conceito = conceito_resultado(resultado)
            if conceito is not None:
                conceito_ciclo_funcionario[(ciclo.exercicio, avaliado_id)] = conceito
                nota_ciclo_funcionario[(ciclo.exercicio, avaliado_id)] = resultado

    historico_por_funcionario = defaultdict(dict)
    nota_historico_por_funcionario = defaultdict(dict)
    for h in HistoricoPreSistema.query.all():
        historico_por_funcionario[h.funcionario_id][h.exercicio] = conceito_resultado(float(h.nota))
        nota_historico_por_funcionario[h.funcionario_id][h.exercicio] = float(h.nota)

    ponteiros_por_funcionario = {
        p.funcionario_id: p for p in ProgressaoPontoPartida.query.all()
    }

    ultima_progressao_por_funcionario = {}
    for p in Progressao.query.order_by(Progressao.exercicio_fim.asc()).all():
        ultima_progressao_por_funcionario[p.funcionario_id] = p  # fica a última (maior exercicio_fim)

    ultimo_evento_por_funcionario = {}
    for e in EventoFuncionario.query.order_by(EventoFuncionario.exercicio.asc()).all():
        ultimo_evento_por_funcionario[e.funcionario_id] = e  # fica o último (maior exercicio)

    return {
        "conceito_ciclo_funcionario": conceito_ciclo_funcionario,
        "nota_ciclo_funcionario": nota_ciclo_funcionario,
        "historico_por_funcionario": historico_por_funcionario,
        "nota_historico_por_funcionario": nota_historico_por_funcionario,
        "ponteiros_por_funcionario": ponteiros_por_funcionario,
        "ultima_progressao_por_funcionario": ultima_progressao_por_funcionario,
        "ultimo_evento_por_funcionario": ultimo_evento_por_funcionario,
    }


def notas_detalhadas_do_funcionario(funcionario_id, dados):
    """Junta pré-sistema + sistema numa lista só, ordenada por ano, com a
    nota, o conceito e se dá pra editar (só os anos pré-sistema — os anos
    já calculados pelo sistema a partir de avaliação real não podem ser
    digitados por cima)."""
    linhas = {}
    for exercicio, nota in dados["nota_historico_por_funcionario"].get(funcionario_id, {}).items():
        linhas[exercicio] = {
            "exercicio": exercicio,
            "nota": nota,
            "conceito": conceito_resultado(nota),
            "editavel": True,
            "origem": "Importado/digitado",
        }
    for (exercicio, avaliado_id), nota in dados["nota_ciclo_funcionario"].items():
        if avaliado_id == funcionario_id:
            linhas[exercicio] = {
                "exercicio": exercicio,
                "nota": nota,
                "conceito": conceito_resultado(nota),
                "editavel": False,
                "origem": "Avaliação do sistema",
            }
    return [linhas[ano] for ano in sorted(linhas)]


def _conceitos_do_funcionario(funcionario_id, dados):
    conceitos = dict(dados["historico_por_funcionario"].get(funcionario_id, {}))
    for (exercicio, avaliado_id), conceito in dados["conceito_ciclo_funcionario"].items():
        if avaliado_id == funcionario_id:
            conceitos[exercicio] = conceito
    return conceitos


def ponto_partida_efetivo_do_funcionario(funcionario_id, dados):
    """Devolve (ponto_partida, precisa_confirmacao).

    ponto_partida = None e precisa_confirmacao = True: o RH marcou "?" na
    planilha — situação ambígua, alguém precisa decidir manualmente.

    ponto_partida = None e precisa_confirmacao = False: não há nenhum marco
    (planilha, progressão ou evento) ainda — normal para quem nunca tirou
    conceito A; calcular_situacao_par decide o que fazer com isso.
    """
    candidatos = []

    ponteiro = dados["ponteiros_por_funcionario"].get(funcionario_id)
    if ponteiro and ponteiro.exercicio_inicio is not None:
        candidatos.append(ponteiro.exercicio_inicio)

    ultima_progressao = dados["ultima_progressao_por_funcionario"].get(funcionario_id)
    if ultima_progressao:
        candidatos.append(ultima_progressao.exercicio_fim + 1)

    ultimo_evento = dados["ultimo_evento_por_funcionario"].get(funcionario_id)
    if ultimo_evento:
        candidatos.append(ultimo_evento.exercicio)

    if candidatos:
        return max(candidatos), False

    precisa_confirmacao = bool(ponteiro and getattr(ponteiro, "precisa_confirmacao", False))
    return None, precisa_confirmacao


def _aplicar_regra_do_par(conceitos, ponto_partida):
    """A regra em si (pura, sem acesso a banco): desliza a janela ano a ano
    a partir do ponto de partida até achar um par elegível, ficar
    aguardando o próximo ano, ou esgotar o dado conhecido."""
    if ponto_partida is None:
        return {
            "status": "sem_ponto_partida",
            "par_inicio": None,
            "par_fim": None,
            "exercicio_efetivacao": None,
            "conceitos": conceitos,
        }

    ano = ponto_partida

    # O laço sempre retorna de dentro (nunca precisa de limite artificial):
    # assim que `ano` ultrapassa o maior exercício conhecido, o próprio
    # `ano not in conceitos` abaixo já devolve "sem_dado" — inclusive quando
    # o ponto de partida foi definido além do dado disponível (ex.: alguém
    # digitou um ano futuro no ponto de partida). Um limite artificial aqui
    # (como havia antes) fazia esse caso virar "não elegível" por engano,
    # em vez de simplesmente "aguardando esse ano".
    while True:
        if ano not in conceitos:
            return {
                "status": "sem_dado",
                "par_inicio": None,
                "par_fim": None,
                "exercicio_efetivacao": None,
                "ano_em_falta": ano,
                "conceitos": conceitos,
            }
        if conceitos[ano] != CONCEITO_EXIGIDO:
            ano += 1
            continue

        proximo = ano + 1
        if proximo not in conceitos:
            return {
                "status": "aguardando",
                "par_inicio": ano,
                "par_fim": proximo,
                "exercicio_efetivacao": None,
                "conceitos": conceitos,
            }
        if conceitos[proximo] == CONCEITO_EXIGIDO:
            return {
                "status": "elegivel",
                "par_inicio": ano,
                "par_fim": proximo,
                "exercicio_efetivacao": proximo + 1,
                "conceitos": conceitos,
            }
        # segundo ano não bateu a régua: desliza a janela e tenta de novo
        ano = proximo


def calcular_situacao_par(funcionario, dados=None):
    """Situação do par de progressão de UM funcionário. Se `dados` não for
    passado, carrega em lote só pra ele (ok pra tela de detalhe). Ao montar
    uma listagem com vários funcionários, chame carregar_dados_progressao()
    uma única vez antes do loop e passe o resultado aqui em `dados` —
    caso contrário a tela volta a fazer uma consulta por funcionário.
    """
    if dados is None:
        dados = carregar_dados_progressao()

    conceitos = _conceitos_do_funcionario(funcionario.id, dados)
    ponto_partida, precisa_confirmacao = ponto_partida_efetivo_do_funcionario(funcionario.id, dados)

    if ponto_partida is None:
        if precisa_confirmacao:
            # Ambiguidade explícita (planilha marcada com "?") — só o RH resolve.
            return {
                "status": "sem_ponto_partida",
                "par_inicio": None,
                "par_fim": None,
                "exercicio_efetivacao": None,
                "conceitos": conceitos,
            }
        if not conceitos:
            # Nenhum dado ainda (nem histórico importado, nem ciclo no sistema).
            return {
                "status": "sem_historico",
                "par_inicio": None,
                "par_fim": None,
                "exercicio_efetivacao": None,
                "conceitos": conceitos,
            }
        # Não há marco explícito, mas já existe alguma nota: procura o
        # primeiro ano com conceito A a partir do primeiro dado disponível.
        ponto_partida = min(conceitos)

    return _aplicar_regra_do_par(conceitos, ponto_partida)
