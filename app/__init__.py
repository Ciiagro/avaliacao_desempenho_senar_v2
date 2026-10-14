import os
from urllib.parse import urlparse

from flask import Flask, request

from .config import Config
from .extensions import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ---- Segurança da sessão -------------------------------------------
    em_producao = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
    chave = app.config.get("SECRET_KEY")
    if not chave or chave == "dev-key-mude-isso":
        if em_producao:
            raise RuntimeError(
                "SECRET_KEY não configurada (ou ainda com o valor de exemplo). "
                "Defina uma chave longa e aleatória em Settings > Environment Variables do Vercel."
            )
        # só no computador de desenvolvimento
        app.config["SECRET_KEY"] = "dev-key-apenas-para-desenvolvimento-local"
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,   # JavaScript da página não lê o cookie
        SESSION_COOKIE_SAMESITE="Lax",  # não vai junto em POSTs vindos de outros sites
        SESSION_COOKIE_SECURE=em_producao,  # só trafega por HTTPS
    )

    db.init_app(app)

    @app.before_request
    def proteger_contra_csrf():
        """Barra formulários enviados por OUTRO site em nome de quem está logado.

        Todo POST/PUT/PATCH/DELETE precisa vir do próprio sistema: o navegador
        informa a origem da requisição (Sec-Fetch-Site / Origin / Referer) e
        isso não pode ser forjado por uma página de terceiros. Não exige nenhum
        campo extra nos formulários.
        """
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None

        if request.headers.get("Sec-Fetch-Site") in ("same-origin", "none"):
            return None

        hosts_aceitos = {request.host.lower()}
        for h in request.headers.get("X-Forwarded-Host", "").split(","):
            if h.strip():
                hosts_aceitos.add(h.strip().lower())
        origem = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if origem and urlparse(origem).netloc.lower() in hosts_aceitos:
            return None

        app.logger.warning("Requisição bloqueada (origem diferente): %s %s", request.method, request.path)
        return (
            "<p style='font-family:sans-serif'>Requisição bloqueada por segurança "
            "(origem diferente do sistema). Volte, recarregue a página e tente de novo.</p>",
            403,
        )

    from .utils import formatar_cpf, para_fortaleza, separar_resposta_por_item

    app.jinja_env.filters["formatar_cpf"] = formatar_cpf
    app.jinja_env.filters["fortaleza"] = para_fortaleza
    app.jinja_env.filters["separar_resposta_por_item"] = separar_resposta_por_item

    from .routes.main import main_bp
    from .routes.avaliacoes import avaliacoes_bp
    from .routes.admin import admin_bp
    from .routes.recursos import recursos_bp
    from .routes.painel import painel_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(avaliacoes_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(recursos_bp)
    app.register_blueprint(painel_bp)

    @app.context_processor
    def injetar_funcionario_logado():
        """Roda em toda página do sistema, então cada consulta feita aqui é
        multiplicada por cada clique de cada usuário — por isso só busca o
        que realmente vai ser usado no menu (base.html), e computa
        eh_gestor/eh_membro_comissao uma única vez em vez de deixar o
        template chamar esses métodos de novo (o que faria a mesma consulta
        rodar duas vezes por página)."""
        from .routes.main import funcionario_logado
        from .routes.recursos import (
            contar_recursos_pendentes_comissao,
            contar_recursos_pendentes_gestor,
            resultado_pendente_ciencia_do_funcionario,
        )

        funcionario = funcionario_logado()

        if funcionario:
            eh_gestor = funcionario.eh_gestor_de_alguem()
            eh_comissao = funcionario.eh_membro_comissao()
            resultado_pendente = resultado_pendente_ciencia_do_funcionario(funcionario.id)
            # O menu "Recurso" só existe pra quem decidiu recorrer (ou já tem
            # recurso aberto). Quem só está vendo a nota final não vê o menu:
            # a escolha de aceitar/recorrer é feita na tela do resultado.
            from .models import RecursoAvaliacao, ResultadoFinal

            mostrar_menu_recurso = (
                ResultadoFinal.query.filter_by(
                    avaliado_id=funcionario.id, liberado=True, decisao_avaliado="recorreu"
                ).first()
                is not None
                or RecursoAvaliacao.query.filter_by(avaliado_id=funcionario.id).first()
                is not None
            )
            recursos_gestor = (
                contar_recursos_pendentes_gestor(funcionario.id) if eh_gestor else 0
            )
        else:
            eh_gestor = False
            eh_comissao = False
            resultado_pendente = None
            mostrar_menu_recurso = False
            recursos_gestor = 0

        # O link "Comissão" só aparece se não há ninguém logado (visitante)
        # ou se quem está logado é membro da comissão — nesses outros casos
        # nem vale a pena contar os recursos pendentes da comissão.
        mostrar_comissao = (not funcionario) or eh_comissao
        recursos_comissao = contar_recursos_pendentes_comissao() if mostrar_comissao else 0

        return {
            "funcionario_atual": funcionario,
            "funcionario_eh_gestor": eh_gestor,
            "funcionario_eh_comissao": eh_comissao,
            "recursos_pendentes_comissao": recursos_comissao,
            "recursos_pendentes_gestor": recursos_gestor,
            "resultado_pendente_ciencia": resultado_pendente,
            "mostrar_menu_recurso": mostrar_menu_recurso,
        }

    return app
