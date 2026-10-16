import uuid
from datetime import datetime, timezone, date as _date

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
from ..utils import media_avaliacao, calcular_resultado_final, conceito_resultado, adicionar_dias_uteis, para_fortaleza, FUSO_FORTALEZA
from ..resultado_final_service import montar_dados_resultado_final, vinculo_do_avaliado
from .. import senhas as regras_senha
from .. import email_service
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
        funcionario = regras_senha.buscar_funcionario_ativo_por_email(email)

        if funcionario:
            minutos = regras_senha.minutos_de_bloqueio_restantes(funcionario)
            if minutos:
                flash(
                    f"Muitas tentativas erradas. Tente de novo em {minutos} minuto(s) "
                    f"ou use \"Esqueci minha senha\".",
                    "danger",
                )
                return render_template("login.html")

        if funcionario and funcionario.checar_senha(senha):
            regras_senha.limpar_tentativas_login(funcionario)
            db.session.commit()
            session["funcionario_id"] = str(funcionario.id)
            if funcionario.senha_provisoria:
                return redirect(url_for("main.trocar_senha"))
            return redirect(url_for("main.minha_area"))

        if funcionario:
            regras_senha.registrar_login_errado(funcionario)
            db.session.commit()
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

        erro_senha_nova = regras_senha.validar_senha_nova(senha_nova, funcionario)
        if not funcionario.checar_senha(senha_atual):
            flash("Senha atual incorreta.", "danger")
        elif erro_senha_nova:
            flash(erro_senha_nova, "danger")
        elif senha_nova == senha_atual:
            flash("A nova senha precisa ser diferente da senha atual.", "danger")
        elif senha_nova != senha_confirmar:
            flash("A confirmação não bate com a nova senha.", "danger")
        else:
            funcionario.set_senha(senha_nova)
            funcionario.senha_provisoria = False
            regras_senha.invalidar_tokens_pendentes(funcionario)
            db.session.commit()
            flash("Senha alterada com sucesso.", "success")
            return redirect(url_for("main.minha_area"))

    return render_template("trocar_senha.html", forcado=funcionario.senha_provisoria)


# Mesma resposta, exista o e-mail ou não: assim ninguém usa este formulário
# para descobrir quem tem cadastro no sistema.
_MSG_ESQUECI = (
    "Se esse e-mail estiver cadastrado, enviamos um link para criar uma nova senha. "
    "Ele vale por {minutos} minutos. Confira também a caixa de spam."
)


@main_bp.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        funcionario = regras_senha.buscar_funcionario_ativo_por_email(
            request.form.get("email", "")
        )
        if funcionario:
            token = regras_senha.criar_token_redefinicao(funcionario)
            db.session.commit()
            if token:
                link = url_for("main.redefinir_senha", token=token, _external=True)
                email_service.avisar_redefinicao_senha(
                    funcionario, link, regras_senha.TOKEN_VALIDADE_MINUTOS
                )
        flash(_MSG_ESQUECI.format(minutos=regras_senha.TOKEN_VALIDADE_MINUTOS), "success")
        return redirect(url_for("main.esqueci_senha"))
    return render_template("esqueci_senha.html")


@main_bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    registro = regras_senha.buscar_token_valido(token)
    if not registro:
        flash("Este link venceu ou já foi usado. Peça um novo.", "danger")
        return redirect(url_for("main.esqueci_senha"))

    funcionario = Funcionario.query.get(registro.funcionario_id)
    if not funcionario or not funcionario.ativo:
        flash("Este link venceu ou já foi usado. Peça um novo.", "danger")
        return redirect(url_for("main.esqueci_senha"))

    if request.method == "POST":
        senha_nova = request.form.get("senha_nova", "")
        senha_confirmar = request.form.get("senha_confirmar", "")
        erro = regras_senha.validar_senha_nova(senha_nova, funcionario)
        if erro:
            flash(erro, "danger")
        elif senha_nova != senha_confirmar:
            flash("A confirmação não bate com a nova senha.", "danger")
        elif not regras_senha.consumir_token(token):
            # outro clique/aba usou o link no mesmo instante
            db.session.rollback()
            flash("Este link venceu ou já foi usado. Peça um novo.", "danger")
            return redirect(url_for("main.esqueci_senha"))
        else:
            funcionario.set_senha(senha_nova)
            funcionario.senha_provisoria = False
            regras_senha.limpar_tentativas_login(funcionario)
            regras_senha.invalidar_tokens_pendentes(funcionario)
            db.session.commit()
            email_service.avisar_senha_alterada(funcionario)
            flash("Senha criada com sucesso. Entre com a nova senha.", "success")
            return redirect(url_for("main.login"))

    return render_template("redefinir_senha.html", token=token)


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

        meu_vinculo = vinculo_do_avaliado(registro.ciclo_id, funcionario.id)
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


_DIAS_SEMANA = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _data_por_extenso():
    """Ex: "Terça-feira, 13 de outubro de 2026" (data de hoje em Fortaleza)."""
    hoje = para_fortaleza(datetime.now(timezone.utc))
    return f"{_DIAS_SEMANA[hoje.weekday()]}, {hoje.day} de {_MESES[hoje.month - 1]} de {hoje.year}"


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
            data_extenso=_data_por_extenso(),
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
        data_extenso=_data_por_extenso(),
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
MAX_COMPROVACAO_BYTES = 2 * 1024 * 1024


MAX_ENTRADA_BYTES = 4 * 1024 * 1024  # fotos maiores são aceitas e reduzidas automaticamente


def _reduzir_imagem(dados):
    """Reduz foto/imagem (lado maior 1600 px, JPEG qualidade 78). Devolve os bytes ou None se não compensar."""
    try:
        from PIL import Image, ImageOps
        import io
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(dados)))
        img.thumbnail((1600, 1600))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            fundo = Image.new("RGB", img.size, (255, 255, 255))
            fundo.paste(img, mask=img.split()[-1])
            img = fundo
        else:
            img = img.convert("RGB")
        saida = io.BytesIO()
        img.save(saida, "JPEG", quality=78, optimize=True)
        return saida.getvalue() if len(saida.getvalue()) < len(dados) else None
    except Exception:
        return None


def _ler_comprovacao(file):
    """Valida o arquivo enviado. Devolve (nome, mimetype, bytes, erro)."""
    if not file or not file.filename:
        return None, None, None, None
    nome = secure_filename(file.filename) or "comprovacao"
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    mimetype = EXT_COMPROVACAO.get(ext)
    if not mimetype:
        return None, None, None, "O documento precisa ser PDF, JPG ou PNG."
    dados = file.read(MAX_ENTRADA_BYTES + 1)
    if len(dados) > MAX_ENTRADA_BYTES:
        return None, None, None, "O documento é grande demais (máximo de 4 MB)."
    if not any(dados.startswith(a) for a in ASSINATURAS_COMPROVACAO[mimetype]):
        return None, None, None, "O conteúdo do arquivo não corresponde a um PDF, JPG ou PNG válido."
    if mimetype != "application/pdf":
        reduzido = _reduzir_imagem(dados)
        if reduzido:
            dados, mimetype = reduzido, "image/jpeg"
            nome = nome.rsplit(".", 1)[0] + ".jpg"
    if len(dados) > MAX_COMPROVACAO_BYTES:
        return None, None, None, "O documento é grande demais (máximo de 2 MB). Em PDF, reduza o tamanho antes de enviar."
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


MAX_TRIMESTRES_CURSO = 20
FILTROS_CURSO = {"todos": None, "andamento": "Em andamento", "concluidos": "Concluído", "desistentes": "Desistente"}


def _fmt_h(v):
    return f"{v:g}h"


def _fmt_reais(v):
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _chave_tri(ano, tri):
    return ano * 4 + (tri - 1)


def _de_chave(chave):
    return chave // 4, chave % 4 + 1


def _tri_da_data(d):
    return d.year, (d.month - 1) // 3 + 1


def _horas_proporcionais(total, ini_curso, fim_curso, ano, tri):
    """Horas sugeridas do trimestre = total x (dias do curso no trimestre / dias do curso)."""
    if not (total and ini_curso and fim_curso) or fim_curso < ini_curso:
        return 0
    ini_tri, fim_tri = limites_trimestre(ano, tri)
    dias = (min(fim_curso, fim_tri) - max(ini_curso, ini_tri)).days + 1
    if dias <= 0:
        return 0
    return int(round(total * dias / ((fim_curso - ini_curso).days + 1)))


def _chaves_do_curso(ini, fim):
    return range(_chave_tri(*_tri_da_data(ini)), _chave_tri(*_tri_da_data(fim)) + 1)


def _curso_key(c):
    return f"g_{c.grupo_curso}" if c.grupo_curso else f"c_{c.id}"


def _linhas_do_curso(funcionario_id, key):
    """Trimestres (linhas) de um curso do funcionário, em ordem."""
    q = Capacitacao.query.filter_by(funcionario_id=funcionario_id)
    try:
        if key.startswith("g_"):
            q = q.filter_by(grupo_curso=uuid.UUID(key[2:]))
        elif key.startswith("c_"):
            q = q.filter_by(id=int(key[2:]))
        else:
            return []
    except ValueError:
        return []
    return q.order_by(Capacitacao.ano, Capacitacao.trimestre, Capacitacao.id).all()


def _montar_curso(linhas):
    base = linhas[0]
    grupo = bool(base.grupo_curso)
    confirmadas = [r for r in linhas if not r.previsto]
    total_h = base.carga_horaria_total or base.carga_horaria or 0
    total_v = base.valor_total_senar if base.valor_total_senar is not None else base.valor_pago_senar
    desistente = any(r.status == "Desistente" for r in linhas)
    if desistente:
        situacao = "Desistente"
    elif grupo and base.data_conclusao:
        situacao = "Concluído" if base.data_conclusao < _date.today() else "Em andamento"
    else:
        situacao = base.status or "Em andamento"
    return {
        "key": _curso_key(base), "base": base, "linhas": linhas, "grupo": grupo,
        "classe": base.classe, "longo": base.classe == "Longo",
        "nome": base.nome_curso, "instituicao": base.instituicao, "tipo": base.tipo,
        "ini": base.data_inicio, "fim": base.data_conclusao,
        "total_h": total_h, "total_v": total_v, "situacao": situacao,
        "horas_ok": sum(r.carga_horaria or 0 for r in confirmadas),
        "valor_ok": sum(float(r.valor_pago_senar or 0) for r in confirmadas),
        "pendentes": sum(1 for r in linhas if r.previsto),
    }


def _ratear_valores(linhas, so_vazios=False):
    """Divide em parcelas IGUAIS o que falta do valor total entre os trimestres sem comprovante."""
    base = linhas[0]
    if base.valor_total_senar is None:
        return False
    pend = sorted((r for r in linhas if r.previsto), key=lambda r: (r.ano, r.trimestre))
    if not pend or (so_vazios and all(r.valor_pago_senar is not None for r in pend)):
        return False
    resta = float(base.valor_total_senar) - sum(float(r.valor_pago_senar or 0) for r in linhas if not r.previsto)
    resta = max(resta, 0)
    parcela = round(resta / len(pend), 2)
    novos = [parcela] * (len(pend) - 1) + [round(max(resta - parcela * (len(pend) - 1), 0), 2)]
    mudou = False
    for r, v in zip(pend, novos):
        if r.valor_pago_senar is None or abs(float(r.valor_pago_senar) - v) > 0.001:
            r.valor_pago_senar = v
            mudou = True
    return mudou


def _preencher_valores_previstos(linhas):
    """Cursos criados antes da divisão automática: preenche o valor previsto dos trimestres sem comprovante."""
    return _ratear_valores(linhas)


def _cursos_do_funcionario(funcionario_id):
    linhas = (
        Capacitacao.query.filter_by(funcionario_id=funcionario_id)
        .order_by(Capacitacao.ano, Capacitacao.trimestre, Capacitacao.id).all()
    )
    grupos = {}
    for r in linhas:
        grupos.setdefault(_curso_key(r), []).append(r)
    if any([_preencher_valores_previstos(g) for g in grupos.values()]):
        db.session.commit()
    cursos = [_montar_curso(g) for g in grupos.values()]
    cursos.sort(key=lambda c: (c["fim"] or c["base"].criado_em.date() if c["base"].criado_em else _date.min), reverse=True)
    return cursos


def _outros_confirmados(funcionario_id, grupo, excluir_id):
    if not grupo:
        return []
    return Capacitacao.query.filter(
        Capacitacao.funcionario_id == funcionario_id, Capacitacao.grupo_curso == grupo,
        Capacitacao.previsto.is_(False), Capacitacao.id != excluir_id,
    ).all()


def _erro_soma_trimestres(linha, carga_horaria, valor):
    """A soma dos trimestres comprovados não pode passar do total do curso."""
    total_h = linha.carga_horaria_total
    total_v = float(linha.valor_total_senar) if linha.valor_total_senar is not None else None
    outros = _outros_confirmados(linha.funcionario_id, linha.grupo_curso, linha.id)
    horas_outros = sum(r.carga_horaria or 0 for r in outros)
    valor_outros = sum(float(r.valor_pago_senar or 0) for r in outros)
    if total_h and carga_horaria is not None and horas_outros + carga_horaria > total_h:
        return (
            f"Somando os outros trimestres comprovados ({_fmt_h(horas_outros)}), essas horas passam da carga "
            f"horária total do curso ({_fmt_h(total_h)}). Neste trimestre o máximo é {_fmt_h(max(total_h - horas_outros, 0))}."
        )
    if total_v is not None and valor is not None and valor_outros + valor > total_v + 0.001:
        return (
            f"Somando os outros trimestres comprovados ({_fmt_reais(valor_outros)}), esse valor passa do total do curso "
            f"({_fmt_reais(total_v)}). Neste trimestre o máximo é {_fmt_reais(max(total_v - valor_outros, 0))}."
        )
    return None


def _sincronizar_curso(linhas, interrompido=False):
    """Mantém os trimestres do curso coerentes com as datas e totais: refaz as horas sugeridas dos
    pendentes, apaga os pendentes fora do período e cria os que faltam."""
    base = linhas[0]
    if not (base.data_inicio and base.data_conclusao and base.carga_horaria_total):
        return
    chaves = set(_chaves_do_curso(base.data_inicio, base.data_conclusao))
    existentes = {}
    for r in linhas:
        k = _chave_tri(r.ano, r.trimestre)
        if r.previsto and k not in chaves:
            db.session.delete(r)
            continue
        existentes[k] = r
        if r.previsto:
            r.carga_horaria = _horas_proporcionais(
                base.carga_horaria_total, base.data_inicio, base.data_conclusao, r.ano, r.trimestre
            )
    if interrompido:
        db.session.flush()
        _ratear_valores(Capacitacao.query.filter_by(funcionario_id=base.funcionario_id, grupo_curso=base.grupo_curso).all())
        return
    for k in sorted(chaves):
        if k in existentes:
            continue
        a, t = _de_chave(k)
        db.session.add(Capacitacao(
            funcionario_id=base.funcionario_id, grupo_curso=base.grupo_curso, previsto=True,
            nome_curso=base.nome_curso, instituicao=base.instituicao, tipo=base.tipo, status="Em andamento",
            carga_horaria_total=base.carga_horaria_total, valor_total_senar=base.valor_total_senar,
            data_inicio=base.data_inicio, data_conclusao=base.data_conclusao, ano=a, trimestre=t,
            carga_horaria=_horas_proporcionais(base.carga_horaria_total, base.data_inicio, base.data_conclusao, a, t),
        ))
    db.session.flush()
    _ratear_valores(Capacitacao.query.filter_by(funcionario_id=base.funcionario_id, grupo_curso=base.grupo_curso).all())


def _dados_curso_form():
    """Lê e valida os campos do curso. Devolve (dados, erro)."""
    f = request.form
    from app import formatar_titulo
    nome = formatar_titulo(f.get("nome_curso", ""))
    instituicao = f.get("instituicao", "").strip().upper()
    tipo = f.get("tipo", "")
    ini, fim = _parse_data_form("data_inicio"), _parse_data_form("data_conclusao")
    total_h = _parse_decimal_form("carga_horaria_total")
    total_v = _parse_decimal_form("valor_total_senar")
    faltando = []
    if not nome:
        faltando.append("nome do curso")
    if not instituicao:
        faltando.append("instituição")
    if not tipo:
        faltando.append("tipo")
    if not ini:
        faltando.append("data de início")
    if not fim:
        faltando.append("data de término")
    if total_h is None or total_h <= 0:
        faltando.append("carga horária total")
    if total_v is None or total_v < 0:
        faltando.append("valor total pago pelo SENAR (informe 0 se não houve custo)")
    if faltando:
        return None, "Preencha todos os campos obrigatórios: " + ", ".join(faltando) + "."
    if fim < ini:
        return None, "A data de término não pode ser anterior à data de início."
    if len(_chaves_do_curso(ini, fim)) > MAX_TRIMESTRES_CURSO:
        return None, f"O período do curso é muito longo (máximo de {MAX_TRIMESTRES_CURSO} trimestres)."
    return dict(nome=nome, instituicao=instituicao, tipo=tipo, ini=ini, fim=fim,
                total_h=int(round(total_h)), total_v=total_v), None


def _url_curso(key, aba=None, **extra):
    return url_for("main.minhas_capacitacoes", curso=key, aba=aba, **extra)


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


def _funcionario_capacitacoes():
    funcionario = funcionario_logado()
    if not funcionario:
        return None, redirect(url_for("main.login"))
    if funcionario.senha_provisoria:
        return None, redirect(url_for("main.trocar_senha"))
    return funcionario, None


@main_bp.route("/minhas-capacitacoes", methods=["GET", "POST"])
def minhas_capacitacoes():
    funcionario, resp = _funcionario_capacitacoes()
    if resp:
        return resp

    if request.method == "POST":
        dados, erro = _dados_curso_form()
        if erro:
            flash(erro, "danger")
            return redirect(url_for("main.minhas_capacitacoes", novo=1))
        arquivo_nome, arquivo_tipo, arquivo_dados, erro_arquivo = _ler_comprovacao(request.files.get("arquivo_comprovacao"))
        if erro_arquivo:
            flash(erro_arquivo, "danger")
            return redirect(url_for("main.minhas_capacitacoes", novo=1))

        grupo = uuid.uuid4()
        chaves = list(_chaves_do_curso(dados["ini"], dados["fim"]))
        if len(chaves) == 1 and not arquivo_dados:
            flash("O comprovante é obrigatório: anexe o certificado ou a declaração de matrícula/frequência.", "danger")
            return redirect(url_for("main.minhas_capacitacoes", novo=1))
        horas = [_horas_proporcionais(dados["total_h"], dados["ini"], dados["fim"], *_de_chave(k)) for k in chaves]
        horas[-1] = max(horas[-1] + dados["total_h"] - sum(horas), 0)  # a soma fecha com o total
        total_v = float(dados["total_v"])
        parcela = round(total_v / len(chaves), 2)
        valores = [parcela] * len(chaves)
        valores[-1] = round(max(total_v - parcela * (len(chaves) - 1), 0), 2)  # a soma fecha com o total
        for k, h, v in zip(chaves, horas, valores):
            a, t = _de_chave(k)
            db.session.add(Capacitacao(
                funcionario_id=funcionario.id, grupo_curso=grupo, previsto=True, status="Em andamento",
                nome_curso=dados["nome"], instituicao=dados["instituicao"], tipo=dados["tipo"],
                carga_horaria_total=dados["total_h"], valor_total_senar=dados["total_v"],
                data_inicio=dados["ini"], data_conclusao=dados["fim"], ano=a, trimestre=t, carga_horaria=h,
                valor_pago_senar=v,
            ))
        db.session.flush()
        # Curso de um trimestre só, já com comprovante: fica confirmado na hora.
        if len(chaves) == 1:
            primeira = Capacitacao.query.filter_by(grupo_curso=grupo).first()
            primeira.arquivo_comprovacao, primeira.arquivo_tipo, primeira.arquivo_dados = arquivo_nome, arquivo_tipo, arquivo_dados
            primeira.previsto = False
            primeira.valor_pago_senar = dados["total_v"]
        db.session.commit()
        if len(chaves) > 1:
            flash("Curso de longa duração cadastrado. Os trimestres foram criados: anexe o comprovante de cada um.", "success")
            return redirect(_url_curso(f"g_{grupo}", "trimestres"))
        flash("Curso cadastrado com o comprovante.", "success")
        return redirect(url_for("main.minhas_capacitacoes"))

    filtro = request.args.get("filtro", "todos")
    if filtro not in FILTROS_CURSO:
        filtro = "todos"
    busca = request.args.get("q", "").strip()
    todos = _cursos_do_funcionario(funcionario.id)
    anos = sorted({r.ano for c in todos for r in c["linhas"]}, reverse=True)
    ano = request.args.get("ano", type=int)
    if ano not in anos:
        ano = None
    cursos = [
        c for c in todos
        if (FILTROS_CURSO[filtro] is None or c["situacao"] == FILTROS_CURSO[filtro])
        and (ano is None or any(r.ano == ano for r in c["linhas"]))
        and (not busca or busca.lower() in (c["nome"] or "").lower() or busca.lower() in (c["instituicao"] or "").lower())
    ]
    selecionado = next((c for c in todos if c["key"] == request.args.get("curso")), None)
    por_pagina = 8
    total_paginas = max(-(-len(cursos) // por_pagina), 1)
    pagina = min(max(request.args.get("pagina", 1, type=int), 1), total_paginas)
    cursos_pagina = cursos[(pagina - 1) * por_pagina: pagina * por_pagina]
    aba = request.args.get("aba", "trimestres")
    if aba not in ("informacoes", "trimestres") or (selecionado and not selecionado["longo"]):
        aba = "trimestres" if (selecionado and selecionado["longo"]) else "informacoes"
    return render_template(
        "minhas_capacitacoes.html",
        funcionario=funcionario, cursos=cursos_pagina, total_filtrados=len(cursos), pagina=pagina, total_paginas=total_paginas, total_cursos=len(todos), selecionado=selecionado,
        filtro=filtro, busca=busca, anos=anos, ano=ano, aba=aba, abrir_novo=bool(request.args.get("novo")) or not todos,
        tipos=TIPOS_CAPACITACAO, filtros=list(FILTROS_CURSO),
    )


@main_bp.route("/minhas-capacitacoes/curso/<key>/editar", methods=["POST"])
def editar_curso(key):
    funcionario, resp = _funcionario_capacitacoes()
    if resp:
        return resp
    linhas = _linhas_do_curso(funcionario.id, key)
    if not linhas:
        abort(404)
    dados, erro = _dados_curso_form()
    if erro:
        flash(erro, "danger")
        return redirect(_url_curso(key, "informacoes"))
    curso = _montar_curso(linhas)
    if dados["total_h"] < curso["horas_ok"]:
        flash(f"A carga horária total não pode ser menor que as horas já comprovadas ({_fmt_h(curso['horas_ok'])}).", "danger")
        return redirect(_url_curso(key, "informacoes"))
    if float(dados["total_v"]) + 0.001 < curso["valor_ok"]:
        flash(f"O valor total não pode ser menor que o já comprovado ({_fmt_reais(curso['valor_ok'])}).", "danger")
        return redirect(_url_curso(key, "informacoes"))
    grupo = linhas[0].grupo_curso or uuid.uuid4()
    for r in linhas:
        r.grupo_curso = grupo
        r.nome_curso, r.instituicao, r.tipo = dados["nome"], dados["instituicao"], dados["tipo"]
        r.data_inicio, r.data_conclusao = dados["ini"], dados["fim"]
        r.carga_horaria_total, r.valor_total_senar = dados["total_h"], dados["total_v"]
    db.session.flush()
    _sincronizar_curso(linhas, interrompido=curso["situacao"] == "Desistente")
    db.session.commit()
    flash("Informações do curso atualizadas.", "success")
    return redirect(_url_curso(f"g_{grupo}", "informacoes"))


@main_bp.route("/minhas-capacitacoes/curso/<key>/excluir", methods=["POST"])
def excluir_curso(key):
    funcionario, resp = _funcionario_capacitacoes()
    if resp:
        return resp
    linhas = _linhas_do_curso(funcionario.id, key)
    if not linhas:
        abort(404)
    for r in linhas:
        db.session.delete(r)
    db.session.commit()
    flash("Curso removido.", "success")
    return redirect(url_for("main.minhas_capacitacoes"))


@main_bp.route("/minhas-capacitacoes/curso/<key>/desistir", methods=["POST"])
def desistir_curso(key):
    funcionario, resp = _funcionario_capacitacoes()
    if resp:
        return resp
    linhas = _linhas_do_curso(funcionario.id, key)
    if not linhas:
        abort(404)
    volta = _url_curso(key, "informacoes")
    d = _parse_data_form("data_desistencia")
    if not d:
        flash("Informe a data em que você parou o curso.", "danger")
        return redirect(volta)
    if linhas[0].data_inicio and d < linhas[0].data_inicio:
        flash("A data não pode ser anterior ao início do curso.", "danger")
        return redirect(volta)
    chave_d = _chave_tri(*_tri_da_data(d))
    for r in linhas:
        k = _chave_tri(r.ano, r.trimestre)
        if k > chave_d:
            if r.previsto:
                db.session.delete(r)
            continue
        r.data_conclusao = d
        if k == chave_d:
            r.status = "Desistente"
    if not any(r.status == "Desistente" for r in linhas):  # data num trimestre sem linha: marca a última
        linhas[-1].status = "Desistente"
    db.session.commit()
    flash(
        f"Curso marcado como desistente em {d.strftime('%d/%m/%Y')}. Os trimestres seguintes que aguardavam "
        "comprovante foram removidos; os já comprovados continuam como estavam.",
        "success",
    )
    return redirect(volta)


@main_bp.route("/minhas-capacitacoes/<int:capacitacao_id>/trimestre", methods=["GET", "POST"])
def comprovar_trimestre(capacitacao_id):
    funcionario, resp = _funcionario_capacitacoes()
    if resp:
        return resp
    linha = Capacitacao.query.get_or_404(capacitacao_id)
    if str(linha.funcionario_id) != str(funcionario.id):
        flash("Você não tem permissão para alterar esta capacitação.", "danger")
        return redirect(url_for("main.minhas_capacitacoes"))
    key = _curso_key(linha)
    volta = _url_curso(key, "trimestres")

    if request.method == "POST":
        carga = _parse_carga_horaria_form()
        gratuito = not (linha.valor_total_senar or 0)
        valor = 0 if gratuito else _parse_decimal_form("valor_pago_senar")
        arquivo = request.files.get("arquivo_comprovacao")
        envia_novo = bool(arquivo and arquivo.filename)
        faltando = []
        if carga is None or carga < 0:
            faltando.append("carga horária do trimestre")
        if valor is None or valor < 0:
            faltando.append("valor pago pelo SENAR (informe 0 se não houve custo)")
        if not envia_novo and not linha.arquivo_tipo:
            faltando.append("comprovante (declaração de matrícula ou frequência, ou certificado)")
        if faltando:
            flash("Preencha: " + ", ".join(faltando) + ".", "danger")
            return redirect(url_for("main.comprovar_trimestre", capacitacao_id=linha.id))
        erro = _erro_soma_trimestres(linha, carga, valor)
        if erro:
            flash(erro, "danger")
            return redirect(url_for("main.comprovar_trimestre", capacitacao_id=linha.id))
        nome, tipo, dados_arq, erro_arq = _ler_comprovacao(arquivo)
        if erro_arq:
            flash(erro_arq, "danger")
            return redirect(url_for("main.comprovar_trimestre", capacitacao_id=linha.id))
        linha.carga_horaria, linha.valor_pago_senar = carga, valor
        linha.observacoes = request.form.get("observacoes", "").strip() or None
        if dados_arq:
            linha.arquivo_comprovacao, linha.arquivo_tipo, linha.arquivo_dados = nome, tipo, dados_arq
        linha.previsto = False
        db.session.commit()
        flash("Trimestre comprovado.", "success")
        return redirect(volta)

    curso = _montar_curso(_linhas_do_curso(funcionario.id, key))
    outros_h = curso["horas_ok"] - (0 if linha.previsto else (linha.carga_horaria or 0))
    outros_v = curso["valor_ok"] - (0 if linha.previsto else float(linha.valor_pago_senar or 0))
    return render_template(
        "minhas_capacitacoes_trimestre.html", linha=linha, curso=curso, volta=volta,
        restam_h=max((curso["total_h"] or 0) - outros_h, 0),
        restam_v=max(float(curso["total_v"] or 0) - outros_v, 0),
        gratuito=not (linha.valor_total_senar or 0),
        fim_tri=limites_trimestre(linha.ano, linha.trimestre)[1],
        ini_tri=limites_trimestre(linha.ano, linha.trimestre)[0],
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



def _sou_gestor_de(funcionario, avaliado_id):
    """Verifica se `funcionario` já foi (ou é) avaliador de gestor dessa
    pessoa em algum ciclo — é o que dá a ele o direito de ver as
    capacitações dela. Não trava pelo ciclo estar aberto, senão o gestor
    perde o acesso assim que o exercício fecha."""
    return (
        VinculoAvaliacao.query.filter_by(
            avaliador_id=funcionario.id, avaliado_id=avaliado_id
        ).first()
        is not None
    )


def _cursos_confirmados(funcionario_id, ano=None, trimestre=None):
    """Todos os cursos cadastrados por uma pessoa (uma linha por curso), só leitura."""
    linhas = (
        Capacitacao.query.filter_by(funcionario_id=funcionario_id)
        .order_by(Capacitacao.ano, Capacitacao.trimestre, Capacitacao.id).all()
    )
    grupos = {}
    for r in linhas:
        grupos.setdefault(_curso_key(r), []).append(r)
    cursos = [_montar_curso(g) for g in grupos.values()]
    cursos.sort(key=lambda c: (c["fim"] or _date.min), reverse=True)
    return cursos


@main_bp.route("/minha-equipe/capacitacoes")
def capacitacoes_de_todos_da_equipe():
    """Gestor vê, numa tela só, as capacitações de todos que ele avalia."""
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))
    ciclo = ciclo_ativo()
    if not ciclo:
        flash("Nenhum ciclo de avaliação está aberto no momento.", "warning")
        return redirect(url_for("main.minha_area"))


    vinculos = (
        VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id, avaliador_id=funcionario.id)
        .join(Funcionario, VinculoAvaliacao.avaliado_id == Funcionario.id)
        .order_by(Funcionario.nome)
        .all()
    )
    ano = request.args.get("ano", type=int)
    pessoa_id = request.args.get("pessoa", "")
    if pessoa_id and any(str(v.avaliado_id) == pessoa_id for v in vinculos):
        vinculos = [v for v in vinculos if str(v.avaliado_id) == pessoa_id]
    else:
        pessoa_id = ""
    pessoas = []
    anos = set()
    for v in vinculos:
        cursos_todos = _cursos_confirmados(v.avaliado_id)
        anos |= {r.ano for c in cursos_todos for r in c["linhas"]}
        cursos = [c for c in cursos_todos if ano is None or any(r.ano == ano for r in c["linhas"])]
        pessoas.append({
            "avaliado": v.avaliado,
            "cursos": cursos,
            "horas": sum(c["total_h"] or 0 for c in cursos),
        })

    return render_template(
        "capacitacoes_equipe_todos.html",
        pessoas=pessoas, anos=sorted(anos, reverse=True), ano_selecionado=ano, pessoa_id=pessoa_id,
        com_cursos=sum(1 for p in pessoas if p["cursos"]),
    )


@main_bp.route("/minha-equipe/<uuid:avaliado_id>/capacitacoes")
def capacitacoes_da_equipe(avaliado_id):
    """Tela só de leitura pro gestor ver os cursos/capacitações que uma
    pessoa da sua equipe já cadastrou em "Minhas Capacitações"."""
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    avaliado = Funcionario.query.get_or_404(avaliado_id)
    if not _sou_gestor_de(funcionario, avaliado.id):
        abort(403)

    ano = request.args.get("ano", type=int)
    trimestre = request.args.get("trimestre", type=int)
    if not request.args:
        ano, trimestre = trimestre_atual()

    # O gestor só vê o que já foi comprovado; trimestres pendentes não aparecem.
    query = Capacitacao.query.filter_by(funcionario_id=avaliado.id, previsto=False)
    if ano:
        query = query.filter(Capacitacao.ano == ano)
    if trimestre in (1, 2, 3, 4):
        query = query.filter(Capacitacao.trimestre == trimestre)
    else:
        trimestre = None

    lista = query.order_by(
        Capacitacao.ano.desc(),
        Capacitacao.trimestre.desc(),
        Capacitacao.data_conclusao.desc().nullslast(),
    ).all()

    anos = {
        r[0]
        for r in db.session.query(Capacitacao.ano)
        .filter(Capacitacao.funcionario_id == avaliado.id)
        .distinct()
        .all()
    }
    anos.add(trimestre_atual()[0])
    if ano:
        anos.add(ano)
    anos = sorted(anos, reverse=True)

    # Uma linha por curso (não por trimestre): horas/valor do período + dados do curso inteiro.
    cursos = []
    vistos = {}
    for r in lista:
        k = _curso_key(r)
        if k not in vistos:
            c = _montar_curso(_linhas_do_curso(avaliado.id, k) or [r])
            c["horas_periodo"] = 0
            c["valor_periodo"] = 0.0
            vistos[k] = c
            cursos.append(c)
        vistos[k]["horas_periodo"] += r.carga_horaria or 0
        vistos[k]["valor_periodo"] += float(r.valor_pago_senar or 0)

    total_horas = sum(c.carga_horaria or 0 for c in lista if not c.previsto)
    total_valor = sum((c.valor_pago_senar or 0) for c in lista if not c.previsto)
    total_valor_fmt = (
        f"R$ {total_valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )

    if ano and trimestre:
        ini_tri, fim_tri = limites_trimestre(ano, trimestre)
        periodo_txt = (
            f"{trimestre}º trimestre de {ano} · "
            f"{ini_tri.strftime('%d/%m/%Y')} a {fim_tri.strftime('%d/%m/%Y')}"
        )
    elif ano:
        periodo_txt = f"Ano de {ano} · todos os trimestres"
    elif trimestre:
        periodo_txt = f"{trimestre}º trimestre · todos os anos"
    else:
        periodo_txt = "Todos os períodos"

    return render_template(
        "capacitacoes_equipe.html",
        avaliado=avaliado,
        capacitacoes=lista,
        cursos=cursos,
        anos=anos,
        ano_selecionado=ano,
        trimestre_selecionado=trimestre,
        trimestres=[1, 2, 3, 4],
        total_horas=total_horas,
        total_valor_fmt=total_valor_fmt,
        periodo_txt=periodo_txt,
    )


@main_bp.route("/minha-equipe/capacitacoes/<int:capacitacao_id>/documento")
def documento_capacitacao_equipe(capacitacao_id):
    funcionario = funcionario_logado()
    if not funcionario:
        return redirect(url_for("main.login"))

    capacitacao = Capacitacao.query.get_or_404(capacitacao_id)
    if not _sou_gestor_de(funcionario, capacitacao.funcionario_id):
        abort(403)

    return resposta_documento_capacitacao(capacitacao)


def _resultado_liberado_do_ciclo(funcionario, ciclo_id):
    """Confere se o resultado final desse ciclo foi liberado para este
    empregado, e devolve o registro (ou None caso não tenha sido)."""
    return ResultadoFinal.query.filter_by(
        ciclo_id=ciclo_id, avaliado_id=funcionario.id, liberado=True
    ).first()


def _devolutiva_do_registro(registro):
    """Devolutiva marcada pra esse avaliado (ou None se ainda não foi)."""
    avaliado = registro.avaliado if registro else None
    devolutiva = avaliado.devolutiva if avaliado else None
    if devolutiva and devolutiva.data_limite_recorrer:
        return devolutiva
    return None


def _ciclo_com_janela(registro):
    """Ciclo do resultado, se o RH definiu a janela de recursos nele."""
    ciclo = CicloAvaliacao.query.get(registro.ciclo_id) if registro else None
    return ciclo if ciclo and ciclo.janela_recurso() else None


def prazo_ciencia_base(registro):
    """Diz de onde o prazo está sendo contado ('devolutiva' ou 'liberação'),
    pra as telas mostrarem o texto certo. Com a janela de recursos definida
    pelo RH, não há contagem: é o 'período de recursos'."""
    if _ciclo_com_janela(registro):
        return "período de recursos"
    return "devolutiva" if _devolutiva_do_registro(registro) else "liberação"


def prazo_ciencia(registro):
    """Data-limite pro avaliado dar ciência do resultado final (aceitando ou
    recorrendo) e também pra abrir recurso.

    - Se a devolutiva já foi marcada: vale a data-limite dela (5 dias úteis a
      partir da data da devolutiva), até o fim desse dia.
    - Se ainda não foi marcada: 5 dias úteis a partir da liberação do
      resultado.
    Conta os dias úteis pelo calendário de Fortaleza/CE, não pelo UTC."""
    if not registro:
        return None
    ciclo_janela = _ciclo_com_janela(registro)
    if ciclo_janela:
        return ciclo_janela.fim_janela_recurso_dt()
    devolutiva = _devolutiva_do_registro(registro)
    if devolutiva:
        limite = devolutiva.data_limite_recorrer
        return datetime(limite.year, limite.month, limite.day, 23, 59, 59, tzinfo=FUSO_FORTALEZA)
    if not registro.liberado_em:
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
        prazo_base=prazo_ciencia_base(registro),
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

