from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app

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
    RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL,
    RECURSO_STATUS_AGUARDANDO_GESTOR,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE,
    RECURSO_STATUS_AGUARDANDO_FUNCIONARIO,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO,
    RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO,
    RECURSO_STATUS_AGUARDANDO_PRESIDENCIA,
    RECURSO_STATUS_ENCERRADO,
)
from ..utils import media_avaliacao, calcular_resultado_final, conceito_resultado
from ..resultado_final_service import montar_dados_resultado_final
from ..email_service import (
    avisar_comissao_novo_recurso,
    avisar_comissao_gestor_respondeu,
    avisar_comissao_empregado_aceitou,
    avisar_comissao_empregado_recorreu,
)

recursos_bp = Blueprint("recursos", __name__)

# Prazo pra Comissão agir num recurso: dias corridos a partir da abertura.
PRAZO_COMISSAO_DIAS = 5


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
    """Quantos recursos estão esperando resposta desse gestor especificamente."""
    if not funcionario_id:
        return 0
    vinculos_meus = VinculoAvaliacao.query.filter_by(avaliador_id=funcionario_id).all()
    if not vinculos_meus:
        return 0
    ciclo_ids = {v.ciclo_id for v in vinculos_meus}
    avaliado_ids = {v.avaliado_id for v in vinculos_meus}

    total = 0
    candidatos = RecursoAvaliacao.query.filter(
        RecursoAvaliacao.ciclo_id.in_(ciclo_ids),
        RecursoAvaliacao.avaliado_id.in_(avaliado_ids),
        RecursoAvaliacao.status == RECURSO_STATUS_AGUARDANDO_GESTOR,
    ).all()
    for r in candidatos:
        if VinculoAvaliacao.query.filter_by(
            ciclo_id=r.ciclo_id, avaliado_id=r.avaliado_id, avaliador_id=funcionario_id
        ).first():
            total += 1
    return total


def _funcionario_logado():
    funcionario_id = session.get("funcionario_id")
    if not funcionario_id:
        return None
    return Funcionario.query.get(funcionario_id)


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
    """Diz se o empregado pode abrir um novo recurso pra esse ciclo.

    Só existe recurso "em aberto" por vez pro mesmo ciclo — mas depois que
    um recurso é encerrado porque a PRESIDÊNCIA NÃO ACATOU, o empregado
    ainda pode discordar de novo e abrir outro recurso (não é a palavra
    final). Já se o recurso anterior terminou porque o empregado aceitou,
    ou porque a Comissão confirmou a revisão do gestor, não faz sentido
    abrir outro — considera resolvido."""
    ultimo = (
        RecursoAvaliacao.query.filter_by(ciclo_id=ciclo_id, avaliado_id=avaliado_id)
        .order_by(RecursoAvaliacao.criado_em.desc())
        .first()
    )
    if not ultimo:
        return True
    if ultimo.status != RECURSO_STATUS_ENCERRADO:
        return False
    decisao_presidencia = next(
        (e for e in ultimo.eventos if e.tipo == "decisao_presidencia"), None
    )
    return bool(decisao_presidencia and decisao_presidencia.decisao == "nao_acatado")


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

    ciclos_sem_recurso = []
    for registro in registros_liberados:
        if registro.decisao_avaliado == "aceito":
            # Já concordou com o resultado — não faz mais sentido abrir recurso.
            continue
        if _pode_abrir_novo_recurso(registro.ciclo_id, funcionario.id):
            ciclo = CicloAvaliacao.query.get(registro.ciclo_id)
            ciclos_sem_recurso.append(ciclo)

    meus_recursos = (
        RecursoAvaliacao.query.filter_by(avaliado_id=funcionario.id)
        .order_by(RecursoAvaliacao.criado_em.desc())
        .all()
    )

    # A resposta do gestor só aparece pro empregado depois que a Comissão
    # repassar (ou confirmar o encerramento, no caso do gestor ter revisado
    # a nota) — a Comissão sempre vê e decide antes do empregado.
    for r in meus_recursos:
        liberado = any(
            e.tipo in ("repasse_comissao_funcionario", "fechamento_comissao")
            for e in r.eventos
        )
        r.eventos_visiveis = [
            e for e in r.eventos if not (e.tipo == "resposta_gestor" and not liberado)
        ]

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
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Conte o motivo do recurso antes de enviar.", "danger")
        return redirect(url_for("recursos.recurso_area"))

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
    flash("Recurso aberto. A Comissão vai analisar e encaminhar ao gestor.", "success")
    return redirect(url_for("recursos.recurso_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/aceitar", methods=["POST"])
def aceitar_recurso(recurso_id):
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if str(recurso.avaliado_id) != str(funcionario.id) or recurso.status != RECURSO_STATUS_AGUARDANDO_FUNCIONARIO:
        flash("Essa ação não está disponível para esse recurso.", "danger")
        return redirect(url_for("recursos.recurso_area"))

    recurso.status = RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO
    db.session.add(
        RecursoEvento(recurso_id=recurso.id, tipo="aceite_funcionario", autor_id=funcionario.id)
    )
    db.session.commit()
    avisar_comissao_empregado_aceitou(recurso)
    flash("Ok, sua resposta foi registrada. A Comissão vai confirmar o encerramento.", "success")
    return redirect(url_for("recursos.recurso_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/recorrer", methods=["POST"])
def recorrer_recurso(recurso_id):
    funcionario = _funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if str(recurso.avaliado_id) != str(funcionario.id) or recurso.status != RECURSO_STATUS_AGUARDANDO_FUNCIONARIO:
        flash("Essa ação não está disponível para esse recurso.", "danger")
        return redirect(url_for("recursos.recurso_area"))

    justificativa = request.form.get("justificativa", "").strip()
    recurso.status = RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="pedido_recorrer",
            autor_id=funcionario.id,
            texto=justificativa or None,
        )
    )
    db.session.commit()
    avisar_comissao_empregado_recorreu(recurso)
    flash("Pedido enviado para a Comissão encaminhar à presidência.", "success")
    return redirect(url_for("recursos.recurso_area"))


# ---------------------------------------------------------------------------
# Gestor
# ---------------------------------------------------------------------------

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
                recursos_pendentes.append(r)
            else:
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

    if request.method == "POST":
        if recurso.status != RECURSO_STATUS_AGUARDANDO_GESTOR:
            flash("Esse recurso já foi respondido.", "warning")
            return redirect(url_for("recursos.recurso_gestor_area"))

        decisao = request.form.get("decisao")
        justificativa = request.form.get("justificativa", "").strip()
        if decisao not in ("manteve", "revisou") or not justificativa:
            flash("Escolha manter ou revisar, e escreva a justificativa.", "danger")
            return redirect(url_for("recursos.recurso_gestor_detalhe", recurso_id=recurso.id))

        if decisao == "revisou":
            _aplicar_revisao_notas(recurso, avaliacao_gestor, request.form, funcionario.id)

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


@recursos_bp.route("/recurso/comissao")
def recurso_comissao_area():
    pendentes_iniciais = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL
    ).order_by(RecursoAvaliacao.criado_em).all()
    pendentes_repasse = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE
    ).order_by(RecursoAvaliacao.criado_em).all()
    pendentes_recurso = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO
    ).order_by(RecursoAvaliacao.criado_em).all()
    pendentes_fechamento = RecursoAvaliacao.query.filter_by(
        status=RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO
    ).order_by(RecursoAvaliacao.criado_em).all()
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
    return render_template(
        "recurso_comissao_detalhe.html",
        recurso=recurso,
        dados=dados,
    )


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-repassar", methods=["POST"])
def recurso_comissao_repassar(recurso_id):
    """A Comissão viu a resposta do gestor (manteve) e repassa ao empregado."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE:
        flash("Esse recurso não está aguardando a Comissão.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    recurso.status = RECURSO_STATUS_AGUARDANDO_FUNCIONARIO
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="repasse_comissao_funcionario",
            texto=request.form.get("comentario", "").strip() or None,
        )
    )
    db.session.commit()
    flash("Resposta do gestor repassada ao empregado.", "success")
    return redirect(url_for("recursos.recurso_comissao_area"))


@recursos_bp.route("/recurso/<int:recurso_id>/comissao-fechar", methods=["POST"])
def recurso_comissao_fechar(recurso_id):
    """A Comissão confirma o encerramento depois que o empregado aceitou a resposta do gestor."""
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    if recurso.status != RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO:
        flash("Esse recurso não está aguardando a Comissão.", "warning")
        return redirect(url_for("recursos.recurso_comissao_area"))

    recurso.status = RECURSO_STATUS_ENCERRADO
    db.session.add(
        RecursoEvento(
            recurso_id=recurso.id,
            tipo="fechamento_comissao",
            texto=request.form.get("comentario", "").strip() or None,
        )
    )
    db.session.commit()
    flash("Recurso encerrado.", "success")
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
        flash("Decisão registrada.", "success")
        return redirect(url_for("recursos.recurso_presidencia_area"))

    return render_template(
        "recurso_presidencia_detalhe.html",
        funcionario=funcionario,
        recurso=recurso,
        dados=dados,
    )
