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
        from .routes.main import funcionario_logado
        from .routes.recursos import (
            contar_recursos_pendentes_comissao,
            contar_recursos_pendentes_gestor,
        )

        funcionario = funcionario_logado()
        return {
            "funcionario_atual": funcionario,
            "recursos_pendentes_comissao": contar_recursos_pendentes_comissao(),
            "recursos_pendentes_gestor": contar_recursos_pendentes_gestor(
                funcionario.id if funcionario else None
            ),
        }

    return app
