from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response, g

from ..extensions import db
from ..models import Funcionario, VinculoAvaliacao, CicloAvaliacao, Avaliacao, ResultadoFinal
from ..utils import media_avaliacao, calcular_resultado_final, conceito_resultado, adicionar_dias_uteis, para_fortaleza
from ..resultado_final_service import montar_dados_resultado_final
from ..pdf_resultado_final import gerar_pdf_resultado_final
from ..excel_resultado_final import gerar_excel_resultado_final

main_bp = Blueprint("main", __name__)

# Prazo pro avaliado dar ciência (aceitar ou recorrer) depois que o
# resultado final é liberado.
PRAZO_CIENCIA_DIAS_UTEIS = 5


def ciclo_ativo():
    """Retorna o ciclo de avaliação "aberto" a usar quando ninguém escolhe
    o ciclo explicitamente: o marcado como padrão, se houver; senão, o
    aberto mais recente (comportamento antigo, usado como fallback)."""
    return (
        CicloAvaliacao.query.filter_by(status="aberto")
        .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
        .first()
    )


def funcionario_logado():
    """Retorna o Funcionario logado (via /login) ou None.

    Cacheado em `g` (memória do próprio request) porque isto é chamado
    várias vezes na mesma página: uma vez pelo context_processor (que roda
    em toda página do site) e de novo dentro de várias rotas. Sem o cache,
    cada chamada repetia a mesma consulta ao banco dentro do mesmo request."""
    if not hasattr(g, "_funcionario_logado_cache"):
        funcionario_id = session.get("funcionario_id")
        g._funcionario_logado_cache = (
            Funcionario.query.get(funcionario_id) if funcionario_id else None
        )
    return g._funcionario_logado_cache


@main_bp.route("/")
def index():
    ciclo = ciclo_ativo()
    return render_template("index.html", ciclo=ciclo, funcionario=funcionario_logado())


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        funcionario = (
            Funcionario.query.filter(
                db.func.lower(Funcionario.email) == email, Funcionario.ativo.is_(True)
            ).first()
            if email
            else None
        )
        if funcionario and funcionario.checar_senha(senha):
            session["funcionario_id"] = str(funcionario.id)
            if funcionario.senha_provisoria:
                return redirect(url_for("main.trocar_senha"))
            return redirect(url_for("main.minha_area"))
        flash("E-mail ou senha incorretos.", "danger")
    return render_template("login.html")


@main_bp.route("/logout")
def logout():
    session.pop("funcionario_id", None)
    flash("Você saiu.", "success")
    return redirect(url_for("main.index"))


@main_bp.route("/trocar-senha", methods=["GET", "POST"])
def trocar_senha():
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    if request.method == "POST":
        senha_atual = request.form.get("senha_atual", "")
        senha_nova = request.form.get("senha_nova", "")
        senha_confirmar = request.form.get("senha_confirmar", "")

        if not funcionario.checar_senha(senha_atual):
            flash("Senha atual incorreta.", "danger")
        elif len(senha_nova) < 6:
            flash("A nova senha precisa ter pelo menos 6 caracteres.", "danger")
        elif senha_nova != senha_confirmar:
            flash("A confirmação não bate com a nova senha.", "danger")
        else:
            funcionario.set_senha(senha_nova)
            funcionario.senha_provisoria = False
            db.session.commit()
            flash("Senha alterada com sucesso.", "success")
            return redirect(url_for("main.minha_area"))

    return render_template("trocar_senha.html", forcado=funcionario.senha_provisoria)


def _resultados_liberados_do_funcionario(funcionario):
    """Todos os resultados finais já liberados pela administração para este
    empregado, em qualquer ciclo (mesmo que o ciclo já tenha sido
    encerrado depois da liberação). Mais recente primeiro."""
    registros = (
        ResultadoFinal.query.filter_by(avaliado_id=funcionario.id, liberado=True)
        .join(CicloAvaliacao, ResultadoFinal.ciclo_id == CicloAvaliacao.id)
        .order_by(CicloAvaliacao.exercicio.desc())
        .all()
    )

    resultados = []
    for registro in registros:
        ciclo_do_registro = CicloAvaliacao.query.get(registro.ciclo_id)

        autoavaliacao_dele = Avaliacao.query.filter_by(
            ciclo_id=registro.ciclo_id,
            avaliado_id=funcionario.id,
            avaliador_id=funcionario.id,
            tipo="auto",
        ).first()

        meu_vinculo = VinculoAvaliacao.query.filter_by(
            ciclo_id=registro.ciclo_id, avaliado_id=funcionario.id
        ).first()
        avaliacao_gestor_dele = None
        if meu_vinculo:
            avaliacao_gestor_dele = Avaliacao.query.filter_by(
                ciclo_id=registro.ciclo_id,
                avaliado_id=funcionario.id,
                avaliador_id=meu_vinculo.avaliador_id,
                tipo="gestor",
            ).first()

        media_auto = media_avaliacao(autoavaliacao_dele)
        media_gestor = media_avaliacao(avaliacao_gestor_dele)
        resultado = calcular_resultado_final(media_auto, media_gestor)
        if resultado is None:
            continue

        resultados.append(
            {
                "ciclo": ciclo_do_registro,
                "media_auto": media_auto,
                "media_gestor": media_gestor,
                "resultado_final": resultado,
                "conceito": conceito_resultado(resultado),
            }
        )

    return resultados


@main_bp.route("/minha-area")
def minha_area():
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))
    if funcionario.senha_provisoria:
        return redirect(url_for("main.trocar_senha"))

    resultados_liberados = _resultados_liberados_do_funcionario(funcionario)

    ciclo = ciclo_ativo()
    if not ciclo:
        flash("Nenhum ciclo de avaliação está aberto no momento.", "warning")
        return render_template(
            "minha_area.html",
            funcionario=funcionario,
            ciclo=None,
            autoavaliacao=None,
            linhas=[],
            resultados_liberados=resultados_liberados,
        )

    autoavaliacao = Avaliacao.query.filter_by(
        ciclo_id=ciclo.id,
        avaliado_id=funcionario.id,
        avaliador_id=funcionario.id,
        tipo="auto",
    ).first()

    vinculos = (
        VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id, avaliador_id=funcionario.id)
        .join(Funcionario, VinculoAvaliacao.avaliado_id == Funcionario.id)
        .order_by(Funcionario.nome)
        .all()
    )
    referencia = ciclo.referencia_elegibilidade()
    linhas = []
    for v in vinculos:
        # Não mostra quem não era elegível (ex: menos de 1 ano de casa) na
        # data do próprio ciclo — mesmo que um vínculo tenha sido criado
        # por engano pra essa pessoa nesse ciclo.
        if v.avaliado.is_elegivel_avaliacao(referencia=referencia) is False:
            continue
        avaliacao = Avaliacao.query.filter_by(
            ciclo_id=ciclo.id,
            avaliado_id=v.avaliado_id,
            avaliador_id=funcionario.id,
            tipo="gestor",
        ).first()
        autoavaliacao_dele = Avaliacao.query.filter_by(
            ciclo_id=ciclo.id,
            avaliado_id=v.avaliado_id,
            avaliador_id=v.avaliado_id,
            tipo="auto",
        ).first()
        linhas.append(
            {
                "avaliado": v.avaliado,
                "avaliacao": avaliacao,
                "status": avaliacao.status if avaliacao else "nao_iniciada",
                "autoavaliacao_status": autoavaliacao_dele.status if autoavaliacao_dele else "nao_iniciada",
            }
        )

    return render_template(
        "minha_area.html",
        funcionario=funcionario,
        ciclo=ciclo,
        autoavaliacao=autoavaliacao,
        linhas=linhas,
        resultados_liberados=resultados_liberados,
    )


def _resultado_liberado_do_ciclo(funcionario, ciclo_id):
    """Confere se o resultado final desse ciclo foi liberado para este
    empregado, e devolve o registro (ou None caso não tenha sido)."""
    return ResultadoFinal.query.filter_by(
        ciclo_id=ciclo_id, avaliado_id=funcionario.id, liberado=True
    ).first()


def prazo_ciencia(registro):
    """Data-limite (5 dias úteis a partir da liberação) pro avaliado dar
    ciência do resultado final — aceitando ou recorrendo. Conta os dias
    úteis pelo calendário de Fortaleza/CE, não pelo UTC."""
    if not registro or not registro.liberado_em:
        return None
    liberado_local = para_fortaleza(registro.liberado_em)
    return adicionar_dias_uteis(liberado_local, PRAZO_CIENCIA_DIAS_UTEIS)


@main_bp.route("/meu-resultado/<int:ciclo_id>")
def meu_resultado_detalhe(ciclo_id):
    """Mostra ao próprio empregado a autoavaliação e a avaliação do gestor
    lado a lado, com o resultado final — só depois que a administração
    liberar."""
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    registro = _resultado_liberado_do_ciclo(funcionario, ciclo_id)
    if not registro:
        flash("Seu resultado final ainda não foi liberado pela administração.", "warning")
        return redirect(url_for("main.minha_area"))

    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    dados = montar_dados_resultado_final(ciclo, funcionario)
    if dados["resultado_final"] is None:
        flash("Seu resultado final ainda não está disponível.", "warning")
        return redirect(url_for("main.minha_area"))

    # Se o empregado optou por recorrer, busca o recurso pra mostrar o
    # status ATUAL dele aqui mesmo (em vez de um texto fixo que nunca
    # muda) — e, quando estiver esperando a assinatura dele, deixa
    # assinar direto por aqui também, sem precisar ir pra área de
    # recursos (mesma ação, mesmo resultado dos dois lugares).
    recurso_atual = None
    if registro.decisao_avaliado == "recorreu":
        from ..models import RecursoAvaliacao
        from .recursos import STATUS_RECURSO_LABEL

        recurso_atual = RecursoAvaliacao.query.filter_by(
            ciclo_id=ciclo_id, avaliado_id=funcionario.id
        ).first()
        if recurso_atual:
            recurso_atual.status_legivel = STATUS_RECURSO_LABEL.get(
                recurso_atual.status, recurso_atual.status
            )

    return render_template(
        "resultado_detalhe_funcionario.html",
        ciclo=ciclo,
        funcionario=funcionario,
        dados=dados,
        prazo_ciencia=prazo_ciencia(registro),
        agora=datetime.now(timezone.utc),
        recurso_atual=recurso_atual,
    )


@main_bp.route("/meu-resultado/<int:ciclo_id>/ciencia", methods=["POST"])
def meu_resultado_ciencia(ciclo_id):
    """O próprio empregado marca a ciência de que recebeu o resultado final,
    dizendo se aceita (encerra por aí) ou se vai recorrer. Só pode ser feito
    depois que o resultado foi liberado, e fica registrado com data/hora
    (é impresso no PDF como comprovante).

    A caixa de ciência é obrigatória nos dois casos — tanto pra aceitar
    quanto pra recorrer — porque os dois botões ficam dentro do mesmo
    formulário. Escolher "recorrer" aqui não abre o recurso sozinho: só
    registra a ciência e a intenção, e leva o empregado pra área de
    recursos pra ele efetivamente abrir o recurso (com o motivo)."""
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    registro = _resultado_liberado_do_ciclo(funcionario, ciclo_id)
    if not registro:
        flash("Seu resultado final ainda não foi liberado pela administração.", "warning")
        return redirect(url_for("main.minha_area"))

    if not request.form.get("ciencia"):
        flash("Marque a caixa de ciência para confirmar o recebimento da sua avaliação.", "warning")
        return redirect(url_for("main.meu_resultado_detalhe", ciclo_id=ciclo_id))

    decisao = request.form.get("decisao")
    if decisao not in ("aceito", "recorrer"):
        flash("Escolha se aceita o resultado ou se quer recorrer.", "warning")
        return redirect(url_for("main.meu_resultado_detalhe", ciclo_id=ciclo_id))

    if not registro.ciente_avaliado:
        registro.ciente_avaliado = True
        registro.ciente_em = datetime.utcnow()
        registro.decisao_avaliado = "recorreu" if decisao == "recorrer" else "aceito"
        db.session.commit()

    if decisao == "recorrer":
        flash("Ciência registrada. Agora conte o motivo e abra seu recurso abaixo.", "warning")
        return redirect(url_for("recursos.recurso_area"))

    flash("Ciência registrada. Obrigado por confirmar o recebimento.", "success")
    return redirect(url_for("main.meu_resultado_detalhe", ciclo_id=ciclo_id))


@main_bp.route("/meu-resultado/<int:ciclo_id>/pdf")
def meu_resultado_pdf(ciclo_id):
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    registro = _resultado_liberado_do_ciclo(funcionario, ciclo_id)
    if not registro:
        flash("Seu resultado final ainda não foi liberado pela administração.", "warning")
        return redirect(url_for("main.minha_area"))

    if not registro.ciente_avaliado:
        flash("Confirme a ciência de recebimento antes de baixar o PDF.", "warning")
        return redirect(url_for("main.meu_resultado_detalhe", ciclo_id=ciclo_id))

    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    dados = montar_dados_resultado_final(ciclo, funcionario)
    if dados["resultado_final"] is None:
        flash("Seu resultado final ainda não está disponível.", "warning")
        return redirect(url_for("main.minha_area"))

    pdf_buffer = gerar_pdf_resultado_final(dados)
    nome_arquivo = f"resultado_final_{funcionario.nome.replace(' ', '_')}_{ciclo.exercicio}.pdf"
    return Response(
        pdf_buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@main_bp.route("/meu-resultado/<int:ciclo_id>/excel")
def meu_resultado_excel(ciclo_id):
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    if not _resultado_liberado_do_ciclo(funcionario, ciclo_id):
        flash("Seu resultado final ainda não foi liberado pela administração.", "warning")
        return redirect(url_for("main.minha_area"))

    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    dados = montar_dados_resultado_final(ciclo, funcionario)
    if dados["resultado_final"] is None:
        flash("Seu resultado final ainda não está disponível.", "warning")
        return redirect(url_for("main.minha_area"))

    excel_buffer = gerar_excel_resultado_final(dados)
    nome_arquivo = f"resultado_final_{funcionario.nome.replace(' ', '_')}_{ciclo.exercicio}.xlsx"
    return Response(
        excel_buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


# ---------------------------------------------------------------------------
# Tarefa automática (chamada 1x/dia pelo Vercel Cron — ver vercel.json):
# manda os lembretes de prazo por e-mail (5 dias, 2 dias e no dia).
# Não é uma tela — não usa login de funcionário/admin. É protegida por um
# segredo (CRON_SECRET) pra ninguém de fora poder disparar isso à toa.
# ---------------------------------------------------------------------------
@main_bp.route("/tarefas/verificar-prazos")
def tarefa_verificar_prazos():
    from flask import current_app, jsonify
    from ..lembretes_service import enviar_lembretes_prazo

    segredo_esperado = current_app.config.get("CRON_SECRET")
    if not segredo_esperado:
        # Sem CRON_SECRET configurado, a rota fica desativada por segurança
        # (nunca deixar essa rota aberta pra qualquer um acionar).
        return jsonify({"erro": "CRON_SECRET não configurado no ambiente."}), 503

    # O Vercel Cron manda automaticamente "Authorization: Bearer <CRON_SECRET>"
    # quando essa variável de ambiente existe no projeto — não precisa
    # configurar isso na mão, só cadastrar CRON_SECRET no painel do Vercel.
    autorizacao = request.headers.get("Authorization", "")
    if autorizacao != f"Bearer {segredo_esperado}":
        return jsonify({"erro": "não autorizado"}), 401

    resumo = enviar_lembretes_prazo()
    return jsonify(resumo)

