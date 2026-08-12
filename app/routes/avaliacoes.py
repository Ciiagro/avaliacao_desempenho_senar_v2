from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response

from ..extensions import db
from ..models import (
    Funcionario,
    Formulario,
    Avaliacao,
    RespostaFator,
    CicloAvaliacao,
)
from ..pdf_avaliacao import gerar_pdf_avaliacao

avaliacoes_bp = Blueprint("avaliacoes", __name__)

PONTUACOES_VALIDAS = {4, 6, 8, 10}


def _ciclo_ativo():
    """Ciclo "aberto" marcado como padrão; se nenhum estiver marcado, cai
    pro aberto mais recente (fallback do comportamento antigo)."""
    return (
        CicloAvaliacao.query.filter_by(status="aberto")
        .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
        .first()
    )


@avaliacoes_bp.before_request
def exigir_login_funcionario():
    if not session.get("funcionario_id"):
        flash("Faça login para acessar sua avaliação.", "warning")
        return redirect(url_for("main.login"))


def _pode_ver_avaliacao(avaliacao, meu_id):
    if not meu_id:
        return False
    # O gestor NÃO pode ver a autoavaliação do subordinado — só o avaliador
    # e o próprio avaliado enxergam uma avaliação.
    return str(avaliacao.avaliador_id) == meu_id or str(avaliacao.avaliado_id) == meu_id


@avaliacoes_bp.route("/avaliacao/<uuid:avaliacao_id>/pdf")
def baixar_pdf(avaliacao_id):
    avaliacao = Avaliacao.query.get_or_404(avaliacao_id)
    meu_id = session.get("funcionario_id")

    if not _pode_ver_avaliacao(avaliacao, meu_id):
        flash("Você não tem permissão para baixar essa avaliação.", "danger")
        return redirect(url_for("main.minha_area"))

    if avaliacao.status != "concluida":
        flash("Essa avaliação ainda não foi concluída.", "warning")
        return redirect(url_for("main.minha_area"))

    pdf_buffer = gerar_pdf_avaliacao(avaliacao)
    nome_arquivo = f"avaliacao_{avaliacao.avaliado.nome.replace(' ', '_')}_{avaliacao.tipo}.pdf"
    return Response(
        pdf_buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@avaliacoes_bp.route("/avaliacao/<int:ciclo_id>/<uuid:avaliado_id>/autoavaliacao/ver")
def ver_autoavaliacao(ciclo_id, avaliado_id):
    """
    Visualização só-leitura da autoavaliação, disponível apenas para o
    próprio avaliado. O gestor NÃO pode ver a autoavaliação de quem ele
    avalia.
    """
    meu_id = session.get("funcionario_id")

    eh_o_proprio = str(avaliado_id) == meu_id
    if not eh_o_proprio:
        flash("Você não tem permissão para ver essa autoavaliação.", "danger")
        return redirect(url_for("main.minha_area"))

    avaliado = Funcionario.query.get_or_404(avaliado_id)
    avaliacao = Avaliacao.query.filter_by(
        ciclo_id=ciclo_id, avaliado_id=avaliado_id, avaliador_id=avaliado_id, tipo="auto"
    ).first()

    if not avaliacao or avaliacao.status != "concluida":
        flash("A autoavaliação dessa pessoa ainda não foi concluída.", "warning")
        return redirect(url_for("main.minha_area"))

    respostas_salvas = {r.fator_id: r.pontuacao for r in avaliacao.respostas}

    return render_template(
        "formulario_visualizacao.html",
        avaliado=avaliado,
        formulario=avaliacao.formulario,
        avaliacao=avaliacao,
        respostas_salvas=respostas_salvas,
    )


@avaliacoes_bp.route(
    "/avaliacao/<int:ciclo_id>/<uuid:avaliado_id>/<uuid:avaliador_id>/<tipo>",
    methods=["GET", "POST"],
)
def formulario(ciclo_id, avaliado_id, avaliador_id, tipo):
    if tipo not in ("auto", "gestor"):
        flash("Tipo de avaliação inválido.", "danger")
        return redirect(url_for("main.index"))

    # Só a própria pessoa (autoavaliação) ou o avaliador vinculado (gestor) pode acessar
    if str(avaliador_id) != session.get("funcionario_id"):
        flash("Você só pode preencher avaliações em que você é o avaliador.", "danger")
        return redirect(url_for("main.minha_area"))

    if tipo == "auto" and str(avaliado_id) != str(avaliador_id):
        flash("Autoavaliação só pode ser feita por você mesmo.", "danger")
        return redirect(url_for("main.minha_area"))

    avaliado = Funcionario.query.get_or_404(avaliado_id)
    avaliador = Funcionario.query.get_or_404(avaliador_id)

    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    prazo = ciclo.data_limite_autoavaliacao if tipo == "auto" else ciclo.data_limite_gestor
    prazo_encerrado = prazo is not None and date.today() > prazo

    formulario_obj = Formulario.query.filter_by(
        nivel_hierarquico=avaliado.nivel_hierarquico
    ).first()
    if not formulario_obj:
        flash(
            f"Não existe formulário cadastrado para o nível hierárquico de {avaliado.nome}.",
            "danger",
        )
        return redirect(url_for("main.index"))

    avaliacao = Avaliacao.query.filter_by(
        ciclo_id=ciclo_id,
        avaliado_id=avaliado_id,
        avaliador_id=avaliador_id,
        tipo=tipo,
    ).first()

    # Depois de concluída e assinada, a avaliação passa a ser só-leitura —
    # nenhuma edição por aqui. (Correções feitas através do recurso usam um
    # caminho próprio, que continua funcionando normalmente.)
    ja_concluida = bool(avaliacao and avaliacao.status == "concluida")

    if request.method == "POST":
        if ja_concluida:
            flash(
                "Essa avaliação já foi concluída e assinada — não é mais possível editá-la.",
                "danger",
            )
            return redirect(url_for("main.minha_area"))

        if prazo_encerrado:
            flash(
                f"O prazo para esta avaliação encerrou em {prazo.strftime('%d/%m/%Y')}. "
                "Não é mais possível salvar alterações.",
                "danger",
            )
            return redirect(url_for("main.minha_area"))

        rascunho = request.form.get("acao") == "rascunho"

        if not rascunho:
            fatores_faltando = []
            for fator in formulario_obj.fatores:
                valor = request.form.get(f"fator_{fator.id}")
                valido = False
                if valor:
                    try:
                        valido = int(valor) in PONTUACOES_VALIDAS
                    except ValueError:
                        valido = False
                if not valido:
                    fatores_faltando.append(fator.nome)

            campos_texto = {
                "pontos_fortes": "Pontos fortes",
                "oportunidades_desenvolvimento": "Oportunidade de desenvolvimento",
                "plano_acao": "Plano de desenvolvimento — Ação",
                "resultados_alcancados": "Resultados alcançados durante o ano",
            }
            campos_faltando = [
                rotulo
                for campo, rotulo in campos_texto.items()
                if not request.form.get(campo, "").strip()
            ]

            if fatores_faltando or campos_faltando:
                partes = []
                if fatores_faltando:
                    partes.append("os fatores (" + ", ".join(fatores_faltando) + ")")
                if campos_faltando:
                    partes.append("os campos (" + ", ".join(campos_faltando) + ")")
                flash(
                    "Para concluir, preencha " + " e ".join(partes)
                    + ". Enquanto estiver em rascunho, isso não é obrigatório.",
                    "danger",
                )
                return redirect(
                    url_for(
                        "avaliacoes.formulario",
                        ciclo_id=ciclo_id,
                        avaliado_id=avaliado_id,
                        avaliador_id=avaliador_id,
                        tipo=tipo,
                    )
                )

            if not request.form.get("confirmo_assinatura"):
                flash(
                    "Para concluir, marque a confirmação de que as informações são verdadeiras (assinatura eletrônica).",
                    "danger",
                )
                return redirect(
                    url_for(
                        "avaliacoes.formulario",
                        ciclo_id=ciclo_id,
                        avaliado_id=avaliado_id,
                        avaliador_id=avaliador_id,
                        tipo=tipo,
                    )
                )

        if not avaliacao:
            avaliacao = Avaliacao(
                ciclo_id=ciclo_id,
                avaliado_id=avaliado_id,
                avaliador_id=avaliador_id,
                tipo=tipo,
                formulario_id=formulario_obj.id,
            )
            db.session.add(avaliacao)
            db.session.flush()  # garante avaliacao.id antes de salvar respostas

        # Parte I - fatores
        for fator in formulario_obj.fatores:
            valor = request.form.get(f"fator_{fator.id}")
            if valor is None or valor == "":
                continue
            pontuacao = int(valor)
            if pontuacao not in PONTUACOES_VALIDAS:
                continue

            resposta = RespostaFator.query.filter_by(
                avaliacao_id=avaliacao.id, fator_id=fator.id
            ).first()
            if resposta:
                resposta.pontuacao = pontuacao
            else:
                db.session.add(
                    RespostaFator(
                        avaliacao_id=avaliacao.id,
                        fator_id=fator.id,
                        pontuacao=pontuacao,
                    )
                )

        # Parte II - campos abertos
        avaliacao.pontos_fortes = request.form.get("pontos_fortes", "")
        avaliacao.oportunidades_desenvolvimento = request.form.get(
            "oportunidades_desenvolvimento", ""
        )
        avaliacao.plano_acao = request.form.get("plano_acao", "")
        avaliacao.resultados_alcancados = request.form.get(
            "resultados_alcancados", ""
        )

        avaliacao.status = "em_andamento" if rascunho else "concluida"
        if not rascunho:
            avaliacao.assinado_por = avaliador.nome
            avaliacao.assinado_em = datetime.utcnow()

        db.session.commit()

        flash(
            "Avaliação salva como rascunho."
            if rascunho
            else "Avaliação concluída e assinada com sucesso!",
            "success",
        )

        return redirect(url_for("main.minha_area"))

    # GET: monta dicionário fator_id -> pontuação já salva (se houver)
    respostas_salvas = {}
    if avaliacao:
        for r in avaliacao.respostas:
            respostas_salvas[r.fator_id] = r.pontuacao

    return render_template(
        "formulario_avaliacao.html",
        avaliado=avaliado,
        avaliador=avaliador,
        formulario=formulario_obj,
        avaliacao=avaliacao,
        respostas_salvas=respostas_salvas,
        tipo=tipo,
        ciclo_id=ciclo_id,
        prazo=prazo,
        prazo_encerrado=prazo_encerrado,
        ja_concluida=ja_concluida,
    )
