from flask import Blueprint, render_template

painel_bp = Blueprint("painel", __name__)


@painel_bp.route("/painel")
def painel_monitoramento():
    """Exibe o painel de monitoramento das avaliações de desempenho."""
    return render_template("painel_monitoramento_sistema.html")
