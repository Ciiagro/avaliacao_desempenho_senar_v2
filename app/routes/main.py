from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response, g, abort
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    Funcionario,
    VinculoAvaliacao,
    CicloAvaliacao,
    Avaliacao,
    ResultadoFinal,
    Capacitacao,
    TIPOS_CAPACITACAO,
    TIPOS_STATUS_CAPACITACAO,
    TRIMESTRES,
    trimestre_atual,
    limites_trimestre,
)
from ..utils import media_avaliacao, calcular_resultado_final, conceito_resultado, adicionar_dias_uteis, para_fortaleza
from ..resultado_final_service import montar_dados_resultado_final
# gerar_pdf_resultado_final e gerar_excel_resultado_final são importados dentro
# das próprias rotas que os usam (reportlab/openpyxl são pesados pra importar
# e a maioria das páginas do site — login, minha área, etc. — não precisa deles).

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


# ---------------- Capacitações: comprovante ----------------
EXT_COMPROVACAO = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
ASSINATURAS_COMPROVACAO = {
    "application/pdf": (b"%PDF",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
# O servidor (Vercel) aceita corpo de até ~4,5 MB por requisição.
MAX_COMPROVACAO_BYTES = 4 * 1024 * 1024


def _ler_comprovacao(file):
    """Valida o arquivo enviado. Devolve (nome, mimetype, bytes, erro)."""
    if not file or not file.filename:
        return None, None, None, None
    nome = secure_filename(file.filename) or "comprovacao"
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    mimetype = EXT_COMPROVACAO.get(ext)
    if not mimetype:
        return None, None, None, "O documento precisa ser PDF, JPG ou PNG."
    dados = file.read(MAX_COMPROVACAO_BYTES + 1)
    if len(dados) > MAX_COMPROVACAO_BYTES:
        return None, None, None, "O documento é grande demais (máximo de 4 MB)."
    if not any(dados.startswith(a) for a in ASSINATURAS_COMPROVACAO[mimetype]):
        return None, None, None, "O conteúdo do arquivo não corresponde a um PDF, JPG ou PNG válido."
    return nome, mimetype, dados, None


def _parse_data_form(campo):
    valor = request.form.get(campo)
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_decimal_form(campo):
    valor = request.form.get(campo, "").strip()
    if not valor:
        return None
    try:
        return float(valor)
    except ValueError:
        return None


def _parse_carga_horaria_form():
    valor = _parse_decimal_form("carga_horaria")
    return int(round(valor)) if valor is not None else None


def _erro_datas_trimestre(ano, trimestre, data_inicio, data_conclusao):
    """Mensagem de erro se as datas saírem do trimestre; senão None."""
    ini_tri, fim_tri = limites_trimestre(ano, trimestre)
    periodo = f"{ini_tri.strftime('%d/%m/%Y')} a {fim_tri.strftime('%d/%m/%Y')}"
    for rotulo, d in (("início", data_inicio), ("conclusão", data_conclusao)):
        if d and not (ini_tri <= d <= fim_tri):
            return (
                f"A data de {rotulo} precisa estar dentro do {trimestre}º trimestre "
                f"de {ano} ({periodo})."
            )
    if data_inicio and data_conclusao and data_conclusao < data_inicio:
        return "A data de conclusão não pode ser anterior à data de início."
    return None


def resposta_documento_capacitacao(capacitacao):
    """Devolve o comprovante para ser aberto no navegador (usado também pelo admin)."""
    if not capacitacao.arquivo_tipo or not capacitacao.arquivo_dados:
        abort(404)
    resp = Response(bytes(capacitacao.arquivo_dados), mimetype=capacitacao.arquivo_tipo)
    nome = (capacitacao.arquivo_comprovacao or "comprovacao").replace('"', "")
    resp.headers["Content-Disposition"] = f'inline; filename="{nome}"'
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, max-age=0, no-store"
    return resp


@main_bp.route("/minhas-capacitacoes", methods=["GET", "POST"])
def minhas_capacitacoes():
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))
    if funcionario.senha_provisoria:
        return redirect(url_for("main.trocar_senha"))

    # Trimestre selecionado (padrão: o trimestre atual). No POST vem do
    # formulário; no GET, da query string.
    ano_padrao, tri_padrao = trimestre_atual()
    origem = request.form if request.method == "POST" else request.args
    try:
        ano = int(origem.get("ano", ano_padrao))
        trimestre = int(origem.get("trimestre", tri_padrao))
    except (TypeError, ValueError):
        ano, trimestre = ano_padrao, tri_padrao
    if trimestre not in TRIMESTRES or not (2000 <= ano <= 2100):
        ano, trimestre = ano_padrao, tri_padrao

    if request.method == "POST":
        nome_curso = request.form.get("nome_curso", "").strip()
        if not nome_curso:
            flash("Informe o nome do curso/capacitação.", "danger")
            return redirect(url_for("main.minhas_capacitacoes", ano=ano, trimestre=trimestre))

        carga_horaria = _parse_carga_horaria_form()

        # As datas precisam estar dentro do trimestre selecionado.
        data_inicio = _parse_data_form("data_inicio")
        data_conclusao = _parse_data_form("data_conclusao")
        erro_datas = _erro_datas_trimestre(ano, trimestre, data_inicio, data_conclusao)
        if erro_datas:
            flash(erro_datas, "danger")
            return redirect(url_for("main.minhas_capacitacoes", ano=ano, trimestre=trimestre))

        # Documento de comprovação (fica guardado no banco)
        arquivo_nome, arquivo_tipo, arquivo_dados, erro_arquivo = _ler_comprovacao(
            request.files.get("arquivo_comprovacao")
        )
        if erro_arquivo:
            flash(erro_arquivo, "danger")
            return redirect(url_for("main.minhas_capacitacoes", ano=ano, trimestre=trimestre))

        capacitacao = Capacitacao(
            funcionario_id=funcionario.id,
            nome_curso=nome_curso,
            instituicao=request.form.get("instituicao", "").strip() or None,
            tipo=request.form.get("tipo") or None,
            carga_horaria=carga_horaria,
            data_inicio=data_inicio,
            data_conclusao=data_conclusao,
            status=request.form.get("status") or None,
            arquivo_comprovacao=arquivo_nome,
            arquivo_tipo=arquivo_tipo,
            arquivo_dados=arquivo_dados,
            valor_pago_senar=_parse_decimal_form("valor_pago_senar"),
            observacoes=request.form.get("observacoes", "").strip() or None,
            ano=ano,
            trimestre=trimestre,
        )
        db.session.add(capacitacao)
        db.session.commit()
        flash(f"Capacitação adicionada ao {trimestre}º trimestre de {ano}!", "success")
        return redirect(url_for("main.minhas_capacitacoes", ano=ano, trimestre=trimestre))

    lista = (
        Capacitacao.query.filter_by(funcionario_id=funcionario.id, ano=ano, trimestre=trimestre)
        .order_by(Capacitacao.data_conclusao.desc().nullslast(), Capacitacao.criado_em.desc())
        .all()
    )
    ini_tri, fim_tri = limites_trimestre(ano, trimestre)

    total_horas = sum(c.carga_horaria or 0 for c in lista)
    total_valor = sum((c.valor_pago_senar or 0) for c in lista)
    total_valor_fmt = (
        f"R$ {total_valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )
    return render_template(
        "minhas_capacitacoes.html",
        inicio_trimestre=ini_tri,
        fim_trimestre=fim_tri,
        total_horas=total_horas,
        total_valor_fmt=total_valor_fmt,
        funcionario=funcionario,
        capacitacoes=lista,
        tipos=TIPOS_CAPACITACAO,
        status_options=TIPOS_STATUS_CAPACITACAO,
        ano=ano,
        trimestre=trimestre,
        trimestres=TRIMESTRES,
        anos=list(range(ano_padrao - 3, ano_padrao + 2)),
    )


@main_bp.route("/minhas-capacitacoes/<int:capacitacao_id>/editar", methods=["GET", "POST"])
def editar_minha_capacitacao(capacitacao_id):
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))
    if funcionario.senha_provisoria:
        return redirect(url_for("main.trocar_senha"))

    capacitacao = Capacitacao.query.get_or_404(capacitacao_id)
    if str(capacitacao.funcionario_id) != str(funcionario.id):
        flash("Você não tem permissão para editar esta capacitação.", "danger")
        return redirect(url_for("main.minhas_capacitacoes"))

    # A capacitação continua no trimestre em que foi lançada.
    ano, trimestre = capacitacao.ano, capacitacao.trimestre
    voltar = url_for("main.minhas_capacitacoes", ano=ano, trimestre=trimestre)
    ini_tri, fim_tri = limites_trimestre(ano, trimestre)

    if request.method == "POST":
        nome_curso = request.form.get("nome_curso", "").strip()
        if not nome_curso:
            flash("Informe o nome do curso/capacitação.", "danger")
            return redirect(url_for("main.editar_minha_capacitacao", capacitacao_id=capacitacao.id))

        data_inicio = _parse_data_form("data_inicio")
        data_conclusao = _parse_data_form("data_conclusao")
        erro_datas = _erro_datas_trimestre(ano, trimestre, data_inicio, data_conclusao)
        if erro_datas:
            flash(erro_datas, "danger")
            return redirect(url_for("main.editar_minha_capacitacao", capacitacao_id=capacitacao.id))

        arquivo_nome, arquivo_tipo, arquivo_dados, erro_arquivo = _ler_comprovacao(
            request.files.get("arquivo_comprovacao")
        )
        if erro_arquivo:
            flash(erro_arquivo, "danger")
            return redirect(url_for("main.editar_minha_capacitacao", capacitacao_id=capacitacao.id))

        capacitacao.nome_curso = nome_curso
        capacitacao.instituicao = request.form.get("instituicao", "").strip() or None
        capacitacao.tipo = request.form.get("tipo") or None
        capacitacao.status = request.form.get("status") or None
        capacitacao.carga_horaria = _parse_carga_horaria_form()
        capacitacao.data_inicio = data_inicio
        capacitacao.data_conclusao = data_conclusao
        capacitacao.valor_pago_senar = _parse_decimal_form("valor_pago_senar")
        capacitacao.observacoes = request.form.get("observacoes", "").strip() or None

        if arquivo_dados:  # novo comprovante substitui o anterior
            capacitacao.arquivo_comprovacao = arquivo_nome
            capacitacao.arquivo_tipo = arquivo_tipo
            capacitacao.arquivo_dados = arquivo_dados
        elif request.form.get("remover_arquivo"):
            capacitacao.arquivo_comprovacao = None
            capacitacao.arquivo_tipo = None
            capacitacao.arquivo_dados = None

        db.session.commit()
        flash("Capacitação atualizada!", "success")
        return redirect(voltar)

    return render_template(
        "minhas_capacitacoes_editar.html",
        capacitacao=capacitacao,
        tipos=TIPOS_CAPACITACAO,
        status_options=TIPOS_STATUS_CAPACITACAO,
        ano=ano,
        trimestre=trimestre,
        inicio_trimestre=ini_tri,
        fim_trimestre=fim_tri,
        voltar=voltar,
    )


@main_bp.route("/minhas-capacitacoes/<int:capacitacao_id>/documento")
def documento_minha_capacitacao(capacitacao_id):
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    capacitacao = Capacitacao.query.get_or_404(capacitacao_id)
    if str(capacitacao.funcionario_id) != str(funcionario.id):
        abort(403)
    return resposta_documento_capacitacao(capacitacao)


@main_bp.route("/minhas-capacitacoes/<int:capacitacao_id>/excluir", methods=["POST"])
def excluir_minha_capacitacao(capacitacao_id):
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    capacitacao = Capacitacao.query.get_or_404(capacitacao_id)
    if str(capacitacao.funcionario_id) != str(funcionario.id):
        flash("Você não tem permissão para excluir esta capacitação.", "danger")
        return redirect(url_for("main.minhas_capacitacoes"))

    ano, trimestre = capacitacao.ano, capacitacao.trimestre
    db.session.delete(capacitacao)
    db.session.commit()
    flash("Capacitação removida.", "success")
    return redirect(url_for("main.minhas_capacitacoes", ano=ano, trimestre=trimestre))


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
    from ..pdf_resultado_final import gerar_pdf_resultado_final
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    registro = _resultado_liberado_do_ciclo(funcionario, ciclo_id)
    if not registro:
        flash("Seu resultado final ainda não foi liberado pela administração.", "warning")
        return redirect(url_for("main.minha_area"))

    if registro.decisao_avaliado == "recorreu":
        from ..models import RecursoAvaliacao, RECURSO_STATUS_AGUARDANDO_FUNCIONARIO

        recurso_atual = RecursoAvaliacao.query.filter_by(
            ciclo_id=ciclo_id, avaliado_id=funcionario.id
        ).first()
        if recurso_atual and recurso_atual.status == RECURSO_STATUS_AGUARDANDO_FUNCIONARIO:
            flash("Confirme o recebimento e assine a resposta do recurso antes de baixar.", "warning")
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
    from ..excel_resultado_final import gerar_excel_resultado_final
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    registro = _resultado_liberado_do_ciclo(funcionario, ciclo_id)
    if not registro:
        flash("Seu resultado final ainda não foi liberado pela administração.", "warning")
        return redirect(url_for("main.minha_area"))

    if registro.decisao_avaliado == "recorreu":
        from ..models import RecursoAvaliacao, RECURSO_STATUS_AGUARDANDO_FUNCIONARIO

        recurso_atual = RecursoAvaliacao.query.filter_by(
            ciclo_id=ciclo_id, avaliado_id=funcionario.id
        ).first()
        if recurso_atual and recurso_atual.status == RECURSO_STATUS_AGUARDANDO_FUNCIONARIO:
            flash("Confirme o recebimento e assine a resposta do recurso antes de baixar.", "warning")
            return redirect(url_for("main.meu_resultado_detalhe", ciclo_id=ciclo_id))

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

