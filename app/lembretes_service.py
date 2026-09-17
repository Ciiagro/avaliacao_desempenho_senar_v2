"""
Lembretes automáticos de prazo por e-mail.

Regra: quando faltarem 5 dias, 2 dias ou 0 dias (o próprio dia) para o
prazo de autoavaliação ou de avaliação do gestor de um ciclo, manda um
e-mail para cada pessoa que AINDA não concluiu a avaliação que é
responsabilidade dela.

Pensado pra ser chamado uma vez por dia (ver rota
`main.tarefa_verificar_prazos`, disparada por um cron do Vercel — veja
vercel.json). Cada envio fica registrado em NotificacaoPrazo pra nunca
mandar o mesmo lembrete duas vezes para a mesma pessoa, mesmo que a
rotina seja chamada mais de uma vez no mesmo dia.
"""

from datetime import datetime, timezone

from .extensions import db
from .models import CicloAvaliacao, VinculoAvaliacao, Avaliacao, ResultadoFinal, NotificacaoPrazo
from .utils import para_fortaleza, adicionar_dias_uteis
from .email_service import avisar_prazo_avaliacao, avisar_prazo_ciencia_resultado

DIAS_DE_AVISO = (5, 2, 0)
DIAS_DE_AVISO_CIENCIA = (2, 0)  # prazo de ciência é curto (5 dias úteis), não cabe um aviso de "5 dias"
PRAZO_CIENCIA_DIAS_UTEIS = 5


def _hoje_fortaleza():
    return para_fortaleza(datetime.now(timezone.utc)).date()


def _pendentes_do_ciclo(ciclo, tipo):
    """Lista de Funcionario que ainda precisam concluir a avaliação do
    `tipo` ('auto' ou 'gestor') nesse ciclo.

    - tipo 'auto': cada avaliado (de vinculos_avaliacao) precisa concluir
      a própria autoavaliação (avaliador_id = avaliado_id).
    - tipo 'gestor': cada avaliador (gestor) precisa concluir a avaliação
      de cada subordinado vinculado a ele.
    Uma pessoa só é considerada pendente se tiver e-mail cadastrado —
    sem e-mail não tem pra onde mandar o aviso.
    """
    vinculos = VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id).all()

    concluidas = {
        (a.avaliado_id, a.avaliador_id)
        for a in Avaliacao.query.filter_by(ciclo_id=ciclo.id, tipo=tipo, status="concluida").all()
    }

    pendentes = {}
    for v in vinculos:
        if tipo == "auto":
            chave = (v.avaliado_id, v.avaliado_id)
            responsavel = v.avaliado
        else:
            chave = (v.avaliado_id, v.avaliador_id)
            responsavel = v.avaliador

        if chave in concluidas:
            continue
        if not responsavel or not (responsavel.email and responsavel.email.strip()):
            continue
        pendentes[responsavel.id] = responsavel

    return list(pendentes.values())


def _lembretes_avaliacao(hoje, resumo):
    ciclos = CicloAvaliacao.query.filter_by(status="aberto").all()

    for ciclo in ciclos:
        for tipo, prazo in (
            ("auto", ciclo.data_limite_autoavaliacao),
            ("gestor", ciclo.data_limite_gestor),
        ):
            if not prazo:
                continue

            dias_restantes = (prazo - hoje).days
            resumo["verificados"] += 1
            if dias_restantes not in DIAS_DE_AVISO:
                continue

            for pessoa in _pendentes_do_ciclo(ciclo, tipo):
                ja_enviado = NotificacaoPrazo.query.filter_by(
                    ciclo_id=ciclo.id,
                    tipo=tipo,
                    avaliador_id=pessoa.id,
                    dias_restantes=dias_restantes,
                ).first()
                if ja_enviado:
                    continue

                avisar_prazo_avaliacao(pessoa, tipo, dias_restantes, prazo)
                db.session.add(
                    NotificacaoPrazo(
                        ciclo_id=ciclo.id,
                        tipo=tipo,
                        avaliador_id=pessoa.id,
                        dias_restantes=dias_restantes,
                    )
                )
                db.session.commit()
                resumo["enviados"] += 1
                resumo["detalhes"].append(
                    f"{pessoa.nome} — {tipo} — {dias_restantes}d — ciclo {ciclo.exercicio}"
                )


def _lembretes_ciencia_resultado(hoje, resumo):
    """Quem já teve o resultado final liberado mas ainda não deu ciência
    (independente de pretender recorrer ou não) — o prazo é de 5 dias
    úteis a partir da liberação."""
    pendentes = ResultadoFinal.query.filter_by(liberado=True, ciente_avaliado=False).all()

    for registro in pendentes:
        if not registro.liberado_em:
            continue

        prazo = adicionar_dias_uteis(para_fortaleza(registro.liberado_em), PRAZO_CIENCIA_DIAS_UTEIS)
        if prazo is None:
            continue
        prazo = prazo.date()  # adicionar_dias_uteis devolve datetime; aqui só importa o dia
        dias_restantes = (prazo - hoje).days
        resumo["verificados"] += 1
        if dias_restantes not in DIAS_DE_AVISO_CIENCIA:
            continue

        pessoa = registro.avaliado
        if not pessoa or not (pessoa.email and pessoa.email.strip()):
            continue

        ja_enviado = NotificacaoPrazo.query.filter_by(
            ciclo_id=registro.ciclo_id,
            tipo="ciencia_resultado",
            avaliador_id=pessoa.id,
            dias_restantes=dias_restantes,
        ).first()
        if ja_enviado:
            continue

        avisar_prazo_ciencia_resultado(pessoa, dias_restantes, prazo)
        db.session.add(
            NotificacaoPrazo(
                ciclo_id=registro.ciclo_id,
                tipo="ciencia_resultado",
                avaliador_id=pessoa.id,
                dias_restantes=dias_restantes,
            )
        )
        db.session.commit()
        resumo["enviados"] += 1
        resumo["detalhes"].append(
            f"{pessoa.nome} — ciência do resultado — {dias_restantes}d"
        )


def enviar_lembretes_prazo():
    """Verifica todos os prazos (avaliação e ciência do resultado final) e
    manda os lembretes que forem devidos hoje. Retorna um resumo (dict) do
    que foi feito, pra rota que chama isso poder responder algo útil (e
    pro log do Vercel Cron)."""
    hoje = _hoje_fortaleza()
    resumo = {"verificados": 0, "enviados": 0, "detalhes": []}

    _lembretes_avaliacao(hoje, resumo)
    _lembretes_ciencia_resultado(hoje, resumo)

    return resumo
