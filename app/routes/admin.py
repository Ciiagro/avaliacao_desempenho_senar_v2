import io
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import pandas as pd
from sqlalchemy.orm import aliased, joinedload
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app,
    Response,
)

from ..extensions import db
from ..pdf_avaliacao import gerar_pdf_avaliacao
from ..pdf_resultado_final import gerar_pdf_resultado_final, gerar_pdf_resultado_final_lista
from ..excel_resultado_final import gerar_excel_resultado_final, gerar_excel_resultado_final_lista
from ..resultado_final_service import montar_dados_resultado_final
from ..progressao_service import (
    calcular_situacao_par,
    carregar_dados_progressao,
    notas_detalhadas_do_funcionario,
    ponto_partida_efetivo_do_funcionario,
)
from ..utils import (
    formatar_cpf,
    parse_salario,
    media_avaliacao,
    calcular_resultado_final,
    conceito_resultado,
    adicionar_dias_uteis,
    para_fortaleza,
)
from ..models import (
    Funcionario,
    Cargo,
    Setor,
    VinculoAvaliacao,
    CicloAvaliacao,
    Avaliacao,
    ResultadoFinal,
    MembroComissao,
    NIVEIS_HIERARQUICOS,
    OPCOES_SEXO,
    HistoricoPreSistema,
    ProgressaoPontoPartida,
    EventoFuncionario,
    Progressao,
    TIPOS_EVENTO_FUNCIONARIO,
    RecursoAvaliacao,
    RECURSO_STATUS_ENCERRADO,
    DevolutivaPorFuncionario,
    Capacitacao,
    trimestre_atual,
    limites_trimestre,
)

admin_bp = Blueprint("admin", __name__)

SENHA_PADRAO_INICIAL = "123456"  # senha inicial simples; a pessoa troca no primeiro login


def gerar_senha_temporaria():
    return SENHA_PADRAO_INICIAL


# ---------------------------------------------------------
# Acesso restrito (só o gestor de RH tem a senha)
# ---------------------------------------------------------
@admin_bp.before_request
def exigir_login():
    if request.endpoint in ("admin.login",):
        return None
    if not session.get("admin_logueado"):
        return redirect(url_for("admin.login", proximo=request.path))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if senha and senha == current_app.config["ADMIN_PASSWORD"]:
            session["admin_logueado"] = True
            proximo = request.form.get("proximo") or url_for("admin.painel")
            return redirect(proximo)
        flash("Senha incorreta.", "danger")
    proximo = request.args.get("proximo", "")
    return render_template("admin/login.html", proximo=proximo)


@admin_bp.route("/logout")
def logout():
    session.pop("admin_logueado", None)
    flash("Você saiu da área de administração.", "success")
    return redirect(url_for("main.index"))


@admin_bp.route("/avaliacao/<uuid:avaliacao_id>/pdf")
def baixar_pdf_avaliacao(avaliacao_id):
    avaliacao = Avaliacao.query.get_or_404(avaliacao_id)
    if avaliacao.status != "concluida":
        flash("Essa avaliação ainda não foi concluída.", "warning")
        return redirect(url_for("admin.andamento"))

    pdf_buffer = gerar_pdf_avaliacao(avaliacao)
    nome_arquivo = f"avaliacao_{avaliacao.avaliado.nome.replace(' ', '_')}_{avaliacao.tipo}.pdf"
    return Response(
        pdf_buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@admin_bp.route("/avaliacao/<uuid:avaliacao_id>/ver")
def ver_avaliacao(avaliacao_id):
    avaliacao = Avaliacao.query.get_or_404(avaliacao_id)
    respostas_salvas = {r.fator_id: r.pontuacao for r in avaliacao.respostas}
    return render_template(
        "admin/ver_avaliacao.html",
        avaliacao=avaliacao,
        formulario=avaliacao.formulario,
        respostas_salvas=respostas_salvas,
    )


@admin_bp.route("/andamento")
def andamento():
    ciclo_id_param = request.args.get("ciclo_id")
    if ciclo_id_param:
        ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id_param))
    else:
        ciclo = (
            CicloAvaliacao.query.filter_by(status="aberto")
            .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
            .first()
        ) or CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).first()

    ciclos = CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).all()

    if not ciclo:
        return render_template(
            "admin/andamento.html", ciclo=None, ciclos=ciclos, linhas=[], resumo=None
        )

    funcionarios = (
        Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    )

    vinculos_por_avaliado = {
        v.avaliado_id: v.avaliador
        for v in VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id)
        .join(Funcionario, VinculoAvaliacao.avaliador_id == Funcionario.id)
        .all()
    }

    avaliacoes = Avaliacao.query.filter_by(ciclo_id=ciclo.id).all()
    avaliacao_por_chave = {(a.avaliado_id, a.avaliador_id, a.tipo): a for a in avaliacoes}

    linhas = []
    contagem = {
        "auto_concluida": 0, "auto_em_andamento": 0, "auto_nao_iniciada": 0,
        "gestor_concluida": 0, "gestor_em_andamento": 0, "gestor_nao_iniciada": 0,
        "sem_avaliador": 0,
    }
    for f in funcionarios:
        if f.is_elegivel_avaliacao(referencia=ciclo.referencia_elegibilidade()) is False:
            continue

        avaliacao_auto = avaliacao_por_chave.get((f.id, f.id, "auto"))
        status_auto = avaliacao_auto.status if avaliacao_auto else "nao_iniciada"
        contagem[f"auto_{status_auto}"] = contagem.get(f"auto_{status_auto}", 0) + 1

        avaliador = vinculos_por_avaliado.get(f.id)
        avaliacao_gestor = None
        if avaliador:
            avaliacao_gestor = avaliacao_por_chave.get((f.id, avaliador.id, "gestor"))
            status_gestor = avaliacao_gestor.status if avaliacao_gestor else "nao_iniciada"
            contagem[f"gestor_{status_gestor}"] = contagem.get(f"gestor_{status_gestor}", 0) + 1
        else:
            status_gestor = None
            contagem["sem_avaliador"] += 1

        linhas.append(
            {
                "funcionario": f,
                "status_auto": status_auto,
                "avaliacao_auto": avaliacao_auto,
                "avaliador": avaliador,
                "status_gestor": status_gestor,
                "avaliacao_gestor": avaliacao_gestor,
            }
        )

    total = len(linhas)
    resumo = {
        "total": total,
        "auto_concluida": contagem.get("auto_concluida", 0),
        "gestor_concluida": contagem.get("gestor_concluida", 0),
        "sem_avaliador": contagem.get("sem_avaliador", 0),
        "pct_auto": round(100 * contagem.get("auto_concluida", 0) / total) if total else 0,
        "pct_gestor": round(100 * contagem.get("gestor_concluida", 0) / total) if total else 0,
    }

    return render_template(
        "admin/andamento.html",
        ciclo=ciclo,
        ciclos=ciclos,
        linhas=linhas,
        resumo=resumo,
    )


@admin_bp.route("/painel-monitoramento")
def painel_monitoramento():
    """Painel pra acompanhar o andamento do exercício de longe: situação
    geral (com semáforo), ritmo x prazo, pontos de atenção gerados a partir
    dos dados, progresso por setor, por gestor e a lista de quem falta — sem
    a tabela grande de ações que tem em 'Andamento das avaliações'."""
    import math

    ciclo_id_param = request.args.get("ciclo_id")
    if ciclo_id_param:
        ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id_param))
    else:
        ciclo = (
            CicloAvaliacao.query.filter_by(status="aberto")
            .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
            .first()
        ) or CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).first()

    ciclos = CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).all()

    if not ciclo:
        return render_template(
            "admin/painel_monitoramento.html", ciclo=None, ciclos=ciclos, resumo=None
        )

    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    funcionario_por_id = {f.id: f for f in funcionarios}

    vinculos_por_avaliado = {
        v.avaliado_id: v.avaliador
        for v in VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id)
        .join(Funcionario, VinculoAvaliacao.avaliador_id == Funcionario.id)
        .all()
    }

    avaliacoes = Avaliacao.query.filter_by(ciclo_id=ciclo.id).all()
    avaliacao_por_chave = {(a.avaliado_id, a.avaliador_id, a.tipo): a for a in avaliacoes}

    agora = para_fortaleza(datetime.now(timezone.utc))
    hoje = agora.date()

    # Datas de conclusão (pra medir o ritmo da última semana)
    conclusoes = []  # (tipo, data)
    for a in avaliacoes:
        if a.status == "concluida":
            momento = para_fortaleza(a.assinado_em or a.atualizado_em)
            if momento:
                conclusoes.append((a.tipo, momento.date()))

    # ------------------------------------------------------------------
    # Varredura principal
    # ------------------------------------------------------------------
    pendentes_auto, pendentes_gestor, sem_avaliador = [], [], []
    auto_concluida = gestor_concluida = total = 0
    setores = {}  # nome -> contagens
    equipes = {}  # avaliador_id -> [{nome, ok}]

    for f in funcionarios:
        if f.is_elegivel_avaliacao(referencia=ciclo.referencia_elegibilidade()) is False:
            continue
        total += 1
        setor_nome = f.setor.nome if f.setor else "Sem setor"
        st = setores.setdefault(setor_nome, {"nome": setor_nome, "total": 0, "auto": 0, "gestor": 0})
        st["total"] += 1

        avaliador = vinculos_por_avaliado.get(f.id)
        linha = {
            "nome": f.nome,
            "setor": setor_nome,
            "gestor": avaliador.nome if avaliador else None,
            "gestor_id": str(avaliador.id) if avaliador else None,
        }

        av_auto = avaliacao_por_chave.get((f.id, f.id, "auto"))
        if av_auto and av_auto.status == "concluida":
            auto_concluida += 1
            st["auto"] += 1
        else:
            pendentes_auto.append(linha)

        if not avaliador:
            sem_avaliador.append(linha)
        else:
            av_gestor = avaliacao_por_chave.get((f.id, avaliador.id, "gestor"))
            gestor_ok = bool(av_gestor and av_gestor.status == "concluida")
            equipes.setdefault(avaliador.id, []).append({"nome": f.nome, "ok": gestor_ok})
            if gestor_ok:
                gestor_concluida += 1
                st["gestor"] += 1
            else:
                pendentes_gestor.append(linha)

    pct = lambda parte, todo: round(100 * parte / todo) if todo else 0

    # Pendências da avaliação do gestor agrupadas por gestor (quem precisa
    # agir), do que tem mais gente pendente pro que tem menos.
    _grupos = {}
    for linha in pendentes_gestor:
        _grupos.setdefault(linha["gestor_id"], {"gestor": linha["gestor"], "pessoas": []})["pessoas"].append(linha)
    pendentes_gestor_grupos = sorted(
        _grupos.values(), key=lambda g: (-len(g["pessoas"]), g["gestor"])
    )

    # ------------------------------------------------------------------
    # Gestores (equipe avaliada x total)
    # ------------------------------------------------------------------
    gestores = []
    for avaliador_id, pessoas in equipes.items():
        g = funcionario_por_id.get(avaliador_id) or Funcionario.query.get(avaliador_id)
        ok = sum(1 for p in pessoas if p["ok"])
        gestores.append(
            {
                "nome": g.nome if g else "-",
                "setor": g.setor.nome if g and g.setor else "",
                "concluidas": ok,
                "total": len(pessoas),
                "pendentes": len(pessoas) - ok,
                "pct": pct(ok, len(pessoas)),
                "pessoas": sorted(pessoas, key=lambda p: (p["ok"], p["nome"])),
            }
        )
    gestores.sort(key=lambda g: (g["pct"] == 100, -g["pendentes"], g["nome"]))
    gestores_completos = sum(1 for g in gestores if g["pct"] == 100)

    # ------------------------------------------------------------------
    # Setores
    # ------------------------------------------------------------------
    lista_setores = []
    for s in setores.values():
        s["pct_auto"] = pct(s["auto"], s["total"])
        s["pct_gestor"] = pct(s["gestor"], s["total"])
        s["media"] = (s["pct_auto"] + s["pct_gestor"]) / 2
        lista_setores.append(s)
    lista_setores.sort(key=lambda s: (s["media"], s["nome"]))

    # ------------------------------------------------------------------
    # Prazos, ritmo e semáforo
    # ------------------------------------------------------------------
    def _ritmo(tipo, pendentes_n, prazo, rotulo):
        if not pendentes_n:
            return {"rotulo": rotulo, "nivel": "ok", "situacao": "Concluída", "pendentes": 0}
        recentes = sum(1 for t, d in conclusoes if t == tipo and 0 <= (hoje - d).days < 7)
        info = {"rotulo": rotulo, "pendentes": pendentes_n, "recentes": recentes, "prazo": prazo}
        dias = (prazo - hoje).days if prazo else None
        info["dias"] = dias
        info["necessario"] = (
            math.ceil(pendentes_n / (dias / 7)) if dias and dias > 0 else None
        )
        info["projecao"] = (
            hoje + timedelta(days=math.ceil(pendentes_n / (recentes / 7))) if recentes else None
        )
        if prazo is None:
            info["nivel"], info["situacao"] = "info", "Sem prazo definido"
        elif dias < 0:
            info["nivel"], info["situacao"] = "critico", "Atrasada"
        elif info["projecao"] and info["projecao"] <= prazo:
            info["nivel"], info["situacao"] = "ok", "No ritmo"
        elif dias <= 7:
            info["nivel"], info["situacao"] = "critico", "Prazo curto"
        else:
            info["nivel"], info["situacao"] = "atencao", "Precisa acelerar"
        return info

    pend_auto_n, pend_gestor_n = len(pendentes_auto), len(pendentes_gestor)
    ritmo_auto = _ritmo("auto", pend_auto_n, ciclo.data_limite_autoavaliacao, "Autoavaliação")
    ritmo_gestor = _ritmo("gestor", pend_gestor_n, ciclo.data_limite_gestor, "Avaliação do gestor")

    ordem = {"ok": 0, "info": 0, "atencao": 1, "critico": 2}
    pior = max((ritmo_auto["nivel"], ritmo_gestor["nivel"]), key=lambda n: ordem[n])
    if not (pend_auto_n or pend_gestor_n):
        saude = {"nivel": "ok", "rotulo": "Exercício concluído"}
    else:
        saude = {
            "nivel": "ok" if pior == "info" else pior,
            "rotulo": {"ok": "No ritmo", "info": "Em andamento", "atencao": "Atenção", "critico": "Crítico"}[pior],
        }

    def _prazo_info(prazo):
        if not prazo:
            return None
        dias = (prazo - hoje).days
        return {"data": prazo, "dias": dias, "atrasado": dias < 0}

    def _plural(n, sing, plur):
        return f"{n} {sing if n == 1 else plur}"

    partes = []
    if pend_auto_n:
        partes.append(_plural(pend_auto_n, "autoavaliação", "autoavaliações"))
    if pend_gestor_n:
        partes.append(_plural(pend_gestor_n, "avaliação de gestor", "avaliações de gestor"))
    if partes:
        manchete = ("Falta " if pend_auto_n + pend_gestor_n == 1 else "Faltam ") + " e ".join(partes)
    else:
        manchete = "Tudo concluído neste exercício"

    # Próximo prazo que ainda importa (etapa com pendência)
    candidatos = [
        (r["prazo"], r["rotulo"].lower())
        for r in (ritmo_auto, ritmo_gestor)
        if r.get("pendentes") and r.get("prazo")
    ]
    subtitulo = ""
    if candidatos:
        data_p, nome_p = min(candidatos, key=lambda c: c[0])
        d = (data_p - hoje).days
        quando = (
            f"venceu há {_plural(-d, 'dia', 'dias')}" if d < 0
            else "vence hoje" if d == 0
            else "vence amanhã" if d == 1
            else f"vence em {d} dias"
        )
        subtitulo = f"Prazo da {nome_p} {quando} ({data_p.strftime('%d/%m/%Y')})."

    # Linha do tempo da JANELA DE RESPOSTA (não do ano avaliado): o exercício
    # 2025, por exemplo, tem período 01/01–31/12/2025 mas é respondido em
    # 2026. Mostrar as duas coisas juntas confundia, então aqui só entram
    # o começo das respostas, os prazos e o dia de hoje.
    marcos = []
    criadas = [
        para_fortaleza(a.criado_em).date() for a in avaliacoes if a.criado_em
    ]
    if criadas:
        marcos.append({"rotulo": "Início das respostas", "data": min(criadas), "tipo": "marco"})
    if ciclo.data_limite_autoavaliacao:
        marcos.append({"rotulo": "Prazo autoavaliação", "data": ciclo.data_limite_autoavaliacao, "tipo": "prazo"})
    if ciclo.data_limite_gestor:
        marcos.append({"rotulo": "Prazo gestor", "data": ciclo.data_limite_gestor, "tipo": "prazo"})
    linha_tempo = None
    if any(m["tipo"] == "prazo" for m in marcos):
        marcos.sort(key=lambda m: m["data"])
        datas = [m["data"] for m in marcos] + [hoje]
        ini, fim = min(datas), max(datas)
        span = max((fim - ini).days, 1)
        pos = lambda d: round(6 + 88 * (d - ini).days / span, 1)
        anterior, nivel = None, 0
        for m in marcos:
            m["pos"] = pos(m["data"])
            # marcos muito juntos: o rótulo desce pra outra linha
            nivel = 1 - nivel if anterior is not None and m["pos"] - anterior < 20 else 0
            m["nivel"] = nivel
            anterior = m["pos"]
        linha_tempo = {"marcos": marcos, "hoje_pos": pos(hoje), "inicio_pos": 6}

    # ------------------------------------------------------------------
    # Pontos de atenção (gerados a partir dos números)
    # ------------------------------------------------------------------
    insights = []

    for r in (ritmo_auto, ritmo_gestor):
        if not r.get("pendentes") or r["nivel"] in ("ok", "info"):
            continue
        if r["nivel"] == "critico" and r["dias"] is not None and r["dias"] < 0:
            texto = (
                f"Prazo venceu há {_plural(-r['dias'], 'dia', 'dias')} e ainda faltam "
                f"{r['pendentes']}."
            )
        else:
            texto = (
                f"Faltam {r['pendentes']}; na última semana foram concluídas {r['recentes']}. "
                f"Pra fechar até {r['prazo'].strftime('%d/%m')}, precisa de cerca de "
                f"{r['necessario']} por semana."
            )
        insights.append({"nivel": r["nivel"], "titulo": f"{r['rotulo']} fora do ritmo", "texto": texto})

    zerados = [g for g in gestores if g["concluidas"] == 0]
    if zerados and pend_gestor_n:
        carga = sum(g["pendentes"] for g in zerados)
        insights.append(
            {
                "nivel": "atencao",
                "titulo": f"{_plural(len(zerados), 'gestor ainda não começou', 'gestores ainda não começaram')}",
                "texto": f"Eles seguram {carga} das {pend_gestor_n} avaliações pendentes ({pct(carga, pend_gestor_n)}%).",
            }
        )

    if gestores and gestores[0]["pendentes"] >= 3 and pend_gestor_n:
        g = gestores[0]
        insights.append(
            {
                "nivel": "info",
                "titulo": "Maior fila de avaliações",
                "texto": f"{g['nome'].title()} tem {g['pendentes']} pendentes ({pct(g['pendentes'], pend_gestor_n)}% do total do gestor).",
            }
        )

    abertos = [s for s in lista_setores if s["media"] < 100 and s["total"] >= 2]
    if abertos and (pend_auto_n or pend_gestor_n):
        s = abertos[0]
        insights.append(
            {
                "nivel": "atencao" if s["media"] < 30 else "info",
                "titulo": "Setor mais atrasado",
                "texto": f"{s['nome']}: {s['pct_auto']}% das autoavaliações e {s['pct_gestor']}% das avaliações do gestor.",
            }
        )

    if sem_avaliador:
        insights.append(
            {
                "nivel": "critico",
                "titulo": f"{_plural(len(sem_avaliador), 'pessoa sem gestor vinculado', 'pessoas sem gestor vinculado')}",
                "texto": "Sem vínculo a avaliação do gestor não acontece. Ajustar em Vínculos.",
            }
        )

    completos = [s for s in lista_setores if s["media"] == 100]
    if completos:
        insights.append(
            {
                "nivel": "ok",
                "titulo": f"{_plural(len(completos), 'setor concluído', 'setores concluídos')}",
                "texto": ", ".join(s["nome"] for s in completos[:4]) + ("…" if len(completos) > 4 else "."),
            }
        )

    insights.sort(key=lambda i: {"critico": 0, "atencao": 1, "info": 2, "ok": 3}[i["nivel"]])
    insights = insights[:6]

    resumo = {
        "total": total,
        "auto_concluida": auto_concluida,
        "gestor_concluida": gestor_concluida,
        "pct_auto": pct(auto_concluida, total),
        "pct_gestor": pct(gestor_concluida, total),
        "pct_geral": pct(auto_concluida + gestor_concluida, 2 * total),
        "pendentes_auto": pendentes_auto,
        "pendentes_gestor": pendentes_gestor,
        "pendentes_gestor_grupos": pendentes_gestor_grupos,
        "sem_avaliador": sem_avaliador,
        "prazo_auto": _prazo_info(ciclo.data_limite_autoavaliacao),
        "prazo_gestor": _prazo_info(ciclo.data_limite_gestor),
        "gestores_completos": gestores_completos,
        "gestores_com_equipe": len(gestores),
        "pct_gestores": pct(gestores_completos, len(gestores)),
        "gestores": gestores,
        "setores": lista_setores,
        "saude": saude,
        "manchete": manchete,
        "subtitulo": subtitulo,
        "ritmos": [ritmo_auto, ritmo_gestor],
        "linha_tempo": linha_tempo,
        "insights": insights,
        "atualizado_em": agora.strftime("%H:%M"),
    }

    return render_template(
        "admin/painel_monitoramento.html",
        ciclo=ciclo,
        ciclos=ciclos,
        resumo=resumo,
    )


@admin_bp.route("/resultados")
def resultados():
    """
    Resultado final por empregado (auto x0,30 + gestor x0,70), visível só
    para a administração. A comissão ainda não entra aqui — fica reservada
    para quando o empregado recorrer da nota.
    """
    ciclo_id_param = request.args.get("ciclo_id")
    if ciclo_id_param:
        ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id_param))
    else:
        ciclo = (
            CicloAvaliacao.query.filter_by(status="aberto")
            .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
            .first()
        ) or CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).first()

    ciclos = CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).all()

    if not ciclo:
        return render_template("admin/resultados.html", ciclo=None, ciclos=ciclos, linhas=[])

    linhas = montar_linhas_resultado_final(ciclo)

    return render_template(
        "admin/resultados.html",
        ciclo=ciclo,
        ciclos=ciclos,
        linhas=linhas,
        agora=datetime.now(timezone.utc),
    )

# Prazo pro avaliado dar ciência (aceitar ou recorrer) depois que o
# resultado final é liberado — mesmo valor usado em main.py.
PRAZO_CIENCIA_DIAS_UTEIS = 5


def montar_linhas_resultado_final(ciclo):
    """Monta a lista de linhas (uma por funcionário elegível) usada tanto na
    tela `admin/resultados.html` quanto na exportação em Excel/PDF de todos
    os resultados do ciclo."""
    funcionarios = (
        Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    )

    vinculos_por_avaliado = {
        v.avaliado_id: v.avaliador
        for v in VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id)
        .join(Funcionario, VinculoAvaliacao.avaliador_id == Funcionario.id)
        .all()
    }

    # joinedload evita N+1: sem isso, cada chamada de media_avaliacao() no
    # loop abaixo (uma por funcionário, x2: auto e gestor) disparava uma
    # query nova pra buscar avaliacao.respostas — em produção isso já
    # passou de 1.000 consultas extras nessa única tela (usada tanto na
    # tela de resultados quanto nas exportações Excel/PDF).
    avaliacoes = (
        Avaliacao.query.options(joinedload(Avaliacao.respostas))
        .filter_by(ciclo_id=ciclo.id)
        .all()
    )
    avaliacao_por_chave = {(a.avaliado_id, a.avaliador_id, a.tipo): a for a in avaliacoes}

    liberados_por_avaliado = {
        r.avaliado_id: r
        for r in ResultadoFinal.query.filter_by(ciclo_id=ciclo.id).all()
    }

    # Pra quem recorreu, a "ciência" inicial não é o fim da história — a
    # assinatura que realmente conta é a de quando o recurso encerra (ver
    # app/routes/recursos.py: aceitar_recurso). Busca de uma vez só os
    # recursos do ciclo pra não fazer uma query por funcionário.
    recursos_por_avaliado = {
        r.avaliado_id: r for r in RecursoAvaliacao.query.filter_by(ciclo_id=ciclo.id).all()
    }

    linhas = []
    for f in funcionarios:
        if f.is_elegivel_avaliacao(referencia=ciclo.referencia_elegibilidade()) is False:
            continue

        avaliacao_auto = avaliacao_por_chave.get((f.id, f.id, "auto"))
        avaliador = vinculos_por_avaliado.get(f.id)
        avaliacao_gestor = (
            avaliacao_por_chave.get((f.id, avaliador.id, "gestor")) if avaliador else None
        )

        media_auto = media_avaliacao(avaliacao_auto)
        media_gestor = media_avaliacao(avaliacao_gestor)
        resultado_final = calcular_resultado_final(media_auto, media_gestor)
        conceito = conceito_resultado(resultado_final)

        resultado_registro = liberados_por_avaliado.get(f.id)

        # Status real da assinatura: "pendente" (nem deu ciência ainda),
        # "confirmada" (aceitou de primeira, já é definitivo), "recurso_pendente"
        # (recorreu, mas o recurso ainda não foi assinado no fim) ou
        # "assinada_recurso" (recorreu e já assinou a resposta final do recurso).
        recurso = recursos_por_avaliado.get(f.id)
        if not (resultado_registro and resultado_registro.ciente_avaliado):
            assinatura_status = "pendente"
            assinatura_em = None
        elif resultado_registro.decisao_avaliado == "recorreu":
            if recurso and recurso.status == RECURSO_STATUS_ENCERRADO and recurso.ciente_funcionario:
                assinatura_status = "assinada_recurso"
                assinatura_em = recurso.ciente_funcionario_em
            else:
                assinatura_status = "recurso_pendente"
                assinatura_em = None
        else:
            assinatura_status = "confirmada"
            assinatura_em = resultado_registro.ciente_em

        linhas.append(
            {
                "funcionario": f,
                "media_auto": media_auto,
                "media_gestor": media_gestor,
                "resultado_final": resultado_final,
                "conceito": conceito,
                "pronto": resultado_final is not None,
                "liberado": bool(resultado_registro and resultado_registro.liberado),
                "ciente": bool(resultado_registro and resultado_registro.ciente_avaliado),
                "ciente_em": resultado_registro.ciente_em if resultado_registro else None,
                "assinatura_status": assinatura_status,
                "assinatura_em": assinatura_em,
                "prazo_ciencia": (
                    adicionar_dias_uteis(
                        para_fortaleza(resultado_registro.liberado_em), PRAZO_CIENCIA_DIAS_UTEIS
                    )
                    if resultado_registro and resultado_registro.liberado_em
                    else None
                ),
            }
        )

    return linhas


@admin_bp.route("/resultados/<uuid:avaliado_id>/detalhe")
def detalhe_resultado(avaliado_id):
    """Mostra lado a lado a autoavaliação e a avaliação do gestor de um
    empregado, com o resultado final calculado — pra administração conferir
    tudo numa tela só antes de liberar."""
    ciclo_id = request.args.get("ciclo_id")
    ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id))
    avaliado = Funcionario.query.get_or_404(avaliado_id)

    dados = montar_dados_resultado_final(ciclo, avaliado)

    resultado_registro = ResultadoFinal.query.filter_by(
        ciclo_id=ciclo.id, avaliado_id=avaliado.id
    ).first()
    liberado = bool(resultado_registro and resultado_registro.liberado)

    return render_template(
        "admin/resultado_detalhe.html",
        ciclo=ciclo,
        avaliado=avaliado,
        dados=dados,
        liberado=liberado,
    )


@admin_bp.route("/resultados/exportar")
def exportar_resultados_excel():
    """Baixa a planilha consolidada de todos os funcionários do ciclo, no
    mesmo formato usado pela empresa (MAT, NOME, ADMISSÃO, NOTA, CONCEITO)."""
    ciclo_id_param = request.args.get("ciclo_id")
    if ciclo_id_param:
        ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id_param))
    else:
        ciclo = (
            CicloAvaliacao.query.filter_by(status="aberto")
            .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
            .first()
        ) or CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).first()

    if not ciclo:
        flash("Nenhum ciclo cadastrado ainda.", "warning")
        return redirect(url_for("admin.resultados"))

    somente_concluidos = request.args.get("somente_concluidos", "1") != "0"

    linhas = montar_linhas_resultado_final(ciclo)
    excel_buffer = gerar_excel_resultado_final_lista(ciclo, linhas, somente_concluidos)
    nome_arquivo = f"resultado_final_{ciclo.exercicio}.xlsx"
    return Response(
        excel_buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


@admin_bp.route("/resultados/exportar/pdf")
def exportar_resultados_pdf():
    """Baixa o PDF consolidado de todos os funcionários do ciclo, com a
    lista MAT/NOME/ADMISSÃO/NOTA/CONCEITO e a tabela de referência x real
    dos conceitos."""
    ciclo_id_param = request.args.get("ciclo_id")
    if ciclo_id_param:
        ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id_param))
    else:
        ciclo = (
            CicloAvaliacao.query.filter_by(status="aberto")
            .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
            .first()
        ) or CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).first()

    if not ciclo:
        flash("Nenhum ciclo cadastrado ainda.", "warning")
        return redirect(url_for("admin.resultados"))

    somente_concluidos = request.args.get("somente_concluidos", "1") != "0"

    linhas = montar_linhas_resultado_final(ciclo)
    pdf_buffer = gerar_pdf_resultado_final_lista(ciclo, linhas, somente_concluidos)
    nome_arquivo = f"resultado_final_{ciclo.exercicio}.pdf"
    return Response(
        pdf_buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@admin_bp.route("/resultados/<uuid:avaliado_id>/pdf")
def baixar_resultado_pdf(avaliado_id):
    ciclo_id = request.args.get("ciclo_id")
    ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id))
    avaliado = Funcionario.query.get_or_404(avaliado_id)

    dados = montar_dados_resultado_final(ciclo, avaliado)
    if dados["resultado_final"] is None:
        flash("O resultado final dessa pessoa ainda não pode ser calculado (falta autoavaliação e/ou avaliação do gestor).", "warning")
        return redirect(url_for("admin.resultados", ciclo_id=ciclo.id))

    pdf_buffer = gerar_pdf_resultado_final(dados)
    nome_arquivo = f"resultado_final_{avaliado.nome.replace(' ', '_')}_{ciclo.exercicio}.pdf"
    return Response(
        pdf_buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@admin_bp.route("/resultados/<uuid:avaliado_id>/excel")
def baixar_resultado_excel(avaliado_id):
    ciclo_id = request.args.get("ciclo_id")
    ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id))
    avaliado = Funcionario.query.get_or_404(avaliado_id)

    dados = montar_dados_resultado_final(ciclo, avaliado)
    if dados["resultado_final"] is None:
        flash("O resultado final dessa pessoa ainda não pode ser calculado (falta autoavaliação e/ou avaliação do gestor).", "warning")
        return redirect(url_for("admin.resultados", ciclo_id=ciclo.id))

    excel_buffer = gerar_excel_resultado_final(dados)
    nome_arquivo = f"resultado_final_{avaliado.nome.replace(' ', '_')}_{ciclo.exercicio}.xlsx"
    return Response(
        excel_buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


@admin_bp.route("/resultados/<uuid:avaliado_id>/liberar", methods=["POST"])
def liberar_resultado(avaliado_id):
    ciclo_id = request.form.get("ciclo_id")
    ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id))

    registro = ResultadoFinal.query.filter_by(ciclo_id=ciclo.id, avaliado_id=avaliado_id).first()
    if not registro:
        registro = ResultadoFinal(ciclo_id=ciclo.id, avaliado_id=avaliado_id, liberado=False)
        db.session.add(registro)

    registro.liberado = True
    registro.liberado_em = datetime.utcnow()
    registro.liberado_por = "Administração"
    db.session.commit()
    flash("Resultado final liberado para o empregado.", "success")
    return redirect(url_for("admin.resultados", ciclo_id=ciclo.id))


@admin_bp.route("/resultados/<uuid:avaliado_id>/bloquear", methods=["POST"])
def bloquear_resultado(avaliado_id):
    ciclo_id = request.form.get("ciclo_id")
    ciclo = CicloAvaliacao.query.get_or_404(int(ciclo_id))

    registro = ResultadoFinal.query.filter_by(ciclo_id=ciclo.id, avaliado_id=avaliado_id).first()
    if registro:
        registro.liberado = False
        registro.liberado_em = None
        # Se o resultado for corrigido e liberado de novo, o avaliado precisa
        # confirmar a ciência novamente.
        registro.ciente_avaliado = False
        registro.ciente_em = None
        registro.decisao_avaliado = None
        db.session.commit()
        flash("Liberação do resultado final removida.", "success")
    return redirect(url_for("admin.resultados", ciclo_id=ciclo.id))


# ---------------------------------------------------------
# Progressão de nível
# ---------------------------------------------------------


def par_para_exibir(situacao):
    """String pra mostrar na coluna 'Par atual em avaliação'. Quando já
    existe um par formado (pelo menos o primeiro ano é A), mostra esse
    par. Quando ainda não formou nenhum mas já existem 2+ anos conhecidos,
    mostra os dois mais recentes só como referência (sem valer como par).
    Com 0 ou 1 ano conhecido não tem intervalo nenhum pra mostrar — fica
    "—", e a coluna de Status já explica o resto."""
    if situacao.get("par_inicio") and situacao.get("par_fim"):
        return f"{situacao['par_inicio']}\u2013{situacao['par_fim']}"
    conceitos = situacao.get("conceitos") or {}
    anos = sorted(conceitos)
    if len(anos) >= 2:
        return f"{anos[-2]}\u2013{anos[-1]} (sem A ainda)"
    return "\u2014"


def montar_resumo_progressao(situacao, no_topo, atrasada):
    """Resume a situação toda numa resposta única e direta: pode subir de
    nível agora ou não — com um motivo curto. Substitui a sopa de badges
    técnicos (aguardando/sem_dado/elegível/atrasada...) por uma frase só,
    pensada pra quem só quer saber "sobe ou não sobe".
    """
    if no_topo:
        return {
            "pode_subir": False,
            "titulo": "Já está no nível máximo",
            "motivo": "não há próximo nível hierárquico para progredir.",
        }

    status = situacao["status"]

    if status == "elegivel":
        motivo = f"conceito A em {situacao['par_inicio']} e {situacao['par_fim']}."
        if atrasada:
            motivo += f" Pendente de decisão desde {situacao['exercicio_efetivacao']}."
        return {"pode_subir": True, "titulo": "Pode subir de nível agora", "motivo": motivo}

    if status == "aguardando":
        return {
            "pode_subir": False,
            "titulo": "Ainda não pode subir",
            "motivo": f"já tem A em {situacao['par_inicio']}; falta o resultado de {situacao['par_fim']}.",
        }

    if status == "sem_dado":
        ano = situacao.get("ano_em_falta")
        motivo = f"falta o resultado de {ano}." if ano else "faltam mais anos avaliados."
        return {"pode_subir": False, "titulo": "Ainda não pode subir", "motivo": motivo}

    if status == "sem_ponto_partida":
        return {
            "pode_subir": False,
            "titulo": "Ainda não pode subir",
            "motivo": "situação ambígua — o RH precisa confirmar o ponto de partida do par.",
        }

    if status == "sem_historico":
        return {
            "pode_subir": False,
            "titulo": "Ainda não pode subir",
            "motivo": "ainda não tirou conceito A em nenhum ano avaliado.",
        }

    return {"pode_subir": False, "titulo": "Ainda não pode subir", "motivo": "não elegível no momento."}


def esta_no_nivel_maximo(funcionario):
    """Decisão do cliente: 'Superintendente' NÃO trava progressão, mesmo
    sendo o último nível_hierárquico cadastrado (usado só pra escolher o
    formulário de avaliação). Existe cargo acima na empresa (Presidente),
    mas ele não entra nessa lista de propósito — não é uma etapa que o
    sistema formaliza. Por isso essa checagem sempre devolve False agora;
    a função continua existindo só pra não precisar mudar quem já chama."""
    return False


def proximo_nivel(nivel_atual):
    if nivel_atual in NIVEIS_HIERARQUICOS and nivel_atual != NIVEIS_HIERARQUICOS[-1]:
        return NIVEIS_HIERARQUICOS[NIVEIS_HIERARQUICOS.index(nivel_atual) + 1]
    return nivel_atual


def _linhas_progressao_nivel():
    """Monta as linhas de Progressão de Nível (mesmo cálculo usado na tela
    e na exportação pra Excel, pra nunca ficarem divergentes)."""
    ano_atual = datetime.now().year
    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    dados = carregar_dados_progressao()
    linhas = []
    for funcionario in funcionarios:
        notas = notas_detalhadas_do_funcionario(funcionario.id, dados)
        nota_por_ano = {n["exercicio"]: n["nota"] for n in notas}
        no_topo = esta_no_nivel_maximo(funcionario)
        ponteiro = dados["ponteiros_por_funcionario"].get(funcionario.id)
        excluido = bool(ponteiro and ponteiro.excluido_progressao)

        # O par de cada pessoa parte do ponto de partida EFETIVO — que já
        # empurra sozinho pra frente quando existe uma progressão (decisão)
        # registrada antes: nunca fica preso no par antigo depois de decidido.
        par_inicio, precisa_confirmacao_calc = ponto_partida_efetivo_do_funcionario(funcionario.id, dados)
        precisa_confirmacao = bool(precisa_confirmacao_calc)
        par_fim = par_inicio + 1 if par_inicio else None
        ano_decisao = par_fim + 1 if par_fim else None

        progressao_existente = None
        if par_inicio and par_fim:
            progressao_existente = Progressao.query.filter_by(
                funcionario_id=funcionario.id, exercicio_inicio=par_inicio, exercicio_fim=par_fim
            ).first()

        # O segundo ano do par ainda não tem nota lançada e ninguém decidiu
        # nada ainda — não faz sentido oferecer decisão antes disso existir.
        par_ainda_nao_fechou = bool(par_fim) and nota_por_ano.get(par_fim) is None and not progressao_existente

        # Só existe decisão de verdade pra tomar quando os DOIS anos do par
        # são conceito A. Se o segundo ano já veio e não foi A, o par não
        # fechou — não tem o que decidir, é só "não sobe" objetivamente.
        nota_inicio = nota_por_ano.get(par_inicio) if par_inicio else None
        nota_fim = nota_por_ano.get(par_fim) if par_fim else None
        par_nao_fechou_com_a = (
            bool(par_fim)
            and nota_fim is not None
            and not (nota_inicio is not None and nota_inicio >= 8 and nota_fim >= 8)
            and not progressao_existente
        )

        if progressao_existente:
            if progressao_existente.subiu is not None:
                decisao_atual = "sim" if progressao_existente.subiu else "nao"
            elif progressao_existente.nivel_anterior != progressao_existente.nivel_novo:
                decisao_atual = "sim"
            else:
                decisao_atual = "nao"
        elif par_fim and not par_ainda_nao_fechou and not par_nao_fechou_com_a:
            # Par fechou com A nos dois anos e ainda não tem decisão salva —
            # já vem pré-marcado como "Progressão em {ano}" (em vez de
            # neutro em "A decidir"), pra reduzir clique manual. Mas só vira
            # realidade se alguém clicar em "Salvar decisões" — nada muda
            # sozinho antes disso.
            decisao_atual = "sim"
        else:
            decisao_atual = "a_decidir"

        # Se a pessoa já está no topo POR TER SUBIDO de verdade (não só por
        # já ter nascido lá), mostra "Progressão em {ano}" em vez do aviso
        # genérico de "nível máximo" — é uma informação bem mais útil.
        progressao_ate_topo = None
        if no_topo:
            ultima = dados["ultima_progressao_por_funcionario"].get(funcionario.id)
            if ultima and ultima.nivel_anterior != ultima.nivel_novo:
                progressao_ate_topo = ultima.efetivada_em_exercicio

        # Unifica os três casos "travados" (progrediu até o topo, já está no
        # topo, ou já excluído) num rótulo só — a tela sempre mostra o mesmo
        # tipo de controle (select trancado + lápis pra editar), nunca um
        # selo diferente pra cada caso.
        if excluido:
            rotulo_bloqueado = ponteiro.observacao if ponteiro and ponteiro.observacao else "Não se aplica"
        elif progressao_ate_topo:
            rotulo_bloqueado = f"Progressão em {progressao_ate_topo}"
        elif no_topo:
            rotulo_bloqueado = "Já está no nível máximo"
        else:
            rotulo_bloqueado = None

        # Chance real de subir NESTE ano — o par dela fecha (2º ano) neste
        # ciclo, ainda não tem decisão registrada, e não está travada por
        # nenhum motivo (topo, excluída etc). É diferente de "Sem
        # progressão" genérico, que também cobre pares bem mais distantes.
        decide_esse_ano = (
            not rotulo_bloqueado
            and not progressao_existente
            and not par_nao_fechou_com_a
            and ano_decisao == ano_atual
        )

        linhas.append(
            {
                "funcionario": funcionario,
                "nota_2023": nota_por_ano.get(2023),
                "nota_2024": nota_por_ano.get(2024),
                "nota_2025": nota_por_ano.get(2025),
                "no_topo": no_topo,
                "progressao_ate_topo": progressao_ate_topo,
                "excluido": excluido,
                "rotulo_bloqueado": rotulo_bloqueado,
                "motivo_exclusao": (ponteiro.observacao if ponteiro and ponteiro.observacao else "Não se aplica"),
                "precisa_confirmacao": precisa_confirmacao,
                "par_inicio": par_inicio,
                "par_fim": par_fim,
                "ano_decisao": ano_decisao,
                "ja_passou": bool(ano_decisao) and ano_decisao < ano_atual,
                "decisao_atual": decisao_atual,
                "par_ainda_nao_fechou": par_ainda_nao_fechou,
                "par_nao_fechou_com_a": par_nao_fechou_com_a,
                "decide_esse_ano": decide_esse_ano,
            }
        )
    return linhas


@admin_bp.route("/progressao-nivel")
def progressao_nivel():
    linhas = _linhas_progressao_nivel()
    return render_template("admin/progressao_nivel.html", linhas=linhas)


@admin_bp.route("/progressao-nivel/exportar")
def exportar_progressao_nivel():
    """Exporta a tabela de Progressão de Nível pra Excel: notas de 2023,
    2024, 2025, o par de anos que vale pra cada pessoa, e a decisão/situação
    atual — pra dar pra ver e conferir fora do sistema."""
    linhas = _linhas_progressao_nivel()

    rotulo_decisao = {
        "sim": "Sim, sobe",
        "nao": "Não sobe",
        "a_decidir": "A decidir",
    }

    def par_texto(l):
        if l["par_inicio"] and l["par_fim"]:
            return f"{l['par_inicio']}-{l['par_fim']}"
        return "-"

    def decisao_texto(l):
        if l["rotulo_bloqueado"]:
            return l["rotulo_bloqueado"]
        if l["par_ainda_nao_fechou"]:
            return "Sem progressão"
        return rotulo_decisao.get(l["decisao_atual"], "-")

    df = pd.DataFrame(
        [
            {
                "nome": l["funcionario"].nome,
                "nivel_hierarquico": l["funcionario"].nivel_hierarquico or "-",
                "nota_2023": l["nota_2023"] if l["nota_2023"] is not None else "-",
                "nota_2024": l["nota_2024"] if l["nota_2024"] is not None else "-",
                "nota_2025": l["nota_2025"] if l["nota_2025"] is not None else "-",
                "par": par_texto(l),
                "ano_da_decisao": l["ano_decisao"] or "-",
                "decisao_situacao": decisao_texto(l),
                "chance_de_subir_este_ano": "Sim" if l["decide_esse_ano"] else "-",
            }
            for l in linhas
        ]
    )
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "nome", "nivel_hierarquico", "nota_2023", "nota_2024", "nota_2025",
                "par", "ano_da_decisao", "decisao_situacao", "chance_de_subir_este_ano",
            ]
        )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Progressao de Nivel")
        planilha = writer.sheets["Progressao de Nivel"]
        larguras = {"A": 34, "B": 18, "C": 11, "D": 11, "E": 11, "F": 11, "G": 15, "H": 26, "I": 22}
        for coluna, largura in larguras.items():
            planilha.column_dimensions[coluna].width = largura
    buffer.seek(0)

    nome_arquivo = f"progressao_nivel_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(
        buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


@admin_bp.route("/progressao-nivel/decisoes-2026", methods=["POST"])
def salvar_decisoes_2026():
    """Salva, de uma vez só, a decisão marcada por linha na tela simples de
    Progressão de Nível: A decidir / Sim, sobe / Não sobe / Já subiu
    (retroativo) / Não se aplica. O par usado é o da própria pessoa — 2023-2024
    pra quem já tinha os dois anos livres, 2024-2025 pra quem só habilita a
    partir do ano seguinte (vem do ponto de partida importado da planilha)."""
    funcionarios = Funcionario.query.filter_by(ativo=True).all()
    dados = carregar_dados_progressao()
    alterados = 0

    for funcionario in funcionarios:
        decisao = request.form.get(f"decisao_{funcionario.id}", "a_decidir")
        if decisao == "a_decidir":
            # Se a pessoa estava marcada como excluída e a opção voltou pra
            # "A decidir", desfaz a exclusão — sem isso, não tinha como
            # reverter depois de marcado.
            ponteiro = ProgressaoPontoPartida.query.get(funcionario.id)
            if ponteiro and ponteiro.excluido_progressao:
                ponteiro.excluido_progressao = False
                ponteiro.observacao = None
                alterados += 1
            continue

        if decisao in ("excluido_tabela", "excluido_recente"):
            ponteiro = ProgressaoPontoPartida.query.get(funcionario.id)
            if not ponteiro:
                ponteiro = ProgressaoPontoPartida(funcionario_id=funcionario.id)
                db.session.add(ponteiro)
            ponteiro.excluido_progressao = True
            ponteiro.observacao = {
                "excluido_tabela": "Fora da tabela salarial",
                "excluido_recente": "Admissão recente / ainda não avaliado",
            }[decisao]
            ponteiro.atualizado_por = "Administração"
            alterados += 1
            continue

        par_inicio, _ = ponto_partida_efetivo_do_funcionario(funcionario.id, dados)
        if not par_inicio:
            continue  # sem par definido pra essa pessoa ainda — nada a salvar
        par_fim = par_inicio + 1
        ano_decisao = par_fim + 1

        progressao = Progressao.query.filter_by(
            funcionario_id=funcionario.id, exercicio_inicio=par_inicio, exercicio_fim=par_fim
        ).first()
        if not progressao:
            progressao = Progressao(
                funcionario_id=funcionario.id, exercicio_inicio=par_inicio, exercicio_fim=par_fim
            )
            db.session.add(progressao)

        nivel_atual = funcionario.nivel_hierarquico
        if decisao == "sim":
            progressao.efetivada_em_exercicio = ano_decisao
            progressao.nivel_anterior = nivel_atual
            progressao.nivel_novo = proximo_nivel(nivel_atual)
            progressao.subiu = True
            progressao.decidido_por = "Administração"
            funcionario.nivel_hierarquico = progressao.nivel_novo
        elif decisao == "nao":
            progressao.efetivada_em_exercicio = ano_decisao
            progressao.nivel_anterior = nivel_atual
            progressao.nivel_novo = nivel_atual
            progressao.subiu = False
            progressao.decidido_por = "Administração"
        alterados += 1

    db.session.commit()
    flash(f"{alterados} decisão(ões) salva(s).", "success")
    return redirect(url_for("admin.progressao_nivel"))


@admin_bp.route("/progressao-nivel/importar", methods=["POST"])
def importar_progressao_nivel():
    """
    Importa o histórico pré-sistema via planilha (.xlsx/.csv) com as colunas:
    matricula (casa com o funcionário já cadastrado — se estiver em branco
    ou não bater com ninguém, cai pro casamento por nome, avisando na tela),
    nota_2023, nota_2024 (pelo menos uma delas), par_atual_inicio (opcional,
    "?" ou vazio = precisa confirmação do RH depois).
    Fluxo simples: lê, casa e já grava — sem tela de conferência prévia. Ao
    final, avisa quem não foi encontrado e quem foi casado só pelo nome.
    """
    arquivo = request.files.get("arquivo")
    if not arquivo or arquivo.filename == "":
        flash("Selecione um arquivo para importar.", "danger")
        return redirect(url_for("admin.progressao_nivel"))

    try:
        if arquivo.filename.lower().endswith(".csv"):
            df = pd.read_csv(arquivo)
        else:
            # Não exige um nome de aba específico: usa a primeira aba que
            # tiver uma coluna "matricula" ou "nome"; se nenhuma tiver, usa
            # a primeira aba do arquivo mesmo.
            planilhas = pd.read_excel(arquivo, sheet_name=None)
            df = next(iter(planilhas.values()))
            for aba in planilhas.values():
                colunas_aba = [str(c).strip().lower() for c in aba.columns]
                if "matricula" in colunas_aba or "nome" in colunas_aba:
                    df = aba
                    break
    except Exception as e:
        flash(f"Não foi possível ler o arquivo: {e}", "danger")
        return redirect(url_for("admin.progressao_nivel"))

    df.columns = [str(c).strip().lower() for c in df.columns]
    if "matricula" not in df.columns and "nome" not in df.columns:
        flash(
            "O arquivo precisa ter pelo menos uma coluna 'matricula' ou 'nome' "
            "para casar cada linha com um funcionário já cadastrado.",
            "danger",
        )
        return redirect(url_for("admin.progressao_nivel"))

    def normalizar_nome(nome):
        sem_acento = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
        return sem_acento.strip().lower()

    todos_funcionarios = Funcionario.query.all()
    funcionarios_por_matricula = {
        str(f.matricula).strip(): f for f in todos_funcionarios if f.matricula and str(f.matricula).strip()
    }
    funcionarios_por_nome = defaultdict(list)
    for f in todos_funcionarios:
        funcionarios_por_nome[normalizar_nome(f.nome)].append(f)

    colunas_nota = [c for c in df.columns if c.startswith("nota_")]
    importados, casados_por_nome, sem_matricula_na_planilha = 0, [], 0
    nao_encontrados, nomes_ambiguos = [], []

    for i, row in df.iterrows():
        funcionario = None
        matricula_raw = row.get("matricula") if "matricula" in df.columns else None
        matricula = None
        if not pd.isna(matricula_raw) and str(matricula_raw).strip():
            matricula = str(matricula_raw).strip()
            funcionario = funcionarios_por_matricula.get(matricula)
        else:
            sem_matricula_na_planilha += 1

        nome_raw = row.get("nome") if "nome" in df.columns else None
        if not funcionario and not pd.isna(nome_raw) and str(nome_raw).strip():
            candidatos = funcionarios_por_nome.get(normalizar_nome(nome_raw), [])
            if len(candidatos) == 1:
                funcionario = candidatos[0]
                casados_por_nome.append(f"linha {i + 2} ({nome_raw})")
            elif len(candidatos) > 1:
                nomes_ambiguos.append(f"linha {i + 2} ({nome_raw} — {len(candidatos)} funcionários com esse nome)")
                continue

        if not funcionario:
            identificador = matricula or (str(nome_raw).strip() if not pd.isna(nome_raw) else "sem matrícula/nome")
            nao_encontrados.append(f"linha {i + 2} ({identificador})")
            continue

        for coluna in colunas_nota:
            valor = row.get(coluna)
            if pd.isna(valor) or str(valor).strip() == "":
                continue
            exercicio = int(coluna.replace("nota_", ""))
            nota = float(valor)
            registro = HistoricoPreSistema.query.filter_by(
                funcionario_id=funcionario.id, exercicio=exercicio
            ).first()
            if not registro:
                registro = HistoricoPreSistema(funcionario_id=funcionario.id, exercicio=exercicio)
                db.session.add(registro)
            registro.nota = nota
            registro.origem = "importado"

        par_raw = row.get("par_atual_inicio")
        par_valor = None
        marcado_como_incerto = False
        if not pd.isna(par_raw):
            texto_par = str(par_raw).strip()
            if texto_par == "?":
                marcado_como_incerto = True
            elif texto_par != "":
                try:
                    par_valor = int(float(par_raw))
                except (ValueError, TypeError):
                    par_valor = None

        ponteiro = ProgressaoPontoPartida.query.get(funcionario.id)
        if not ponteiro:
            ponteiro = ProgressaoPontoPartida(funcionario_id=funcionario.id)
            db.session.add(ponteiro)
        ponteiro.exercicio_inicio = par_valor
        ponteiro.precisa_confirmacao = marcado_como_incerto
        observacao_raw = row.get("observacao")
        ponteiro.observacao = (
            str(observacao_raw).strip() if not pd.isna(observacao_raw) else None
        )
        ponteiro.atualizado_por = "Administração (importação de histórico)"

        importados += 1

    db.session.commit()

    mensagens = [f"{importados} registro(s) importado(s)."]
    nivel = "success"
    if casados_por_nome:
        mensagens.append(f"{len(casados_por_nome)} casado(s) só pelo nome (confira): " + ", ".join(casados_por_nome))
        nivel = "warning"
    if nomes_ambiguos:
        mensagens.append(f"{len(nomes_ambiguos)} nome(s) ambíguo(s), pulado(s): " + ", ".join(nomes_ambiguos))
        nivel = "warning"
    if nao_encontrados:
        mensagens.append(f"{len(nao_encontrados)} não encontrado(s): " + ", ".join(nao_encontrados))
        nivel = "warning"
    if importados == 0:
        mensagens.append(
            "Nenhuma linha foi importada — confira se a coluna 'matricula' do sistema "
            "está preenchida para os funcionários, ou se os nomes da planilha batem "
            "exatamente com os nomes cadastrados."
        )
        nivel = "danger"
    flash(" | ".join(mensagens), nivel)
    return redirect(url_for("admin.progressao_nivel"))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>")
def progressao_nivel_detalhe(funcionario_id):
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    dados = carregar_dados_progressao()
    situacao = calcular_situacao_par(funcionario, dados)
    notas = notas_detalhadas_do_funcionario(funcionario.id, dados)
    no_topo = esta_no_nivel_maximo(funcionario)
    ano_atual = datetime.now().year
    atrasada = (
        situacao["status"] == "elegivel"
        and not no_topo
        and situacao["exercicio_efetivacao"] is not None
        and situacao["exercicio_efetivacao"] < ano_atual
    )
    resumo = montar_resumo_progressao(situacao, no_topo, atrasada)
    progressoes = (
        Progressao.query.filter_by(funcionario_id=funcionario.id)
        .order_by(Progressao.exercicio_fim.desc())
        .all()
    )
    eventos = (
        EventoFuncionario.query.filter_by(funcionario_id=funcionario.id)
        .order_by(EventoFuncionario.exercicio.desc())
        .all()
    )
    ponteiro = ProgressaoPontoPartida.query.get(funcionario.id)
    return render_template(
        "admin/progressao_nivel_detalhe.html",
        funcionario=funcionario,
        situacao=situacao,
        no_topo=no_topo,
        atrasada=atrasada,
        resumo=resumo,
        progressoes=progressoes,
        eventos=eventos,
        ponteiro=ponteiro,
        notas=notas,
        niveis=NIVEIS_HIERARQUICOS,
        tipos_evento=TIPOS_EVENTO_FUNCIONARIO,
    )


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/nota", methods=["POST"])
def salvar_nota_historico(funcionario_id):
    """Digitar/editar direto a nota de um exercício pré-sistema, sem
    precisar passar por planilha — pensado pra correções pontuais."""
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    exercicio_raw = request.form.get("exercicio")
    nota_raw = request.form.get("nota")

    if not exercicio_raw or not nota_raw:
        flash("Preencha o exercício e a nota.", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    try:
        exercicio = int(exercicio_raw)
        nota = float(str(nota_raw).replace(",", "."))
    except (ValueError, TypeError):
        flash("Exercício ou nota inválidos.", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    registro = HistoricoPreSistema.query.filter_by(
        funcionario_id=funcionario.id, exercicio=exercicio
    ).first()
    if not registro:
        registro = HistoricoPreSistema(funcionario_id=funcionario.id, exercicio=exercicio)
        db.session.add(registro)
    registro.nota = nota
    registro.origem = "manual"
    db.session.commit()
    flash(f"Nota de {exercicio} salva.", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/nota/<int:exercicio>/excluir", methods=["POST"])
def excluir_nota_historico(funcionario_id, exercicio):
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    registro = HistoricoPreSistema.query.filter_by(
        funcionario_id=funcionario.id, exercicio=exercicio
    ).first()
    if registro:
        db.session.delete(registro)
        db.session.commit()
        flash(f"Nota de {exercicio} removida.", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/progressao/<int:progressao_id>/excluir", methods=["POST"])
def excluir_progressao(funcionario_id, progressao_id):
    """Remove um par já decidido (progressão ou 'não subiu') que foi
    registrado por engano — isso também desfaz o efeito dele no cálculo
    do próximo par (o ponto de partida volta a considerar só o que sobrar)."""
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    registro = Progressao.query.filter_by(id=progressao_id, funcionario_id=funcionario.id).first()
    if registro:
        db.session.delete(registro)
        db.session.commit()
        flash(f"Par {registro.exercicio_inicio}-{registro.exercicio_fim} removido.", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/evento/<int:evento_id>/excluir", methods=["POST"])
def excluir_evento_funcionario(funcionario_id, evento_id):
    """Remove um evento registrado por engano (ex.: mudança de função com
    o ano errado), que também deixa de empurrar o ponto de partida."""
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    registro = EventoFuncionario.query.filter_by(id=evento_id, funcionario_id=funcionario.id).first()
    if registro:
        db.session.delete(registro)
        db.session.commit()
        flash(f"Evento de {registro.exercicio} removido.", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/ponto-partida", methods=["POST"])
def salvar_ponto_partida(funcionario_id):
    """Digitar/editar direto o ponto de partida do par (o ano a partir do
    qual a contagem conta), sem precisar passar por planilha."""
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    exercicio_raw = request.form.get("exercicio_inicio", "").strip()

    ponteiro = ProgressaoPontoPartida.query.get(funcionario.id)
    if not ponteiro:
        ponteiro = ProgressaoPontoPartida(funcionario_id=funcionario.id)
        db.session.add(ponteiro)

    if exercicio_raw == "?":
        ponteiro.exercicio_inicio = None
        ponteiro.precisa_confirmacao = True
    elif exercicio_raw == "":
        ponteiro.exercicio_inicio = None
        ponteiro.precisa_confirmacao = False
    else:
        try:
            ponteiro.exercicio_inicio = int(exercicio_raw)
            ponteiro.precisa_confirmacao = False
        except ValueError:
            flash("Ponto de partida inválido — use um ano (ex: 2023) ou '?'.", "danger")
            return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    ponteiro.atualizado_por = "Administração (edição manual)"
    db.session.commit()
    flash("Ponto de partida salvo.", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/evento", methods=["POST"])
def registrar_evento_funcionario(funcionario_id):
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    tipo = request.form.get("tipo")
    exercicio = request.form.get("exercicio")
    observacao = request.form.get("observacao")

    if tipo not in TIPOS_EVENTO_FUNCIONARIO or not exercicio:
        flash("Preencha o tipo de evento e o exercício.", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    evento = EventoFuncionario(
        funcionario_id=funcionario.id,
        tipo=tipo,
        exercicio=int(exercicio),
        observacao=observacao,
        registrado_por="Administração",
    )
    db.session.add(evento)
    db.session.commit()
    flash("Evento registrado — a contagem do par foi ajustada.", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/efetivar", methods=["POST"])
def efetivar_progressao(funcionario_id):
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    situacao = calcular_situacao_par(funcionario)

    if situacao["status"] != "elegivel":
        flash("Este funcionário não está elegível para progressão no momento.", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    nivel_anterior = funcionario.nivel_hierarquico
    nivel_novo = request.form.get("nivel_novo") or nivel_anterior

    progressao = Progressao(
        funcionario_id=funcionario.id,
        exercicio_inicio=situacao["par_inicio"],
        exercicio_fim=situacao["par_fim"],
        efetivada_em_exercicio=situacao["exercicio_efetivacao"],
        nivel_anterior=nivel_anterior,
        nivel_novo=nivel_novo,
        subiu=True,
        decidido_por="Administração",
    )
    db.session.add(progressao)
    funcionario.nivel_hierarquico = nivel_novo
    db.session.commit()
    flash(f"Progressão efetivada: {funcionario.nome} ({nivel_anterior} \u2192 {nivel_novo}).", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/nao-efetivar", methods=["POST"])
def marcar_nao_efetivada(funcionario_id):
    """Registra a decisão de NÃO promover, mesmo com o par elegível. Assim
    como uma progressão de verdade, isso consome o par — o que passou,
    passou: o próximo par já usa os anos seguintes, não fica reaberto pra
    reconsiderar depois. A única diferença de 'Efetivar progressão' é que
    nivel_anterior e nivel_novo ficam iguais (nenhum nível muda)."""
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    situacao = calcular_situacao_par(funcionario)

    if situacao["status"] != "elegivel":
        flash("Este funcionário não está elegível para progressão no momento.", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    progressao = Progressao(
        funcionario_id=funcionario.id,
        exercicio_inicio=situacao["par_inicio"],
        exercicio_fim=situacao["par_fim"],
        efetivada_em_exercicio=situacao["exercicio_efetivacao"],
        nivel_anterior=funcionario.nivel_hierarquico,
        nivel_novo=funcionario.nivel_hierarquico,
        subiu=False,
        decidido_por="Administração (decidiu não promover)",
    )
    db.session.add(progressao)
    db.session.commit()
    flash(
        f"Registrado: {funcionario.nome} não vai subir de nível desta vez "
        f"(par {situacao['par_inicio']}-{situacao['par_fim']}). Próximo par já conta a partir de "
        f"{situacao['par_fim'] + 1}.",
        "success",
    )
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/progressao-retroativa", methods=["POST"])
def registrar_progressao_retroativa(funcionario_id):
    """Documenta uma progressão que já aconteceu de verdade fora do sistema
    (ex.: antes desse sistema existir). Diferente de 'Efetivar progressão',
    não depende da situação atual estar 'elegível' — o par e o ano de
    efetivação são digitados diretamente, porque já são fato passado.

    Isso grava o registro de auditoria (Progressao) e, por causa disso, o
    ponto de partida do próximo par passa a ser calculado automaticamente
    a partir daqui (exercicio_fim + 1) — não precisa mais editar o ponto
    de partida manualmente depois de registrar isso.
    """
    funcionario = Funcionario.query.get_or_404(funcionario_id)

    try:
        exercicio_inicio = int(request.form.get("exercicio_inicio"))
        exercicio_fim = int(request.form.get("exercicio_fim"))
        efetivada_em_exercicio = int(request.form.get("efetivada_em_exercicio"))
    except (TypeError, ValueError):
        flash("Preencha os três anos (início do par, fim do par, ano em que valeu).", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    nivel_anterior = request.form.get("nivel_anterior") or funcionario.nivel_hierarquico
    nivel_novo = request.form.get("nivel_novo") or funcionario.nivel_hierarquico

    progressao = Progressao(
        funcionario_id=funcionario.id,
        exercicio_inicio=exercicio_inicio,
        exercicio_fim=exercicio_fim,
        efetivada_em_exercicio=efetivada_em_exercicio,
        nivel_anterior=nivel_anterior,
        nivel_novo=nivel_novo,
        subiu=(nivel_anterior != nivel_novo),
        decidido_por="Administração (registro retroativo)",
    )
    db.session.add(progressao)
    if funcionario.nivel_hierarquico != nivel_novo:
        funcionario.nivel_hierarquico = nivel_novo
    db.session.commit()
    flash(
        f"Progressão retroativa registrada: {funcionario.nome} — par {exercicio_inicio}-{exercicio_fim}, "
        f"valendo desde {efetivada_em_exercicio} ({nivel_anterior} \u2192 {nivel_novo}).",
        "success",
    )
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/progressao-nivel/<uuid:funcionario_id>/nivel-manual", methods=["POST"])
def alterar_nivel_manual(funcionario_id):
    """Troca o nivel_hierarquico direto, sem passar pela regra do par nem
    exigir nenhum ano. Pra quando a decisão já foi tomada por fora e você só
    quer aplicar no cadastro — não cria registro em `progressoes` (não
    afeta o cálculo de qual será o próximo par contado pra essa pessoa).
    Se quiser que isso também conte como um par "gasto" pra fins de cálculo,
    use "Registrar progressão retroativa" em vez deste."""
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    nivel_novo = request.form.get("nivel_novo")

    if nivel_novo not in NIVEIS_HIERARQUICOS:
        flash("Nível inválido.", "danger")
        return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))

    nivel_anterior = funcionario.nivel_hierarquico
    funcionario.nivel_hierarquico = nivel_novo
    db.session.commit()
    flash(f"Nível alterado manualmente: {funcionario.nome} ({nivel_anterior} \u2192 {nivel_novo}).", "success")
    return redirect(url_for("admin.progressao_nivel_detalhe", funcionario_id=funcionario.id))


@admin_bp.route("/capacitacoes")
def capacitacoes():
    """Lista as capacitações de todos os funcionários (cadastradas por
    eles mesmos em "Minhas Capacitações"). Mesmo visual da tela do
    colaborador: ano + abas de trimestre + resumo + tabela. Na primeira
    visita abre no trimestre atual; 'Todos' nas abas/ano mostra tudo."""
    funcionario_id = request.args.get("funcionario_id") or None
    ano = request.args.get("ano", type=int)
    trimestre = request.args.get("trimestre", type=int)

    if not request.args:
        ano, trimestre = trimestre_atual()

    query = Capacitacao.query.join(Funcionario, Capacitacao.funcionario_id == Funcionario.id)
    if funcionario_id:
        query = query.filter(Capacitacao.funcionario_id == funcionario_id)
    if ano:
        query = query.filter(Capacitacao.ano == ano)
    if trimestre in (1, 2, 3, 4):
        query = query.filter(Capacitacao.trimestre == trimestre)
    else:
        trimestre = None

    lista = query.order_by(
        Funcionario.nome, Capacitacao.ano.desc(), Capacitacao.trimestre.desc(),
        Capacitacao.data_conclusao.desc().nullslast()
    ).all()

    anos = {r[0] for r in db.session.query(Capacitacao.ano).distinct().all()}
    anos.add(trimestre_atual()[0])
    if ano:
        anos.add(ano)
    anos = sorted(anos, reverse=True)

    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()

    total_horas = sum(c.carga_horaria or 0 for c in lista)
    total_valor = sum((c.valor_pago_senar or 0) for c in lista)
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
        "admin/capacitacoes.html",
        capacitacoes=lista,
        funcionarios=funcionarios,
        funcionario_id_selecionado=funcionario_id,
        anos=anos,
        ano_selecionado=ano,
        trimestre_selecionado=trimestre,
        trimestres=[1, 2, 3, 4],
        total_horas=total_horas,
        total_valor_fmt=total_valor_fmt,
        total_pessoas=len({c.funcionario_id for c in lista}),
        periodo_txt=periodo_txt,
    )


@admin_bp.route("/capacitacoes/<int:capacitacao_id>/documento")
def documento_capacitacao(capacitacao_id):
    from .main import resposta_documento_capacitacao

    return resposta_documento_capacitacao(Capacitacao.query.get_or_404(capacitacao_id))


@admin_bp.route("/")
def painel():
    total_funcionarios = Funcionario.query.filter_by(ativo=True).count()
    total_ciclos = CicloAvaliacao.query.count()
    ciclos = CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).all()
    return render_template(
        "admin/painel.html",
        total_funcionarios=total_funcionarios,
        total_ciclos=total_ciclos,
        ciclos=ciclos,
    )


# ---------------------------------------------------------
# Funcionários
# ---------------------------------------------------------
@admin_bp.route("/funcionarios", methods=["GET", "POST"])
def funcionarios():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        cargo_nome = request.form.get("cargo_nome", "").strip()
        setor_id = request.form.get("setor_id") or None
        nivel_hierarquico = request.form.get("nivel_hierarquico") or None
        email = request.form.get("email", "").strip()
        matricula = request.form.get("matricula", "").strip()
        cpf = request.form.get("cpf", "").strip()
        cpf = "".join(ch for ch in cpf if ch.isdigit()) or None
        sexo = request.form.get("sexo") or None
        data_nascimento_raw = request.form.get("data_nascimento") or None
        data_admissao_raw = request.form.get("data_admissao") or None
        salario_raw = request.form.get("salario", "").strip()
        elegivel_raw = request.form.get("elegivel_avaliacao", "auto")
        elegivel_avaliacao = {"sim": True, "nao": False}.get(elegivel_raw)  # None se "auto"

        data_nascimento = None
        if data_nascimento_raw:
            try:
                data_nascimento = datetime.strptime(data_nascimento_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Data de nascimento inválida.", "danger")
                return redirect(url_for("admin.funcionarios"))

        data_admissao = None
        if data_admissao_raw:
            try:
                data_admissao = datetime.strptime(data_admissao_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Data de admissão inválida.", "danger")
                return redirect(url_for("admin.funcionarios"))

        salario = None
        if salario_raw:
            try:
                salario = parse_salario(salario_raw)
            except ValueError:
                flash("Salário inválido.", "danger")
                return redirect(url_for("admin.funcionarios"))

        if not nome or not nivel_hierarquico:
            flash("Nome e nível hierárquico são obrigatórios.", "danger")
        else:
            cargo_id = None
            if cargo_nome:
                cargo = Cargo.query.filter(db.func.lower(Cargo.nome) == cargo_nome.lower()).first()
                if not cargo:
                    cargo = Cargo(nome=cargo_nome)
                    db.session.add(cargo)
                    db.session.flush()
                cargo_id = cargo.id

            senha_temp = gerar_senha_temporaria()
            novo = Funcionario(
                nome=nome,
                cargo_id=cargo_id,
                setor_id=int(setor_id) if setor_id else None,
                nivel_hierarquico=nivel_hierarquico,
                email=email or None,
                matricula=matricula or None,
                cpf=cpf,
                data_nascimento=data_nascimento,
                data_admissao=data_admissao,
                sexo=sexo,
                salario=salario,
                elegivel_avaliacao=elegivel_avaliacao,
                senha_provisoria=True,
            )
            novo.set_senha(senha_temp)
            db.session.add(novo)
            db.session.commit()
            if email:
                flash(
                    f"Funcionário {nome} cadastrado. Senha temporária: {senha_temp} "
                    f"(repasse para {email} — ela só aparece agora, guarde-a).",
                    "success",
                )
            else:
                flash(
                    f"Funcionário {nome} cadastrado, mas sem e-mail ele não consegue fazer login. "
                    f"Senha temporária gerada: {senha_temp}. Cadastre um e-mail para ele antes de repassar.",
                    "warning",
                )
        return redirect(url_for("admin.funcionarios"))

    setor_id_filtro = request.args.get("setor_id")
    status_filtro = request.args.get("status", "ativos")  # ativos (padrão) | inativos | todos
    consulta = Funcionario.query
    setor_filtro = None
    if setor_id_filtro:
        setor_filtro = Setor.query.get(int(setor_id_filtro))
        consulta = consulta.filter_by(setor_id=setor_id_filtro)

    # Contagens pro card de resumo — respeitam o filtro de setor (se houver),
    # mas mostram os três números lado a lado independente de qual status
    # está selecionado no momento.
    consulta_base_contagem = Funcionario.query
    if setor_id_filtro:
        consulta_base_contagem = consulta_base_contagem.filter_by(setor_id=setor_id_filtro)
    total_ativos = consulta_base_contagem.filter_by(ativo=True).count()
    total_inativos = consulta_base_contagem.filter_by(ativo=False).count()

    if status_filtro == "ativos":
        consulta = consulta.filter_by(ativo=True)
    elif status_filtro == "inativos":
        consulta = consulta.filter_by(ativo=False)
    # "todos" não filtra por status

    lista = consulta.order_by(Funcionario.nome).all()
    cargos = Cargo.query.order_by(Cargo.nome).all()
    setores = Setor.query.order_by(Setor.nome).all()
    return render_template(
        "admin/funcionarios.html",
        lista=lista,
        total_ativos=total_ativos,
        total_inativos=total_inativos,
        cargos=cargos,
        setores=setores,
        niveis=NIVEIS_HIERARQUICOS,
        opcoes_sexo=OPCOES_SEXO,
        setor_filtro=setor_filtro,
        status_filtro=status_filtro,
    )


@admin_bp.route("/funcionarios/exportar")
def exportar_funcionarios():
    """Exporta a lista de funcionários cadastrados para Excel."""
    lista = Funcionario.query.order_by(Funcionario.nome).all()

    def status_login(f):
        if not f.senha_hash:
            return "Sem senha"
        if f.senha_provisoria:
            return "Senha provisória"
        return "Ativo"

    def elegivel(f):
        eleg = f.is_elegivel_avaliacao()
        if eleg is None:
            return "-"
        return "Sim" if eleg else "Não"

    df = pd.DataFrame(
        [
            {
                "nome": f.nome,
                "cargo": f.cargo.nome if f.cargo else "-",
                "setor": f.setor.nome if f.setor else "-",
                "nivel_hierarquico": f.nivel_hierarquico or "-",
                "elegivel_avaliacao": elegivel(f),
                "login": status_login(f),
                "email": f.email or "-",
                "matricula": f.matricula or "-",
                "data_admissao": f.data_admissao.strftime("%d/%m/%Y") if f.data_admissao else "-",
                "cpf": formatar_cpf(f.cpf),
                "data_nascimento": f.data_nascimento.strftime("%d/%m/%Y") if f.data_nascimento else "-",
                "sexo": f.sexo or "-",
                "salario": f.salario if f.salario is not None else "-",
            }
            for f in lista
        ]
    )
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "nome", "cargo", "setor", "nivel_hierarquico", "elegivel_avaliacao",
                "login", "email", "matricula", "data_admissao", "cpf",
                "data_nascimento", "sexo", "salario",
            ]
        )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Funcionarios")
    buffer.seek(0)

    nome_arquivo = f"funcionarios_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(
        buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


@admin_bp.route("/funcionarios/gerar-senhas-pendentes", methods=["POST"])
def gerar_senhas_pendentes():
    pendentes = Funcionario.query.filter(
        Funcionario.senha_hash.is_(None), Funcionario.ativo.is_(True)
    ).order_by(Funcionario.nome).all()

    senhas_geradas = []
    for f in pendentes:
        senha_temp = gerar_senha_temporaria()
        f.set_senha(senha_temp)
        f.senha_provisoria = True
        senhas_geradas.append({"nome": f.nome, "email": f.email, "senha": senha_temp})
    db.session.commit()

    if not senhas_geradas:
        flash("Todo mundo já tem senha cadastrada.", "success")
        return redirect(url_for("admin.funcionarios"))

    return render_template(
        "admin/senhas_geradas.html", senhas=senhas_geradas, criados=len(senhas_geradas)
    )


@admin_bp.route("/funcionarios/<uuid:funcionario_id>/redefinir-senha", methods=["POST"])
def redefinir_senha(funcionario_id):
    funcionario = Funcionario.query.get_or_404(funcionario_id)
    senha_temp = gerar_senha_temporaria()
    funcionario.set_senha(senha_temp)
    funcionario.senha_provisoria = True
    db.session.commit()
    if funcionario.email:
        flash(
            f"Nova senha temporária de {funcionario.nome}: {senha_temp} "
            f"(repasse para {funcionario.email} — só aparece agora).",
            "success",
        )
    else:
        flash(
            f"Nova senha temporária de {funcionario.nome}: {senha_temp}. "
            f"Ele não tem e-mail cadastrado, então não vai conseguir logar até você adicionar um.",
            "warning",
        )
    return redirect(url_for("admin.funcionarios"))


@admin_bp.route("/funcionarios/<uuid:funcionario_id>/editar", methods=["GET", "POST"])
def editar_funcionario(funcionario_id):
    funcionario = Funcionario.query.get_or_404(funcionario_id)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        cargo_nome = request.form.get("cargo_nome", "").strip()
        setor_id = request.form.get("setor_id") or None
        nivel_hierarquico = request.form.get("nivel_hierarquico") or None
        email = request.form.get("email", "").strip()
        matricula = request.form.get("matricula", "").strip()
        cpf = request.form.get("cpf", "").strip()
        cpf = "".join(ch for ch in cpf if ch.isdigit()) or None
        sexo = request.form.get("sexo") or None
        data_nascimento_raw = request.form.get("data_nascimento") or None
        data_admissao_raw = request.form.get("data_admissao") or None
        data_demissao_raw = request.form.get("data_demissao") or None
        salario_raw = request.form.get("salario", "").strip()
        elegivel_raw = request.form.get("elegivel_avaliacao", "auto")
        elegivel_avaliacao = {"sim": True, "nao": False}.get(elegivel_raw)  # None se "auto"
        ativo = request.form.get("ativo") == "on"

        data_nascimento = None
        if data_nascimento_raw:
            try:
                data_nascimento = datetime.strptime(data_nascimento_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Data de nascimento inválida.", "danger")
                return redirect(url_for("admin.editar_funcionario", funcionario_id=funcionario_id))

        data_admissao = None
        if data_admissao_raw:
            try:
                data_admissao = datetime.strptime(data_admissao_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Data de admissão inválida.", "danger")
                return redirect(url_for("admin.editar_funcionario", funcionario_id=funcionario_id))

        data_demissao = None
        if data_demissao_raw:
            try:
                data_demissao = datetime.strptime(data_demissao_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Data de demissão inválida.", "danger")
                return redirect(url_for("admin.editar_funcionario", funcionario_id=funcionario_id))

        salario = None
        if salario_raw:
            try:
                salario = parse_salario(salario_raw)
            except ValueError:
                flash("Salário inválido.", "danger")
                return redirect(url_for("admin.editar_funcionario", funcionario_id=funcionario_id))

        if not nome or not nivel_hierarquico:
            flash("Nome e nível hierárquico são obrigatórios.", "danger")
            return redirect(url_for("admin.editar_funcionario", funcionario_id=funcionario_id))

        cargo_id = None
        if cargo_nome:
            cargo = Cargo.query.filter(db.func.lower(Cargo.nome) == cargo_nome.lower()).first()
            if not cargo:
                cargo = Cargo(nome=cargo_nome)
                db.session.add(cargo)
                db.session.flush()
            cargo_id = cargo.id

        funcionario.nome = nome
        funcionario.cargo_id = cargo_id
        funcionario.setor_id = int(setor_id) if setor_id else None
        funcionario.nivel_hierarquico = nivel_hierarquico
        funcionario.email = email or None
        funcionario.matricula = matricula or None
        funcionario.cpf = cpf
        funcionario.data_nascimento = data_nascimento
        funcionario.data_admissao = data_admissao
        funcionario.data_demissao = data_demissao
        funcionario.sexo = sexo
        funcionario.salario = salario
        funcionario.elegivel_avaliacao = elegivel_avaliacao
        funcionario.ativo = ativo
        db.session.commit()
        flash(f"Dados de {nome} atualizados.", "success")
        return redirect(url_for("admin.funcionarios"))

    cargos = Cargo.query.order_by(Cargo.nome).all()
    setores = Setor.query.order_by(Setor.nome).all()
    if funcionario.elegivel_avaliacao is None:
        elegivel_atual = "auto"
    elif funcionario.elegivel_avaliacao:
        elegivel_atual = "sim"
    else:
        elegivel_atual = "nao"
    return render_template(
        "admin/editar_funcionario.html",
        f=funcionario,
        cargos=cargos,
        setores=setores,
        niveis=NIVEIS_HIERARQUICOS,
        opcoes_sexo=OPCOES_SEXO,
        elegivel_atual=elegivel_atual,
    )


@admin_bp.route("/funcionarios/importar", methods=["POST"])
def importar_funcionarios():
    """
    Importa funcionários via planilha (.xlsx/.csv) com as colunas:
    nome, nivel_hierarquico (Empregado/Gestor/Superintendente - obrigatório, decide o formulário),
    cargo (opcional, cargo real - criado automaticamente se não existir), email (opcional), matricula (opcional)
    """
    arquivo = request.files.get("arquivo")
    if not arquivo or arquivo.filename == "":
        flash("Selecione um arquivo para importar.", "danger")
        return redirect(url_for("admin.funcionarios"))

    try:
        if arquivo.filename.lower().endswith(".csv"):
            df = pd.read_csv(arquivo)
        else:
            df = pd.read_excel(arquivo)
    except Exception as e:
        flash(f"Não foi possível ler o arquivo: {e}", "danger")
        return redirect(url_for("admin.funcionarios"))

    df.columns = [str(c).strip().lower() for c in df.columns]
    cargos_por_nome = {c.nome.lower(): c for c in Cargo.query.all()}
    setores_por_nome = {s.nome.lower(): s for s in Setor.query.all()}
    niveis_por_nome = {n.lower(): n for n in NIVEIS_HIERARQUICOS}

    criados, erros = 0, []
    senhas_geradas = []
    for i, row in df.iterrows():
        nome = str(row.get("nome", "")).strip()
        if not nome or nome.lower() == "nan":
            continue

        cargo = None
        cargo_nome_raw = row.get("cargo")
        if pd.notna(cargo_nome_raw) and str(cargo_nome_raw).strip():
            cargo_nome = str(cargo_nome_raw).strip()
            cargo = cargos_por_nome.get(cargo_nome.lower())
            if not cargo:
                # Cria o cargo automaticamente se ainda não existir
                cargo = Cargo(nome=cargo_nome)
                db.session.add(cargo)
                db.session.flush()
                cargos_por_nome[cargo_nome.lower()] = cargo

        setor = None
        setor_nome_raw = row.get("setor")
        if pd.notna(setor_nome_raw) and str(setor_nome_raw).strip():
            setor_nome = str(setor_nome_raw).strip()
            setor = setores_por_nome.get(setor_nome.lower())
            if not setor:
                # Cria o setor automaticamente se ainda não existir
                setor = Setor(nome=setor_nome)
                db.session.add(setor)
                db.session.flush()
                setores_por_nome[setor_nome.lower()] = setor

        nivel_raw = row.get("nivel_hierarquico")
        nivel_hierarquico = (
            niveis_por_nome.get(str(nivel_raw).strip().lower())
            if pd.notna(nivel_raw) and str(nivel_raw).strip()
            else None
        )
        if not nivel_hierarquico:
            erros.append(
                f"Linha {i + 2}: nível hierárquico '{row.get('nivel_hierarquico')}' não reconhecido/ausente "
                f"(precisa ser Empregado, Gestor ou Superintendente)"
            )
            continue

        email = row.get("email")
        matricula = row.get("matricula")

        cpf = None
        cpf_raw = row.get("cpf")
        if pd.notna(cpf_raw) and str(cpf_raw).strip():
            cpf = "".join(ch for ch in str(cpf_raw).strip() if ch.isdigit())

        data_nascimento = None
        data_raw = row.get("data_nascimento")
        if pd.notna(data_raw) and str(data_raw).strip():
            try:
                data_nascimento = pd.to_datetime(data_raw).date()
            except (ValueError, TypeError):
                erros.append(f"Linha {i + 2}: data de nascimento '{data_raw}' inválida")
                continue

        data_admissao = None
        data_admissao_raw = row.get("data_admissao")
        if pd.notna(data_admissao_raw) and str(data_admissao_raw).strip():
            try:
                data_admissao = pd.to_datetime(data_admissao_raw).date()
            except (ValueError, TypeError):
                erros.append(f"Linha {i + 2}: data de admissão '{data_admissao_raw}' inválida")
                continue

        sexo = None
        sexo_raw = row.get("sexo")
        if pd.notna(sexo_raw) and str(sexo_raw).strip():
            sexo_por_nome = {s.lower(): s for s in OPCOES_SEXO}
            sexo = sexo_por_nome.get(str(sexo_raw).strip().lower())
            if not sexo:
                erros.append(f"Linha {i + 2}: sexo '{sexo_raw}' não reconhecido")
                continue

        salario = None
        salario_raw = row.get("salario")
        if pd.notna(salario_raw) and str(salario_raw).strip():
            try:
                salario = parse_salario(salario_raw)
            except (ValueError, TypeError):
                erros.append(f"Linha {i + 2}: salário '{salario_raw}' inválido")
                continue

        elegivel_avaliacao = None  # None = calcular automaticamente pela data_admissao
        elegivel_raw = row.get("elegivel_avaliacao")
        if pd.notna(elegivel_raw) and str(elegivel_raw).strip():
            valor = str(elegivel_raw).strip().lower()
            if valor in ("sim", "s", "true", "1", "x"):
                elegivel_avaliacao = True
            elif valor in ("nao", "não", "n", "false", "0"):
                elegivel_avaliacao = False

        email_valor = str(email).strip() if pd.notna(email) else None
        senha_temp = gerar_senha_temporaria()
        novo = Funcionario(
            nome=nome,
            cargo_id=cargo.id if cargo else None,
            setor_id=setor.id if setor else None,
            nivel_hierarquico=nivel_hierarquico,
            email=email_valor,
            matricula=(str(matricula).strip() if pd.notna(matricula) else None),
            cpf=cpf,
            data_nascimento=data_nascimento,
            data_admissao=data_admissao,
            sexo=sexo,
            salario=salario,
            elegivel_avaliacao=elegivel_avaliacao,
            senha_provisoria=True,
        )
        novo.set_senha(senha_temp)
        db.session.add(novo)
        senhas_geradas.append(
            {"nome": nome, "email": email_valor, "senha": senha_temp}
        )
        criados += 1

    db.session.commit()
    if erros:
        flash(" | ".join(erros), "warning")
    if senhas_geradas:
        return render_template(
            "admin/senhas_geradas.html", senhas=senhas_geradas, criados=criados
        )
    flash(f"{criados} funcionário(s) importado(s).", "success")
    return redirect(url_for("admin.funcionarios"))


# ---------------------------------------------------------
# Setores
# ---------------------------------------------------------
@admin_bp.route("/setores", methods=["GET", "POST"])
def setores():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Informe o nome do setor.", "danger")
        elif Setor.query.filter(db.func.lower(Setor.nome) == nome.lower()).first():
            flash(f"Já existe um setor chamado '{nome}'.", "warning")
        else:
            db.session.add(Setor(nome=nome))
            db.session.commit()
            flash(f"Setor '{nome}' cadastrado.", "success")
        return redirect(url_for("admin.setores"))

    lista = Setor.query.order_by(Setor.nome).all()
    # conta quantos funcionários ativos há em cada setor
    contagem = {
        s.id: Funcionario.query.filter_by(setor_id=s.id, ativo=True).count()
        for s in lista
    }
    return render_template("admin/setores.html", lista=lista, contagem=contagem)


@admin_bp.route("/setores/<int:setor_id>/editar", methods=["POST"])
def editar_setor(setor_id):
    setor = Setor.query.get_or_404(setor_id)
    nome_novo = request.form.get("nome", "").strip()

    if not nome_novo:
        flash("Informe o nome do setor.", "danger")
    elif Setor.query.filter(
        db.func.lower(Setor.nome) == nome_novo.lower(), Setor.id != setor.id
    ).first():
        flash(f"Já existe um setor chamado '{nome_novo}'.", "warning")
    else:
        setor.nome = nome_novo
        db.session.commit()
        flash("Setor atualizado.", "success")

    return redirect(url_for("admin.setores"))


@admin_bp.route("/setores/<int:setor_id>/excluir", methods=["POST"])
def excluir_setor(setor_id):
    setor = Setor.query.get_or_404(setor_id)
    em_uso = Funcionario.query.filter_by(setor_id=setor.id).count()
    if em_uso:
        flash(
            f"Não é possível excluir '{setor.nome}': há {em_uso} funcionário(s) vinculado(s) a ele.",
            "danger",
        )
    else:
        db.session.delete(setor)
        db.session.commit()
        flash(f"Setor '{setor.nome}' excluído.", "success")
    return redirect(url_for("admin.setores"))


# ---------------------------------------------------------
# Vínculos avaliador x avaliado
# ---------------------------------------------------------
def _ciclo_selecionado_ou_aberto():
    """Resolve o ciclo a partir de ?ciclo_id=; se não vier, usa o ciclo aberto mais recente."""
    ciclo_id_param = request.values.get("ciclo_id")
    if ciclo_id_param:
        return CicloAvaliacao.query.get_or_404(int(ciclo_id_param))
    return (
        CicloAvaliacao.query.filter_by(status="aberto")
        .order_by(CicloAvaliacao.padrao.desc(), CicloAvaliacao.exercicio.desc())
        .first()
    )


@admin_bp.route("/vinculos", methods=["GET", "POST"])
def vinculos():
    ciclo = _ciclo_selecionado_ou_aberto()
    ciclos = CicloAvaliacao.query.order_by(CicloAvaliacao.exercicio.desc()).all()

    if request.method == "POST":
        if not ciclo:
            flash("Crie um ciclo de avaliação antes de cadastrar vínculos.", "danger")
            return redirect(url_for("admin.vinculos"))

        if ciclo.status != "aberto":
            flash("Este ciclo está encerrado. Reabra-o em Administração para editar vínculos.", "danger")
            return redirect(url_for("admin.vinculos", ciclo_id=ciclo.id))

        avaliado_id = request.form.get("avaliado_id")
        avaliador_id = request.form.get("avaliador_id")

        if not avaliado_id or not avaliador_id:
            flash("Selecione avaliado e avaliador.", "danger")
        elif avaliado_id == avaliador_id:
            flash("Avaliado e avaliador não podem ser a mesma pessoa aqui (a autoavaliação é automática).", "danger")
        else:
            existe = VinculoAvaliacao.query.filter_by(
                ciclo_id=ciclo.id, avaliado_id=avaliado_id, avaliador_id=avaliador_id
            ).first()
            if existe:
                flash("Esse vínculo já existe neste ciclo.", "warning")
            else:
                db.session.add(
                    VinculoAvaliacao(
                        ciclo_id=ciclo.id,
                        avaliado_id=avaliado_id,
                        avaliador_id=avaliador_id,
                    )
                )
                db.session.commit()
                flash("Vínculo cadastrado.", "success")
        return redirect(url_for("admin.vinculos", ciclo_id=ciclo.id))

    busca = request.args.get("q", "").strip()

    lista = []
    if ciclo:
        AvaliadorFuncionario = aliased(Funcionario)
        AvaliadoFuncionario = aliased(Funcionario)
        query = (
            VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id)
            .join(AvaliadorFuncionario, VinculoAvaliacao.avaliador_id == AvaliadorFuncionario.id)
            .join(AvaliadoFuncionario, VinculoAvaliacao.avaliado_id == AvaliadoFuncionario.id)
        )
        if busca:
            query = query.filter(AvaliadorFuncionario.nome.ilike(f"%{busca}%"))
        lista = query.order_by(AvaliadorFuncionario.nome, AvaliadoFuncionario.nome).all()

    funcionarios_ativos = (
        Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    )
    return render_template(
        "admin/vinculos.html",
        ciclo=ciclo,
        ciclos=ciclos,
        lista=lista,
        funcionarios=funcionarios_ativos,
        busca=busca,
    )


@admin_bp.route("/vinculos/exportar")
def exportar_vinculos():
    """Exporta os vínculos do ciclo selecionado (ou aberto) para Excel, respeitando a busca por nome do avaliado (q)."""
    ciclo = _ciclo_selecionado_ou_aberto()
    if not ciclo:
        flash("Crie um ciclo de avaliação antes de exportar vínculos.", "danger")
        return redirect(url_for("admin.vinculos"))

    busca = request.args.get("q", "").strip()

    AvaliadorFuncionario = aliased(Funcionario)
    AvaliadoFuncionario = aliased(Funcionario)
    query = (
        VinculoAvaliacao.query.filter_by(ciclo_id=ciclo.id)
        .join(AvaliadorFuncionario, VinculoAvaliacao.avaliador_id == AvaliadorFuncionario.id)
        .join(AvaliadoFuncionario, VinculoAvaliacao.avaliado_id == AvaliadoFuncionario.id)
    )
    if busca:
        query = query.filter(AvaliadorFuncionario.nome.ilike(f"%{busca}%"))
    lista = query.order_by(AvaliadorFuncionario.nome, AvaliadoFuncionario.nome).all()

    df = pd.DataFrame(
        [{"avaliado": v.avaliado.nome, "avaliador": v.avaliador.nome} for v in lista]
    )
    if df.empty:
        df = pd.DataFrame(columns=["avaliado", "avaliador"])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Vinculos")
    buffer.seek(0)

    nome_arquivo = f"vinculos_avaliacao_{ciclo.exercicio}.xlsx"
    return Response(
        buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


@admin_bp.route("/vinculos/<int:vinculo_id>/excluir", methods=["POST"])
def excluir_vinculo(vinculo_id):
    vinculo = VinculoAvaliacao.query.get_or_404(vinculo_id)
    ciclo_id = vinculo.ciclo_id
    ciclo = CicloAvaliacao.query.get(ciclo_id)
    if ciclo and ciclo.status != "aberto":
        flash("Este ciclo está encerrado. Reabra-o em Administração para remover vínculos.", "danger")
        return redirect(url_for("admin.vinculos", ciclo_id=ciclo_id))
    db.session.delete(vinculo)
    db.session.commit()
    flash("Vínculo removido.", "success")
    return redirect(url_for("admin.vinculos", ciclo_id=ciclo_id))


@admin_bp.route("/vinculos/<int:vinculo_id>/editar", methods=["POST"])
def editar_vinculo(vinculo_id):
    vinculo = VinculoAvaliacao.query.get_or_404(vinculo_id)

    avaliado_id = request.form.get("avaliado_id")
    avaliador_id = request.form.get("avaliador_id")
    busca = request.form.get("q", "").strip()

    ciclo_atual = CicloAvaliacao.query.get(vinculo.ciclo_id)
    if ciclo_atual and ciclo_atual.status != "aberto":
        flash("Este ciclo está encerrado. Reabra-o em Administração para editar vínculos.", "danger")
        return redirect(url_for("admin.vinculos", q=busca, ciclo_id=vinculo.ciclo_id))

    if not avaliado_id or not avaliador_id:
        flash("Selecione avaliado e avaliador.", "danger")
        return redirect(url_for("admin.vinculos", q=busca, ciclo_id=vinculo.ciclo_id))

    if avaliado_id == avaliador_id:
        flash("Avaliado e avaliador não podem ser a mesma pessoa aqui (a autoavaliação é automática).", "danger")
        return redirect(url_for("admin.vinculos", q=busca, ciclo_id=vinculo.ciclo_id))

    existe = VinculoAvaliacao.query.filter(
        VinculoAvaliacao.ciclo_id == vinculo.ciclo_id,
        VinculoAvaliacao.avaliado_id == avaliado_id,
        VinculoAvaliacao.avaliador_id == avaliador_id,
        VinculoAvaliacao.id != vinculo.id,
    ).first()
    if existe:
        flash("Esse vínculo já existe neste ciclo.", "warning")
        return redirect(url_for("admin.vinculos", q=busca, ciclo_id=vinculo.ciclo_id))

    vinculo.avaliado_id = avaliado_id
    vinculo.avaliador_id = avaliador_id
    db.session.commit()
    flash("Vínculo atualizado.", "success")
    return redirect(url_for("admin.vinculos", q=busca, ciclo_id=vinculo.ciclo_id))


@admin_bp.route("/vinculos/importar", methods=["POST"])
def importar_vinculos():
    """
    Importa vínculos via planilha (.xlsx/.csv) com as colunas:
    avaliado, avaliador  (nomes exatamente como cadastrados em funcionarios.nome)
    """
    ciclo = _ciclo_selecionado_ou_aberto()
    if not ciclo:
        flash("Crie um ciclo de avaliação antes de importar vínculos.", "danger")
        return redirect(url_for("admin.vinculos"))

    if ciclo.status != "aberto":
        flash("Este ciclo está encerrado. Reabra-o em Administração para importar vínculos.", "danger")
        return redirect(url_for("admin.vinculos", ciclo_id=ciclo.id))

    arquivo = request.files.get("arquivo")
    if not arquivo or arquivo.filename == "":
        flash("Selecione um arquivo para importar.", "danger")
        return redirect(url_for("admin.vinculos", ciclo_id=ciclo.id))

    try:
        if arquivo.filename.lower().endswith(".csv"):
            df = pd.read_csv(arquivo)
        else:
            df = pd.read_excel(arquivo)
    except Exception as e:
        flash(f"Não foi possível ler o arquivo: {e}", "danger")
        return redirect(url_for("admin.vinculos", ciclo_id=ciclo.id))

    df.columns = [str(c).strip().lower() for c in df.columns]
    funcionarios_por_nome = {f.nome.strip().lower(): f for f in Funcionario.query.all()}

    criados, erros = 0, []
    for i, row in df.iterrows():
        nome_avaliado = str(row.get("avaliado", "")).strip()
        nome_avaliador = str(row.get("avaliador", "")).strip()
        if not nome_avaliado or nome_avaliado.lower() == "nan":
            continue

        avaliado = funcionarios_por_nome.get(nome_avaliado.lower())
        avaliador = funcionarios_por_nome.get(nome_avaliador.lower())

        if not avaliado or not avaliador:
            erros.append(f"Linha {i + 2}: '{nome_avaliado}' ou '{nome_avaliador}' não encontrado")
            continue

        existe = VinculoAvaliacao.query.filter_by(
            ciclo_id=ciclo.id, avaliado_id=avaliado.id, avaliador_id=avaliador.id
        ).first()
        if not existe:
            db.session.add(
                VinculoAvaliacao(
                    ciclo_id=ciclo.id, avaliado_id=avaliado.id, avaliador_id=avaliador.id
                )
            )
            criados += 1

    db.session.commit()
    flash(f"{criados} vínculo(s) importado(s).", "success")
    if erros:
        flash(" | ".join(erros), "warning")
    return redirect(url_for("admin.vinculos", ciclo_id=ciclo.id))


# ---------------------------------------------------------
# Ciclos de avaliação
# ---------------------------------------------------------
@admin_bp.route("/ciclos", methods=["POST"])
def criar_ciclo():
    exercicio = request.form.get("exercicio")
    data_inicio = request.form.get("data_inicio") or None
    data_fim = request.form.get("data_fim") or None
    data_limite_autoavaliacao = request.form.get("data_limite_autoavaliacao") or None
    data_limite_gestor = request.form.get("data_limite_gestor") or None

    if not exercicio:
        flash("Informe o exercício (ano).", "danger")
        return redirect(url_for("admin.painel"))

    if CicloAvaliacao.query.filter_by(exercicio=int(exercicio)).first():
        flash("Já existe um ciclo para esse exercício.", "warning")
        return redirect(url_for("admin.painel"))

    db.session.add(
        CicloAvaliacao(
            exercicio=int(exercicio),
            data_inicio=data_inicio,
            data_fim=data_fim,
            data_limite_autoavaliacao=data_limite_autoavaliacao,
            data_limite_gestor=data_limite_gestor,
            status="aberto",
        )
    )
    db.session.commit()
    flash("Ciclo de avaliação criado.", "success")
    return redirect(url_for("admin.painel"))


@admin_bp.route("/ciclos/<int:ciclo_id>/prazos", methods=["POST"])
def editar_prazos_ciclo(ciclo_id):
    """Atualiza o exercício e/ou a data limite de autoavaliação e de avaliação
    do gestor de um ciclo já existente. Renomear o exercício não afeta os
    vínculos/avaliações já cadastrados, pois eles apontam para o ciclo pelo
    id interno, não pelo ano exibido."""
    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)

    novo_exercicio = request.form.get("exercicio")
    if novo_exercicio:
        novo_exercicio = int(novo_exercicio)
        conflito = CicloAvaliacao.query.filter(
            CicloAvaliacao.exercicio == novo_exercicio,
            CicloAvaliacao.id != ciclo.id,
        ).first()
        if conflito:
            flash(f"Já existe outro ciclo com o exercício {novo_exercicio}.", "danger")
            return redirect(url_for("admin.painel"))
        ciclo.exercicio = novo_exercicio

    ciclo.data_limite_autoavaliacao = request.form.get("data_limite_autoavaliacao") or None
    ciclo.data_limite_gestor = request.form.get("data_limite_gestor") or None
    if "data_inicio" in request.form:
        ciclo.data_inicio = request.form.get("data_inicio") or None
    if "data_fim" in request.form:
        ciclo.data_fim = request.form.get("data_fim") or None
    db.session.commit()
    flash(f"Ciclo {ciclo.exercicio} atualizado.", "success")
    return redirect(url_for("admin.painel"))


@admin_bp.route("/ciclos/<int:ciclo_id>/encerrar", methods=["POST"])
def encerrar_ciclo(ciclo_id):
    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    ciclo.status = "encerrado"
    db.session.commit()
    flash(f"Ciclo {ciclo.exercicio} encerrado.", "success")
    return redirect(url_for("admin.painel"))


@admin_bp.route("/ciclos/<int:ciclo_id>/reabrir", methods=["POST"])
def reabrir_ciclo(ciclo_id):
    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    ciclo.status = "aberto"
    db.session.commit()
    flash(f"Ciclo {ciclo.exercicio} reaberto.", "success")
    return redirect(url_for("admin.painel"))


@admin_bp.route("/ciclos/<int:ciclo_id>/definir_padrao", methods=["POST"])
def definir_ciclo_padrao(ciclo_id):
    """Marca este ciclo como o padrão a ser usado nas telas (funcionário e
    admin) quando ninguém escolhe o ciclo explicitamente via ?ciclo_id=.
    Útil quando há mais de um ciclo "aberto" ao mesmo tempo (ex: o ano
    anterior ainda em avaliação e o ano corrente já criado) — sem isso, o
    sistema sempre assumia o exercício mais recente como padrão."""
    ciclo = CicloAvaliacao.query.get_or_404(ciclo_id)
    CicloAvaliacao.query.update({CicloAvaliacao.padrao: False})
    ciclo.padrao = True
    db.session.commit()
    flash(f"Ciclo {ciclo.exercicio} definido como padrão.", "success")
    return redirect(url_for("admin.painel"))


@admin_bp.route("/comissao", methods=["GET", "POST"])
def comissao():
    """Gerencia quem faz parte da Comissão de Recursos (grupo fixo) e quem
    é a presidência (decide o recurso quando escalado)."""
    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "adicionar_membro":
            funcionario_id = request.form.get("funcionario_id")
            if funcionario_id:
                ja_existe = MembroComissao.query.filter_by(funcionario_id=funcionario_id).first()
                if ja_existe:
                    flash("Essa pessoa já está na Comissão.", "warning")
                else:
                    db.session.add(MembroComissao(funcionario_id=funcionario_id))
                    db.session.commit()
                    flash("Adicionado à Comissão.", "success")

        elif acao == "remover_membro":
            membro_id = request.form.get("membro_id")
            membro = MembroComissao.query.get(membro_id) if membro_id else None
            if membro:
                db.session.delete(membro)
                db.session.commit()
                flash("Removido da Comissão.", "success")

        elif acao == "definir_presidencia":
            funcionario_id = request.form.get("funcionario_id")
            Funcionario.query.update({Funcionario.eh_presidencia: False})
            if funcionario_id:
                funcionario = Funcionario.query.get(funcionario_id)
                if funcionario:
                    funcionario.eh_presidencia = True
                    flash(f"{funcionario.nome} agora é a presidência.", "success")
            else:
                flash("Presidência removida (ninguém definido).", "success")
            db.session.commit()

        return redirect(url_for("admin.comissao"))

    membros = MembroComissao.query.join(Funcionario).order_by(Funcionario.nome).all()
    presidencia_atual = Funcionario.query.filter_by(eh_presidencia=True).first()
    funcionarios_ativos = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()

    return render_template(
        "admin/comissao.html",
        membros=membros,
        presidencia_atual=presidencia_atual,
        funcionarios=funcionarios_ativos,
    )


# ---------------------------------------------------------
# Devolutiva de Funcionários (COM ENVIO DE EMAIL)
# ---------------------------------------------------------

def enviar_email_devolutiva(funcionario, data_devolutiva, data_limite):
    """
    Envia email para o funcionário informando que devolutiva foi marcada.
    Usa o sistema de e-mail já existente no projeto (app/email_service.py),
    que roda em segundo plano e nunca quebra a ação do admin caso falhe.
    """
    from ..email_service import avisar_empregado_devolutiva_marcada

    if not funcionario.email:
        current_app.logger.warning(
            "Devolutiva marcada para %s, mas não há e-mail cadastrado.",
            funcionario.nome,
        )
        return

    avisar_empregado_devolutiva_marcada(funcionario, data_devolutiva, data_limite)


@admin_bp.route("/devolutiva/funcionarios", methods=["GET"])
def listar_funcionarios_devolutiva():
    """Lista todos funcionários para admin marcar devolutiva."""
    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    
    lista = []
    for func in funcionarios:
        info = {
            "id": str(func.id),
            "nome": func.nome,
            "email": func.email or "-",
            "data_devolutiva": func.devolutiva.data_devolutiva if func.devolutiva else None,
            "data_limite": func.devolutiva.data_limite_recorrer if func.devolutiva else None,
            "tem_devolutiva": func.tem_devolutiva_marcada()
        }
        lista.append(info)
    
    return render_template(
        "admin/devolutiva_funcionarios.html",
        funcionarios=lista
    )


@admin_bp.route("/devolutiva/funcionario/<funcionario_id>/marcar", methods=["POST"])
def marcar_devolutiva_funcionario(funcionario_id):
    """Admin marca data de devolutiva para UM funcionário. Envia email automático."""
    try:
        funcionario = Funcionario.query.get_or_404(funcionario_id)
    except:
        flash("Funcionário não encontrado.", "error")
        return redirect(request.referrer or url_for("admin.painel"))
    
    data_devolutiva_str = request.form.get("data_devolutiva")
    if not data_devolutiva_str:
        flash("Data de devolutiva é obrigatória.", "error")
        return redirect(request.referrer or url_for("admin.listar_funcionarios_devolutiva"))
    
    try:
        data_devolutiva = datetime.strptime(data_devolutiva_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Formato de data inválido.", "error")
        return redirect(request.referrer or url_for("admin.listar_funcionarios_devolutiva"))
    
    data_limite = data_devolutiva + timedelta(days=5)
    
    devolutiva = DevolutivaPorFuncionario.query.filter_by(funcionario_id=funcionario_id).first()
    
    if devolutiva:
        devolutiva.data_devolutiva = data_devolutiva
        devolutiva.data_limite_recorrer = data_limite
        devolutiva.marcado_em = datetime.now(timezone.utc)
        devolutiva.marcado_por = session.get("email", "admin")
        acao = "Atualizada"
    else:
        devolutiva = DevolutivaPorFuncionario(
            funcionario_id=funcionario_id,
            data_devolutiva=data_devolutiva,
            data_limite_recorrer=data_limite,
            marcado_em=datetime.now(timezone.utc),
            marcado_por=session.get("email", "admin")
        )
        db.session.add(devolutiva)
        acao = "Marcada"
    
    db.session.commit()
    
    enviar_email_devolutiva(funcionario, data_devolutiva, data_limite)
    
    flash(
        f"✅ Devolutiva {acao} para {funcionario.nome}! "
        f"Data: {data_devolutiva.strftime('%d/%m/%Y')} | "
        f"Prazo: até {data_limite.strftime('%d/%m/%Y')} | "
        f"📧 Email enviado",
        "success"
    )
    
    return redirect(request.referrer or url_for("admin.resultados"))
def remover_devolutiva_funcionario(funcionario_id):
    """Admin remove devolutiva marcada para um funcionário."""
    try:
        funcionario = Funcionario.query.get_or_404(funcionario_id)
    except:
        flash("Funcionário não encontrado.", "error")
        return redirect(request.referrer or url_for("admin.painel"))
    
    devolutiva = DevolutivaPorFuncionario.query.filter_by(funcionario_id=funcionario_id).first()
    
    if devolutiva:
        db.session.delete(devolutiva)
        db.session.commit()
        flash(f"Devolutiva de {funcionario.nome} removida.", "success")
    else:
        flash(f"{funcionario.nome} não tem devolutiva marcada.", "info")
    
    return redirect(url_for("admin.listar_funcionarios_devolutiva"))
