from flask import Flask

from .config import Config
from .extensions import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    from .utils import formatar_cpf, para_fortaleza

    app.jinja_env.filters["formatar_cpf"] = formatar_cpf
    app.jinja_env.filters["fortaleza"] = para_fortaleza

    from .routes.main import main_bp
    from .routes.avaliacoes import avaliacoes_bp
    from .routes.admin import admin_bp
    from .routes.recursos import recursos_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(avaliacoes_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(recursos_bp)

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
            recursos_gestor = (
                contar_recursos_pendentes_gestor(funcionario.id) if eh_gestor else 0
            )
        else:
            eh_gestor = False
            eh_comissao = False
            resultado_pendente = None
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
        }

    return app
