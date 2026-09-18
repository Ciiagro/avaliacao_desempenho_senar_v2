from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, Response

from ..extensions import db
from ..models import (
    Funcionario,
    CicloAvaliacao,
    Avaliacao,
    RespostaFator,
    VinculoAvaliacao,
    ResultadoFinal,
    RecursoAvaliacao,
    RecursoEvento,
    RecursoRevisaoNota,
    RecursoItemContestado,
    MembroComissao,
    Formulario,
    Fator,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL,
    RECURSO_STATUS_AGUARDANDO_GESTOR,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE,
    RECURSO_STATUS_AGUARDANDO_FUNCIONARIO,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO,
    RECURSO_STATUS_AGUARDANDO_PRESIDENCIA,
    RECURSO_STATUS_ENCERRADO,
)
from ..utils import media_avaliacao, calcular_resultado_final, conceito_resultado, prazo_dias_corridos
from ..resultado_final_service import montar_dados_resultado_final
from ..pdf_recurso import gerar_pdf_recurso
from ..email_service import (
    avisar_comissao_novo_recurso,
    avisar_comissao_gestor_respondeu,
    avisar_comissao_empregado_aceitou,
    avisar_gestor_recurso_encaminhado,
    avisar_empregado_resposta_disponivel,
    avisar_empregado_recurso_encerrado,
)

recursos_bp = Blueprint("recursos", __name__)

# Prazo pra Comissão agir num recurso: dias corridos a partir da abertura.
PRAZO_COMISSAO_DIAS = 5

# Depois que o resultado final é liberado pro empregado ver, ele tem esse
# prazo (dias corridos, empurrando pro próximo dia útil se cair em fim de
# semana) pra abrir um recurso — é só informativo (mostra a data-limite pro
# empregado), o sistema não bloqueia a abertura depois que esse prazo passa.
PRAZO_RECURSO_FUNCIONARIO_DIAS = 5

# Depois que a Comissão encaminha o recurso pro gestor reavaliar, ele tem
# esse prazo (dias corridos, mesma regra de empurrar fim de semana) pra
# responder à Comissão. Também só informativo.
PRAZO_GESTOR_RESPONDER_DIAS = 10


@recursos_bp.before_request
def exigir_senha_comissao():
    """A área da Comissão funciona igual à Administração: só precisa da
    senha da Comissão, não precisa estar logado como funcionário nem
    cadastrado em lugar nenhum."""
    endpoint = request.endpoint or ""
    if not endpoint.startswith("recursos.recurso_comissao"):
        return None
    if endpoint in ("recursos.recurso_comissao_login", "recursos.recurso_comissao_logout"):
        return None
    if not session.get("comissao_logueada"):
        return redirect(url_for("recursos.recurso_comissao_login", proximo=request.path))
    return None


def prazo_comissao(recurso):
    """Data-limite pra Comissão agir nesse recurso."""
    if not recurso.criado_em:
        return None
    return recurso.criado_em + timedelta(days=PRAZO_COMISSAO_DIAS)


# Pra cada status "aguardando a Comissão", qual tipo de evento marca o
# momento em que o recurso chegou nessa fila específica (não necessariamente
# quando o recurso foi aberto — ex: "gestor respondeu" chegou pra Comissão
# só quando o gestor respondeu, não na abertura).
_EVENTO_CHEGADA_POR_STATUS = {
    RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL: "abertura",
    RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE: "resposta_gestor",
    RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO: "pedido_recorrer",
    RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO: "aceite_funcionario",
}


def chegada_comissao(recurso):
    """Quando esse recurso chegou pra fila ATUAL da Comissão (não a
    abertura do recurso, a não ser que seja esse o caso) — usado pra
    ordenar (mais antigo primeiro) e mostrar pro usuário."""
    tipo_evento = _EVENTO_CHEGADA_POR_STATUS.get(recurso.status)
    if tipo_evento:
        eventos_do_tipo = [e for e in recurso.eventos if e.tipo == tipo_evento]
        if eventos_do_tipo:
            return eventos_do_tipo[-1].criado_em
    return recurso.criado_em


def resultado_pendente_ciencia_do_funcionario(funcionario_id):
    """Resultado final já liberado que o funcionário ainda não deu ciência
    (nem aceitou, nem abriu recurso). Enquanto existir um assim, o menu
    "Recurso" do topo não deve levar direto pra área de recursos — precisa
    passar primeiro pela tela do resultado e escolher aceitar ou recorrer."""
    if not funcionario_id:
        return None
    return ResultadoFinal.query.filter_by(
        avaliado_id=funcionario_id, liberado=True, ciente_avaliado=False
    ).first()


def contar_recursos_pendentes_comissao():
    return RecursoAvaliacao.query.filter(
        RecursoAvaliacao.status.in_(
            [
                RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL,
                RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE,
                RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO,
                RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO,
            ]
        )
    ).count()


def contar_recursos_pendentes_gestor(funcionario_id):
    """Quantos recursos estão esperando resposta desse gestor especificamente.

    Antes isto rodava uma query extra por recurso candidato dentro de um loop
    (N+1). Agora é uma única query: junta RecursoAvaliacao com o próprio
    VinculoAvaliacao (ciclo_id + avaliado_id + avaliador_id), então o banco
    já filtra e conta tudo de uma vez, sem idas e vindas repetidas."""
    if not funcionario_id:
        return 0
    return (
        RecursoAvaliacao.query.join(
            VinculoAvaliacao,
            db.and_(
                VinculoAvaliacao.ciclo_id == RecursoAvaliacao.ciclo_id,
                VinculoAvaliacao.avaliado_id == RecursoAvaliacao.avaliado_id,
                VinculoAvaliacao.avaliador_id == funcionario_id,
            ),
        )
        .filter(RecursoAvaliacao.status == RECURSO_STATUS_AGUARDANDO_GESTOR)
        .count()
    )


def _funcionario_logado():
    """Mesmo funcionário logado de app/routes/main.py — reaproveita a
    função de lá (que já cacheia em `g`) em vez de repetir a consulta ao
    banco de novo aqui."""
    from .main import funcionario_logado

    return funcionario_logado()


def _gestor_do_recurso(recurso):
    vinculo = VinculoAvaliacao.query.filter_by(
        ciclo_id=recurso.ciclo_id, avaliado_id=recurso.avaliado_id
    ).first()
    return vinculo.avaliador if vinculo else None


def _avaliacao_gestor_do_recurso(recurso):
    vinculo = VinculoAvaliacao.query.filter_by(
        ciclo_id=recurso.ciclo_id, avaliado_id=recurso.avaliado_id
    ).first()
    if not vinculo:
        return None
    return Avaliacao.query.filter_by(
        ciclo_id=recurso.ciclo_id,
        avaliado_id=recurso.avaliado_id,
        avaliador_id=vinculo.avaliador_id,
        tipo="gestor",
    ).first()


def _aplicar_revisao_notas(recurso, avaliacao_gestor, form, autor_id):
    """Aplica as novas notas enviadas no formulário à avaliação do gestor,
    registrando o valor antigo e o novo em RecursoRevisaoNota. Nunca perde o
    histórico do que era antes.

    Como o formulário chega com todos os fatores pré-marcados no valor
    atual (pra facilitar o preenchimento), só grava um registro de revisão
    pros fatores onde o valor novo é DE FATO diferente do antigo — senão a
    Comissão veria "revisou" em fatores que o gestor nem mexeu."""
    respostas_atuais = {r.fator_id: r for r in avaliacao_gestor.respostas}
    for fator in avaliacao_gestor.formulario.fatores:
        valor_novo = form.get(f"fator_{fator.id}")
        if not valor_novo:
            continue
        valor_novo = int(valor_novo)
        resposta = respostas_atuais.get(fator.id)
        valor_antigo = resposta.pontuacao if resposta else None
        if valor_novo == valor_antigo:
            continue
        if resposta:
            resposta.pontuacao = valor_novo
        else:
            resposta = RespostaFator(
                avaliacao_id=avaliacao_gestor.id, fator_id=fator.id, pontuacao=valor_novo
            )
            db.session.add(resposta)
        db.session.add(
            RecursoRevisaoNota(
                recurso_id=recurso.id,
                fator_id=fator.id,
                nota_anterior=valor_antigo,
                nota_nova=valor_novo,
                alterado_por_id=autor_id,
            )
        )


def _pode_abrir_novo_recurso(ciclo_id, avaliado_id):
    """Diz se o empregado pode abrir um recurso pra esse ciclo.

    A decisão da presidência é a última instância — depois que ela decide
    (acata ou não), o recurso encerra e não tem mais como reabrir. Só é
    possível abrir um recurso novo se nunca existiu nenhum pra esse ciclo."""
    ja_existe = RecursoAvaliacao.query.filter_by(
        ciclo_id=ciclo_id, avaliado_id=avaliado_id
    ).first()
    return ja_existe is None


# ---------------------------------------------------------------------------
# Empregado
# ---------------------------------------------------------------------------

@recursos_bp.route("/recurso")
def recurso_area():
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    registros_liberados = ResultadoFinal.query.filter_by(
        avaliado_id=funcionario.id, liberado=True
    ).all()

    formulario_funcionario = None
    if funcionario.nivel_hierarquico:
        formulario_funcionario = Formulario.query.filter_by(
            nivel_hierarquico=funcionario.nivel_hierarquico
        ).first()
    fatores_funcionario = formulario_funcionario.fatores if formulario_funcionario else []

    ciclos_sem_recurso = []
    for registro in registros_liberados:
        if registro.decisao_avaliado == "aceito":
            # Já concordou com o resultado — não faz mais sentido abrir recurso.
            continue
        if _pode_abrir_novo_recurso(registro.ciclo_id, funcionario.id):
            ciclo = CicloAvaliacao.query.get(registro.ciclo_id)
            ciclo.prazo_abrir_recurso = prazo_dias_corridos(
                registro.liberado_em, PRAZO_RECURSO_FUNCIONARIO_DIAS
            )
            ciclo.fatores = fatores_funcionario
            ciclos_sem_recurso.append(ciclo)

    meus_recursos = (
        RecursoAvaliacao.query.filter_by(avaliado_id=funcionario.id)
        .order_by(RecursoAvaliacao.criado_em.desc())
        .all()
    )

    # A resposta do gestor só aparece pro empregado depois que a Comissão
    # repassar (ou confirmar o encerramento, no caso do gestor ter revisado
    # a nota) — a Comissão sempre vê e decide antes do empregado.
    # "ajuste_comissao" é um acerto interno entre Comissão e gestor (pode
    # acontecer antes de repassar) e nunca aparece pro empregado — ele só
    # vê o resultado final, já recalculado com a nota ajustada.
    for r in meus_recursos:
        liberado = any(
            e.tipo in ("repasse_comissao_funcionario", "fechamento_comissao")
            for e in r.eventos
        )
        r.eventos_visiveis = [
            e
            for e in r.eventos
            if e.tipo != "ajuste_comissao"
            and not (e.tipo == "resposta_gestor" and not liberado)
        ]
        r.resultado_atual_em_texto = (
            _resultado_atual_texto(montar_dados_resultado_final(r.ciclo, r.avaliado))
            if liberado else None
        )

    return render_template(
        "recurso_funcionario.html",
        funcionario=funcionario,
        ciclos_sem_recurso=ciclos_sem_recurso,
        meus_recursos=meus_recursos,
    )


@recursos_bp.route("/recurso/abrir", methods=["POST"])
def abrir_recurso():
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    ciclo_id = int(request.form.get("ciclo_id"))
    fatores_ids = [i for i in request.form.getlist("itens_discordancia") if i]

    if not fatores_ids:
        flash("Selecione ao menos um item da avaliação com o qual você não concorda.", "danger")
        return redirect(url_for("recursos.recurso_area"))

    partes_motivo = []
    itens_contestados = []
    for fator_id in fatores_ids:
        fator = Fator.query.get(int(fator_id))
        texto_item = request.form.get(f"motivo_fator_{fator_id}", "").strip()
        if not fator or not texto_item:
            flash("Explique o motivo de cada item marcado antes de enviar.", "danger")
            return redirect(url_for("recursos.recurso_area"))
        partes_motivo.append(f"{fator.nome}: {texto_item}")
        itens_contestados.append((fator.id, texto_item))

    motivo = "\n\n".join(partes_motivo)

    ja_existe = not _pode_abrir_novo_recurso(ciclo_id, funcionario.id)
    if ja_existe:
        flash("Já existe um recurso aberto (ou já decidido definitivamente) para esse ciclo.", "warning")
        return redirect(url_for("recursos.recurso_area"))

    registro_existente = ResultadoFinal.query.filter_by(
        ciclo_id=ciclo_id, avaliado_id=funcionario.id
    ).first()
    if registro_existente and registro_existente.decisao_avaliado == "aceito":
        flash("Você já deu ciência aceitando esse resultado — não é mais possível abrir recurso.", "warning")
        return redirect(url_for("recursos.recurso_area"))

    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    dados = montar_dados_resultado_final(ciclo, funcionario)
    resultado_texto = (
        f"{dados['resultado_final']:.2f} ({dados['conceito']})"
        if dados["resultado_final"] is not None
        else "-"
    )

    recurso = RecursoAvaliacao(
        ciclo_id=ciclo_id,
        avaliado_id=funcionario.id,
        motivo=motivo,
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL,
        resultado_final_em_texto=resultado_texto,
    )
    db.session.add(recurso)
    db.session.flush()

    for fator_id, texto_item in itens_contestados:
        db.session.add(
            RecursoItemContestado(
                recurso_id=recurso.id, fator_id=fator_id, motivo=texto_item
            )
        )

    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id, tipo="abertura", autor_id=funcionario.id, texto=motivo
        )
    )

    # Abrir o recurso também conta como dar ciência do resultado (o
    # empregado tomou conhecimento, só que discordando dele).
    registro = ResultadoFinal.query.filter_by(
        ciclo_id=ciclo_id, avaliado_id=funcionario.id
    ).first()
    if registro and not registro.ciente_avaliado:
        registro.ciente_avaliado = True
        registro.ciente_em = datetime.utcnow()
        registro.decisao_avaliado = "recorreu"

    db.session.commit()
    avisar_comissao_novo_recurso(recurso)
    flash("Seu recurso foi aberto e está em análise. Acompanhe o andamento por aqui ou pelo e-mail cadastrado.", "success")
    return redirect(url_for("recursos.recurso_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/aceitar", methods=["POST"])
def aceitar_recurso(recurso_id):
    """Único passo do empregado depois que a Comissão repassa a resposta
    do gestor: confirmar recebimento e assinar eletronicamente. Isso
    encerra o recurso na hora — não existe mais recorrer a uma instância
    seguinte (presidência); a resposta do gestor, repassada pela Comissão,
    já é a decisão final."""
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if str(recurso.avaliado_id) != str(funcionario.id) or recurso.status != RECURSO_STATUS_AGUARDANDO_FUNCIONARIO:
        flash("Essa ação não está disponível para esse recurso.", "danger")
        return redirect(url_for("recursos.recurso_area"))

    # Se o empregado aceita, não tem mais nada esperando decisão de
    # ninguém — encerra na hora. A Comissão só é avisada pra
    # conhecimento, e pode acrescentar uma observação depois se quiser
    # (não precisa mais confirmar o encerramento manualmente).
    recurso.status = RECURSO_STATUS_ENCERRADO
    recurso.ciente_funcionario = True
    recurso.ciente_funcionario_em = datetime.utcnow()
    db.session.add(
        RecursoEvento(recurso_id=recurso.id, tipo="aceite_funcionario", autor_id=funcionario.id)
    )
    db.session.commit()
    avisar_comissao_empregado_aceitou(recurso)
    flash("Assinatura registrada. Seu recurso foi encerrado.", "success")
    return redirect(url_for("recursos.recurso_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/recorrer", methods=["POST"])
def recorrer_recurso(recurso_id):
    """Desativada: o empregado só recorre uma única vez (quando abre o
    recurso). Depois que o gestor responde e a Comissão repassa, o
    empregado só confirma recebimento (ver aceitar_recurso) — não existe
    mais uma instância seguinte (presidência) pra recorrer de novo.

    A rota continua existindo (em vez de ser removida) só como rede de
    segurança, caso alguém acesse um link antigo/em cache do botão que
    existia aqui antes."""
    flash(
        "Não é mais possível recorrer novamente: a resposta do gestor, repassada pela "
        "Comissão, já é a decisão final. Confirme o recebimento para encerrar o recurso.",
        "warning",
    )
    return redirect(url_for("recursos.recurso_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/pdf")
def recurso_pdf(recurso_id):
    """Comprovante em PDF do recurso encerrado: motivo, resposta do gestor,
    resultado final e a assinatura eletrônica do empregado confirmando o
    recebimento."""
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if str(recurso.avaliado_id) != str(funcionario.id):
        flash("Você não tem permissão para baixar esse documento.", "danger")
        return redirect(url_for("recursos.recurso_area"))

    dados = montar_dados_resultado_final(recurso.ciclo, recurso.avaliado)
    pdf_buffer = gerar_pdf_recurso(recurso, dados)
    nome_arquivo = f"recurso_{recurso.avaliado.nome.replace(' ', '_')}_{recurso.ciclo.exercicio}.pdf"
    return Response(
        pdf_buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@recursos_bp.route("/recurso/<int:recurso_id>/ciencia", methods=["POST"])
def recurso_dar_ciencia(recurso_id):
    """Depois que o recurso é encerrado pela decisão da presidência (mantida
    ou com a nota alterada), o empregado precisa dar ciência de que tomou
    conhecimento — fica registrado com data/hora, igual à ciência do
    resultado final."""
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if str(recurso.avaliado_id) != str(funcionario.id) or recurso.status != RECURSO_STATUS_ENCERRADO:
        flash("Essa ação não está disponível para esse recurso.", "danger")
        return redirect(url_for("recursos.recurso_area"))

    if not recurso.ciente_funcionario:
        recurso.ciente_funcionario = True
        recurso.ciente_funcionario_em = datetime.utcnow()
        db.session.commit()

    flash("Ciência registrada.", "success")
    return redirect(url_for("recursos.recurso_area"))


# ---------------------------------------------------------------------------
# Gestor
# ---------------------------------------------------------------------------

def _calcular_prazo_gestor_responder(recurso):
    """Prazo (10 dias corridos, empurrando fim de semana) pro gestor
    responder, contado a partir de quando a Comissão encaminhou o recurso
    pra ele — usado tanto na lista quanto na tela de resposta do gestor."""
    evento_encaminhamento = next(
        (e for e in reversed(recurso.eventos) if e.tipo == "encaminhamento_comissao_gestor"),
        None,
    )
    momento_encaminhamento = (
        evento_encaminhamento.criado_em if evento_encaminhamento else recurso.criado_em
    )
    return prazo_dias_corridos(momento_encaminhamento, PRAZO_GESTOR_RESPONDER_DIAS)


STATUS_RECURSO_LABEL = {
    RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL: "Aguardando a Comissão encaminhar",
    RECURSO_STATUS_AGUARDANDO_GESTOR: "Aguardando sua resposta",
    RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE: "Você já respondeu — aguardando a Comissão repassar ao empregado",
    RECURSO_STATUS_AGUARDANDO_FUNCIONARIO: "Repassado ao empregado — aguardando a assinatura dele",
    RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO: "Aguardando a Comissão confirmar o encerramento",
    RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO: "Aguardando a Comissão encaminhar à presidência",
    RECURSO_STATUS_AGUARDANDO_PRESIDENCIA: "Aguardando decisão da presidência",
    RECURSO_STATUS_ENCERRADO: "Encerrado",
}


@recursos_bp.route("/recurso/gestor")
def recurso_gestor_area():
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    vinculos_meus = VinculoAvaliacao.query.filter_by(avaliador_id=funcionario.id).all()
    ciclo_ids = {v.ciclo_id for v in vinculos_meus}
    avaliado_ids = {v.avaliado_id for v in vinculos_meus}

    recursos_pendentes = []
    recursos_respondidos = []
    if ciclo_ids and avaliado_ids:
        todos = RecursoAvaliacao.query.filter(
            RecursoAvaliacao.ciclo_id.in_(ciclo_ids),
            RecursoAvaliacao.avaliado_id.in_(avaliado_ids),
        ).order_by(RecursoAvaliacao.criado_em.desc()).all()
        for r in todos:
            # confere que o vínculo é justamente pra esse ciclo+avaliado
            if not VinculoAvaliacao.query.filter_by(
                ciclo_id=r.ciclo_id, avaliado_id=r.avaliado_id, avaliador_id=funcionario.id
            ).first():
                continue
            if r.status == RECURSO_STATUS_AGUARDANDO_GESTOR:
                r.prazo_gestor_responder = _calcular_prazo_gestor_responder(r)
                recursos_pendentes.append(r)
            else:
                # Uma vez que o gestor responde, não sobra mais nenhuma ação
                # pra ele nesse recurso — o que vem depois (Comissão repassar,
                # empregado assinar) não depende mais dele. Por isso essa
                # lista é tratada como "finalizada" do ponto de vista do
                # gestor, mesmo que o recurso em si ainda não esteja encerrado.
                r.status_legivel = STATUS_RECURSO_LABEL.get(r.status, r.status)
                recursos_respondidos.append(r)

    return render_template(
        "recurso_gestor.html",
        funcionario=funcionario,
        recursos_pendentes=recursos_pendentes,
        recursos_respondidos=recursos_respondidos,
    )


@recursos_bp.route("/recurso/<int:recurso_id>/gestor", methods=["GET", "POST"])
def recurso_gestor_detalhe(recurso_id):
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    vinculo = VinculoAvaliacao.query.filter_by(
        ciclo_id=recurso.ciclo_id, avaliado_id=recurso.avaliado_id, avaliador_id=funcionario.id
    ).first()
    if not vinculo:
        flash("Você não é o gestor responsável por esse recurso.", "danger")
        return redirect(url_for("recursos.recurso_gestor_area"))

    avaliacao_gestor = _avaliacao_gestor_do_recurso(recurso)
    dados = montar_dados_resultado_final(recurso.ciclo, recurso.avaliado)
    prazo_gestor_responder = (
        _calcular_prazo_gestor_responder(recurso)
        if recurso.status == RECURSO_STATUS_AGUARDANDO_GESTOR
        else None
    )

    if request.method == "POST":
        if recurso.status != RECURSO_STATUS_AGUARDANDO_GESTOR:
            flash("Esse recurso já foi respondido.", "warning")
            return redirect(url_for("recursos.recurso_gestor_area"))

        decisao = request.form.get("decisao")
        itens_contestados = recurso.itens_contestados_por_fator

        if itens_contestados:
            # Um motivo por item contestado (igual o empregado faz ao abrir
            # o recurso) — mesmo que o gestor mantenha a nota de um item e
            # mude a de outro, cada um precisa do seu próprio motivo.
            partes_justificativa = []
            for fator_id in itens_contestados:
                texto_item = request.form.get(f"motivo_fator_{fator_id}", "").strip()
                if not texto_item:
                    flash("Escreva o motivo de cada item contestado antes de enviar.", "danger")
                    return redirect(url_for("recursos.recurso_gestor_detalhe", recurso_id=recurso.id))
                fator = Fator.query.get(fator_id)
                partes_justificativa.append(f"{fator.nome if fator else fator_id}: {texto_item}")
            justificativa = "\n\n".join(partes_justificativa)
        else:
            justificativa = request.form.get("justificativa", "").strip()

        if decisao not in ("manteve", "revisou") or not justificativa:
            flash("Escolha manter ou revisar, e escreva a justificativa.", "danger")
            return redirect(url_for("recursos.recurso_gestor_detalhe", recurso_id=recurso.id))

        if decisao == "revisou":
            if itens_contestados:
                # Só os fatores contestados podem ter a nota revisada aqui.
                # Mesmo que alguém manipule o POST e mande outros "fator_<id>",
                # eles são descartados antes de chegar em _aplicar_revisao_notas.
                form_permitido = {
                    chave: valor
                    for chave, valor in request.form.items()
                    if not chave.startswith("fator_")
                    or int(chave.replace("fator_", "", 1)) in itens_contestados
                }
            else:
                # Recurso antigo, sem itens contestados individualizados:
                # mantém o comportamento anterior (todos os fatores editáveis).
                form_permitido = request.form
            _aplicar_revisao_notas(recurso, avaliacao_gestor, form_permitido, funcionario.id)

        recurso.status = RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE

        db.session.add(
            RecursoEvento(
                recurso_id=recurso.id,
                tipo="resposta_gestor",
                autor_id=funcionario.id,
                decisao=decisao,
                texto=justificativa,
            )
        )
        db.session.commit()
        avisar_comissao_gestor_respondeu(recurso, decisao, justificativa)
        flash("Resposta registrada. A Comissão vai analisar antes de repassar.", "success")
        return redirect(url_for("recursos.recurso_gestor_area"))

    return render_template(
        "recurso_gestor_detalhe.html",
        funcionario=funcionario,
        recurso=recurso,
        dados=dados,
        prazo_gestor_responder=prazo_gestor_responder,
    )


# ---------------------------------------------------------------------------
# Comissão
# ---------------------------------------------------------------------------

@recursos_bp.route("/recurso/comissao/login", methods=["GET", "POST"])
def recurso_comissao_login():
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if senha and senha == current_app.config["COMISSAO_PASSWORD"]:
            session["comissao_logueada"] = True
            proximo = request.form.get("proximo") or url_for("recursos.recurso_comissao_area")
            return redirect(proximo)
        flash("Senha da Comissão incorreta.", "danger")
    proximo = request.args.get("proximo", "")
    return render_template("recurso_comissao_login.html", proximo=proximo)


@recursos_bp.route("/recurso/comissao/logout")
def recurso_comissao_logout():
    session.pop("comissao_logueada", None)
    flash("Você saiu da área da Comissão.", "success")
    return redirect(url_for("main.index"))


def _resultado_atual_texto(dados):
    """Resultado final recalculado com as notas ATUAIS do gestor (já
    refletindo qualquer revisão feita durante o recurso) — pra Comissão
    saber, antes de repassar ou encaminhar, qual seria o resultado final
    se as coisas ficarem como estão agora."""
    if dados["resultado_final"] is None:
        return None
    return f"{dados['resultado_final']:.2f} ({dados['conceito']})"


@recursos_bp.route("/recurso/comissao")
def recurso_comissao_area():
    pendentes_iniciais = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL
    ).all()
    pendentes_repasse = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE
    ).all()
    pendentes_recurso = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO
    ).all()
    pendentes_fechamento = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO
    ).all()
    em_andamento = RecursoAvaliacao.query.filter(
        RecursoAvaliacao.status.notin_(
            [
                RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL,
                RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE,
                RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO,
                RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO,
                RECURSO_STATUS_ENCERRADO,
            ]
        )
    ).order_by(RecursoAvaliacao.criado_em.desc()).all()

    encerrados = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_ENCERRADO
    ).order_by(RecursoAvaliacao.criado_em.desc()).all()

    # Cada recurso mostra a data/hora em que chegou pra fila ATUAL da
    # Comissão (não necessariamente a abertura — ex: "gestor respondeu" só
    # chegou pra Comissão quando o gestor respondeu). As listas ficam
    # ordenadas pelo mais antigo primeiro, que é o mais urgente.
    for lista in (pendentes_iniciais, pendentes_repasse, pendentes_recurso, pendentes_fechamento):
        for r in lista:
            r.chegada_comissao_em = chegada_comissao(r)
        lista.sort(key=lambda r: r.chegada_comissao_em or r.criado_em)

    # A Comissão precisa ver as duas avaliações (autoavaliação e avaliação
    # do gestor, nota a nota) antes de agir em qualquer recurso — não só o
    # motivo do empregado. Isso também já dá, de graça, o resultado final
    # recalculado com as notas ATUAIS do gestor (já refletindo qualquer
    # revisão feita durante o recurso), pra Comissão saber, antes de
    # repassar ou encaminhar, qual seria o resultado se as coisas ficarem
    # como estão agora.
    for r in pendentes_iniciais + pendentes_repasse + pendentes_recurso:
        r.dados_avaliacoes = montar_dados_resultado_final(r.ciclo, r.avaliado)
    for r in pendentes_repasse + pendentes_recurso:
        r.resultado_atual_em_texto = _resultado_atual_texto(r.dados_avaliacoes)

    todos_pendentes = pendentes_iniciais + pendentes_repasse + pendentes_recurso + pendentes_fechamento

    return render_template(

        "recurso_comissao.html",
        pendentes_iniciais=pendentes_iniciais,
        pendentes_repasse=pendentes_repasse,
        pendentes_recurso=pendentes_recurso,
        pendentes_fechamento=pendentes_fechamento,
        em_andamento=em_andamento,
        encerrados=encerrados,
        prazo_comissao=prazo_comissao,
        now=datetime.now(timezone.utc),
        total_pendentes=len(todos_pendentes),
        total_atrasados=sum(
            1
            for r in todos_pendentes
            if prazo_comissao(r) and prazo_comissao(r) < datetime.now(timezone.utc)
        ),
    )


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-detalhe")
def recurso_comissao_detalhe(recurso_id):
    """Tela só de leitura pra Comissão acompanhar o histórico completo de um
    recurso que não está esperando ação dela agora — em andamento com o
    gestor/empregado/presidência, ou já encerrado."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    dados = montar_dados_resultado_final(recurso.ciclo, recurso.avaliado)
    presidentes = Funcionario.query.filter_by(eh_presidencia=True, ativo=True).order_by(Funcionario.nome).all()
    return render_template(
        "recurso_comissao_detalhe.html",
        recurso=recurso,
        dados=dados,
        presidentes=presidentes,
    )


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-repassar", methods=["POST"])
def recurso_comissao_repassar(recurso_id):
    """A Comissão viu a resposta do gestor e repassa ao empregado.

    Antes de repassar, a Comissão pode ajustar a nota de algum item se achar
    que o gestor errou. Isso é um acerto interno entre Comissão e gestor:
    não pede pra dizer qual membro fez, e nunca aparece pro empregado — ele
    só vê o resultado final (o recálculo já reflete a nota ajustada).
    Só é permitido ajustar os itens que o próprio empregado contestou (a
    não ser num recurso do formato antigo, sem itens individualizados, onde
    qualquer fator pode ser ajustado, como já era)."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE:
        flash("Esse recurso não está aguardando a Comissão.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    campos_fator = {
        chave: valor
        for chave, valor in request.form.items()
        if chave.startswith("fator_") and valor
    }
    if campos_fator:
        itens_contestados = recurso.itens_contestados_por_fator
        if itens_contestados:
            campos_fator = {
                chave: valor
                for chave, valor in campos_fator.items()
                if int(chave.replace("fator_", "", 1)) in itens_contestados
            }

    if campos_fator:
        avaliacao_gestor = _avaliacao_gestor_do_recurso(recurso)
        membro = (
            Funcionario.query.join(MembroComissao, MembroComissao.funcionario_id == Funcionario.id)
            .order_by(Funcionario.nome)
            .first()
        )
        if not avaliacao_gestor:
            flash("Não encontrei a avaliação do gestor para esse recurso.", "danger")
            return redirect(url_for("recursos.recurso_comissao_area"))
        if not membro:
            flash("Não há nenhum membro da Comissão cadastrado — cadastre um antes de ajustar notas.", "danger")
            return redirect(url_for("recursos.recurso_comissao_area"))

        _aplicar_revisao_notas(recurso, avaliacao_gestor, campos_fator, membro.id)
        db.session.add(
            RecursoEvento(
                recurso_id=recurso.id,
                tipo="ajuste_comissao",
                autor_id=membro.id,
                texto=request.form.get("justificativa_ajuste", "").strip() or None,
            )
        )

    recurso.status = RECURSO_STATUS_AGUARDANDO_FUNCIONARIO
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="repasse_comissao_funcionario",
            texto=request.form.get("comentario", "").strip() or None,
        )
    )
    db.session.commit()
    avisar_empregado_resposta_disponivel(recurso, request.form.get("comentario", "").strip())
    flash("Resposta do gestor repassada ao empregado.", "success")
    return redirect(url_for("recursos.recurso_comissao_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-fechar", methods=["POST"])
def recurso_comissao_fechar(recurso_id):
    """Confirma o encerramento (fluxo antigo, mantido só pra recursos que já
    estavam nessa fila antes da mudança) OU, no fluxo atual, deixa a
    Comissão acrescentar uma observação num recurso que o empregado já
    encerrou sozinho ao aceitar — não muda status nenhum, é só registro."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    comentario = request.form.get("comentario", "").strip()

    if recurso.status == RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO:
        recurso.status = RECURSO_STATUS_ENCERRADO
        db.session.add(
            RecursoEvento(recurso_id=recurso.id, tipo="fechamento_comissao", texto=comentario or None)
        )
        db.session.commit()
        avisar_empregado_recurso_encerrado(
            recurso, "Você aceitou a resposta do gestor e a Comissão confirmou o encerramento."
        )
        flash("Recurso encerrado.", "success")
        return redirect(url_for("recursos.recurso_comissao_area"))

    if recurso.status == RECURSO_STATUS_ENCERRADO:
        if not comentario:
            flash("Escreva uma observação antes de salvar.", "warning")
            return redirect(url_for("recursos.recurso_comissao_area"))
        db.session.add(
            RecursoEvento(recurso_id=recurso.id, tipo="observacao_comissao", texto=comentario)
        )
        db.session.commit()
        flash("Observação registrada.", "success")
        return redirect(url_for("recursos.recurso_comissao_area"))

    flash("Esse recurso não está encerrado nem aguardando a Comissão.", "warning")
    return redirect(url_for("recursos.recurso_comissao_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-gestor", methods=["POST"])
def recurso_comissao_encaminhar_gestor(recurso_id):
    """A Comissão analisa o recurso recém-aberto e manda mensagem ao gestor pedindo reavaliação."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL:
        flash("Esse recurso não está aguardando a Comissão.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    comentario = request.form.get("comentario", "").strip()
    if not comentario:
        flash("Escreva a mensagem pro gestor.", "danger")
        return redirect(url_for("recursos.recurso_comissao_area"))

    if not _gestor_do_recurso(recurso):
        flash("Esse empregado não tem um gestor vinculado nesse ciclo — não é possível encaminhar.", "danger")
        return redirect(url_for("recursos.recurso_comissao_area"))

    recurso.status = RECURSO_STATUS_AGUARDANDO_GESTOR
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="encaminhamento_comissao_gestor",
            texto=comentario,
        )
    )
    db.session.commit()
    avisar_gestor_recurso_encaminhado(recurso, comentario)
    flash("Mensagem enviada ao gestor pedindo reavaliação.", "success")
    return redirect(url_for("recursos.recurso_comissao_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao", methods=["POST"])
def recurso_comissao_encaminhar(recurso_id):
    """A Comissão encaminha o recurso já respondido pelo gestor à presidência."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO:
        flash("Esse recurso não está aguardando a Comissão.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    comentario = request.form.get("comentario", "").strip()
    if not comentario:
        flash("Escreva o comentário/justificativa pra presidência.", "danger")
        return redirect(url_for("recursos.recurso_comissao_area"))

    recurso.status = RECURSO_STATUS_AGUARDANDO_PRESIDENCIA
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="encaminhamento_comissao",
            texto=comentario,
        )
    )
    db.session.commit()
    flash("Encaminhado para a presidência.", "success")
    return redirect(url_for("recursos.recurso_comissao_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-registrar-conversa", methods=["POST"])
def recurso_comissao_registrar_conversa(recurso_id):
    """A Comissão registra, com data/hora e motivo, uma conversa que teve
    com a presidência sobre esse recurso (última instância) — a decisão em
    si costuma sair dessa conversa informal, mas ela precisa ficar
    documentada aqui na linha do tempo do recurso."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)

    ja_foi_a_presidencia = any(e.tipo == "encaminhamento_comissao" for e in recurso.eventos)
    if not ja_foi_a_presidencia:
        flash("Esse recurso ainda não foi encaminhado à presidência.", "warning")
        return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))

    resumo = request.form.get("resumo", "").strip()
    if not resumo:
        flash("Descreva o motivo/resumo da conversa com a presidência.", "danger")
        return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))

    data_hora_bruta = request.form.get("data_hora", "").strip()
    quando = datetime.utcnow()
    if data_hora_bruta:
        try:
            quando = datetime.strptime(data_hora_bruta, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Data/hora da conversa inválida — usando o momento atual.", "warning")

    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="conversa_comissao_presidencia",
            texto=resumo,
            criado_em=quando,
        )
    )
    db.session.commit()
    flash("Conversa com a presidência registrada.", "success")
    return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-decisao-presidencia", methods=["POST"])
def recurso_comissao_decidir_presidencia(recurso_id):
    """A Comissão registra, em nome da presidência, a decisão final do
    recurso — normalmente tomada numa conversa informal com a presidência,
    mas lançada aqui pra valer oficialmente. Duas situações: manter a
    decisão do gestor (justificando) ou alterar a nota do colaborador
    (também justificando). Nos dois casos fecha o recurso, exatamente como
    aconteceria se a presidência decidisse logando ela mesma no sistema."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_PRESIDENCIA:
        flash("Esse recurso não está aguardando decisão da presidência.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    presidente_id = request.form.get("presidente_id", "")
    presidente = (
        Funcionario.query.filter_by(id=presidente_id, eh_presidencia=True).first()
        if presidente_id
        else None
    )
    decisao = request.form.get("decisao")
    justificativa = request.form.get("justificativa", "").strip()

    if not presidente:
        flash("Selecione quem, da presidência, tomou a decisão.", "danger")
        return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))
    if decisao not in ("acatado", "nao_acatado") or not justificativa:
        flash("Escolha manter a decisão do gestor ou alterar a nota, e escreva a justificativa.", "danger")
        return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))

    avaliacao_gestor = _avaliacao_gestor_do_recurso(recurso)
    if decisao == "acatado":
        _aplicar_revisao_notas(recurso, avaliacao_gestor, request.form, presidente.id)

    quando = datetime.utcnow()
    data_hora_bruta = request.form.get("data_hora", "").strip()
    if data_hora_bruta:
        try:
            quando = datetime.strptime(data_hora_bruta, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Data/hora da decisão inválida — usando o momento atual.", "warning")
            quando = datetime.utcnow()

    recurso.status = RECURSO_STATUS_ENCERRADO
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="decisao_presidencia",
            autor_id=presidente.id,
            decisao=decisao,
            texto=justificativa,
            criado_em=quando,
        )
    )
    db.session.commit()
    resumo_decisao = (
        "A presidência alterou a sua nota."
        if decisao == "acatado"
        else "A presidência manteve a decisão do gestor."
    )
    avisar_empregado_recurso_encerrado(recurso, f"{resumo_decisao}\n\nJustificativa:\n{justificativa}")
    flash("Decisão da presidência registrada. Recurso encerrado.", "success")
    return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-editar-gestor", methods=["GET", "POST"])
def recurso_comissao_editar_gestor(recurso_id):
    """Quando a presidência decide ALTERAR a nota, a Comissão faz isso
    abrindo o formulário completo da avaliação do GESTOR (não o do
    empregado) — os mesmos fatores e o mesmo parecer (pontos fortes,
    oportunidades, plano de ação, resultados alcançados) que o gestor
    preencheu originalmente, agora editáveis. Ao salvar, registra a
    justificativa e encerra o recurso."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_PRESIDENCIA:
        flash("Esse recurso não está aguardando decisão da presidência.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    avaliacao_gestor = _avaliacao_gestor_do_recurso(recurso)
    if not avaliacao_gestor:
        flash("Não encontrei a avaliação do gestor para esse recurso.", "danger")
        return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))

    if request.method == "POST":
        presidente_id = request.form.get("presidente_id", "")
        presidente = (
            Funcionario.query.filter_by(id=presidente_id, eh_presidencia=True).first()
            if presidente_id
            else None
        )
        justificativa = request.form.get("justificativa", "").strip()
        if not presidente:
            flash("Selecione quem, da presidência, tomou a decisão.", "danger")
            return redirect(url_for("recursos.recurso_comissao_editar_gestor", recurso_id=recurso.id))
        if not justificativa:
            flash("Escreva a justificativa da alteração.", "danger")
            return redirect(url_for("recursos.recurso_comissao_editar_gestor", recurso_id=recurso.id))

        _aplicar_revisao_notas(recurso, avaliacao_gestor, request.form, presidente.id)
        avaliacao_gestor.pontos_fortes = request.form.get("pontos_fortes", "").strip()
        avaliacao_gestor.oportunidades_desenvolvimento = request.form.get("oportunidades_desenvolvimento", "").strip()
        avaliacao_gestor.plano_acao = request.form.get("plano_acao", "").strip()
        avaliacao_gestor.resultados_alcancados = request.form.get("resultados_alcancados", "").strip()

        quando = datetime.utcnow()
        data_hora_bruta = request.form.get("data_hora", "").strip()
        if data_hora_bruta:
            try:
                quando = datetime.strptime(data_hora_bruta, "%Y-%m-%dT%H:%M")
            except ValueError:
                flash("Data/hora da decisão inválida — usando o momento atual.", "warning")
                quando = datetime.utcnow()

        recurso.status = RECURSO_STATUS_ENCERRADO
        db.session.add(
            RecursoEvento(
                recurso_id=recurso.id,
                tipo="decisao_presidencia",
                autor_id=presidente.id,
                decisao="acatado",
                texto=justificativa,
                criado_em=quando,
            )
        )
        db.session.commit()
        avisar_empregado_recurso_encerrado(
            recurso, f"A presidência alterou a sua nota.\n\nJustificativa:\n{justificativa}"
        )
        flash("Avaliação do gestor atualizada e recurso encerrado.", "success")
        return redirect(url_for("recursos.recurso_comissao_detalhe", recurso_id=recurso.id))

    presidentes = Funcionario.query.filter_by(eh_presidencia=True, ativo=True).order_by(Funcionario.nome).all()
    respostas_atuais = {r.fator_id: r.pontuacao for r in avaliacao_gestor.respostas}
    return render_template(
        "recurso_comissao_editar_gestor.html",
        recurso=recurso,
        avaliacao=avaliacao_gestor,
        formulario=avaliacao_gestor.formulario,
        respostas_salvas=respostas_atuais,
        presidentes=presidentes,
    )


# ---------------------------------------------------------------------------
# Presidência
# ---------------------------------------------------------------------------

@recursos_bp.route("/recurso/presidencia")
def recurso_presidencia_area():
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))
    if not funcionario.eh_presidencia:
        flash("Essa área é restrita à presidência.", "danger")
        return redirect(url_for("main.minha_area"))

    pendentes = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_PRESIDENCIA
    ).order_by(RecursoAvaliacao.criado_em).all()
    decididos = RecursoAvaliacao.query.filter_by(status=RECURSO_STATUS_ENCERRADO).order_by(
        RecursoAvaliacao.criado_em.desc()
    ).all()

    return render_template(
        "recurso_presidencia.html", funcionario=funcionario, pendentes=pendentes, decididos=decididos
    )


@recursos_bp.route("/recurso/<int:recurso_id>/presidencia", methods=["GET", "POST"])
def recurso_presidencia_detalhe(recurso_id):
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))
    if not funcionario.eh_presidencia:
        flash("Essa área é restrita à presidência.", "danger")
        return redirect(url_for("main.minha_area"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    avaliacao_gestor = _avaliacao_gestor_do_recurso(recurso)
    dados = montar_dados_resultado_final(recurso.ciclo, recurso.avaliado)

    if request.method == "POST":
        if recurso.status != RECURSO_STATUS_AGUARDANDO_PRESIDENCIA:
            flash("Esse recurso não está aguardando decisão da presidência.", "warning")
            return redirect(url_for("recursos.recurso_presidencia_area"))

        decisao = request.form.get("decisao")
        justificativa = request.form.get("justificativa", "").strip()
        if decisao not in ("acatado", "nao_acatado") or not justificativa:
            flash("Escolha acatar ou não acatar, e escreva a justificativa.", "danger")
            return redirect(url_for("recursos.recurso_presidencia_detalhe", recurso_id=recurso.id))

        if decisao == "acatado":
            _aplicar_revisao_notas(recurso, avaliacao_gestor, request.form, funcionario.id)

        recurso.status = RECURSO_STATUS_ENCERRADO
        db.session.add(
            RecursoEvento(
                recurso_id=recurso.id,
                tipo="decisao_presidencia",
                autor_id=funcionario.id,
                decisao=decisao,
                texto=justificativa,
            )
        )
        db.session.commit()
        resumo_decisao = (
            "A presidência alterou a sua nota."
            if decisao == "acatado"
            else "A presidência manteve a decisão do gestor."
        )
        avisar_empregado_recurso_encerrado(recurso, f"{resumo_decisao}\n\nJustificativa:\n{justificativa}")
        flash("Decisão registrada.", "success")
        return redirect(url_for("recursos.recurso_presidencia_area"))

    return render_template(
        "recurso_presidencia_detalhe.html",
        funcionario=funcionario,
        recurso=recurso,
        dados=dados,
    )
