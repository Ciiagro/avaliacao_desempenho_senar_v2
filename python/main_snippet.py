# =====================================================================
# ADICIONAR A main.py - ROTAS DE DEVOLUTIVA PARA COLABORADOR
# =====================================================================

from datetime import datetime, timezone

# ========== ROTA 1: Ver Devolutiva (Colaborador) ==========

@main_bp.route("/meu-recurso/<int:recurso_id>/devolutiva", methods=["GET"])
def ver_devolutiva_recurso(recurso_id):
    """
    Colaborador visualiza a devolutiva de um recurso.
    
    A data de devolutiva é do FUNCIONÁRIO, não do recurso.
    Todos os recursos do funcionário usam a mesma data de devolutiva.
    """
    from ..models import RecursoAvaliacao, RecursoEvento
    
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    
    # Verificar se o colaborador é proprietário
    funcionario_id = session.get("funcionario_id")
    if str(recurso.avaliado_id) != str(funcionario_id):
        flash("Você não tem permissão para acessar este recurso.", "error")
        return redirect(url_for("main.meus_recursos"))
    
    funcionario = recurso.avaliado
    
    # Verificar se funcionário tem devolutiva marcada
    if not funcionario.tem_devolutiva_marcada():
        flash("A devolutiva ainda não foi marcada para você.", "info")
        return redirect(url_for("main.meus_recursos"))
    
    # Obter eventos relevantes do recurso
    eventos_relevantes = RecursoEvento.query.filter(
        RecursoEvento.recurso_id == recurso_id,
        RecursoEvento.tipo.in_(["resposta_gestor", "decisao_presidencia"])
    ).order_by(RecursoEvento.criado_em).all()
    
    # Obter informações de devolutiva do FUNCIONÁRIO
    pode_recorrer = funcionario.pode_recorrer_apos_devolutiva()
    dias_restantes = funcionario.dias_restantes_recorrer()
    
    return render_template(
        "recurso_devolutiva.html",
        recurso=recurso,
        funcionario=funcionario,
        eventos_relevantes=eventos_relevantes,
        pode_recorrer=pode_recorrer,
        dias_restantes=dias_restantes,
    )


# ========== ROTA 2: Concordar com Devolutiva ==========

@main_bp.route("/meu-recurso/<int:recurso_id>/aceitar-devolutiva", methods=["POST"])
def aceitar_devolutiva_recurso(recurso_id):
    """
    Colaborador concorda com a resposta da devolutiva.
    Encerra o recurso.
    """
    from ..models import RecursoAvaliacao, RecursoEvento
    
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    
    # Verificar permissão
    funcionario_id = session.get("funcionario_id")
    if str(recurso.avaliado_id) != str(funcionario_id):
        flash("Você não tem permissão.", "error")
        return redirect(url_for("main.meus_recursos"))
    
    funcionario = recurso.avaliado
    
    # Verificar se tem devolutiva marcada
    if not funcionario.tem_devolutiva_marcada():
        flash("Devolutiva não foi marcada para você.", "error")
        return redirect(url_for("main.meus_recursos"))
    
    # Marcar como encerrado
    recurso.status = "encerrado"
    recurso.ciente_funcionario = True
    recurso.ciente_funcionario_em = datetime.now(timezone.utc)
    
    # Registrar evento
    evento = RecursoEvento(
        recurso_id=recurso.id,
        tipo="aceite_devolutiva",
        descricao="Funcionário aceitou a resposta da devolutiva.",
        criado_por="funcionario",
        criado_em=datetime.now(timezone.utc),
    )
    
    db.session.add(evento)
    db.session.commit()
    
    flash("✅ Você concordou com a resposta. Recurso encerrado.", "success")
    return redirect(url_for("main.meus_recursos"))


# ========== ROTA 3: Recorrer Após Devolutiva ==========

@main_bp.route("/meu-recurso/<int:recurso_id>/recorrer-apos-devolutiva", methods=["POST"])
def recorrer_apos_devolutiva(recurso_id):
    """
    Colaborador escolhe recorrer à presidência após a devolutiva.
    
    Valida se ainda está no prazo (prazo do FUNCIONÁRIO).
    """
    from ..models import RecursoAvaliacao, RecursoEvento
    
    recurso = RecursoAvaliacao.query.get_or_404(recurso_id)
    
    # Verificar permissão
    funcionario_id = session.get("funcionario_id")
    if str(recurso.avaliado_id) != str(funcionario_id):
        flash("Você não tem permissão.", "error")
        return redirect(url_for("main.meus_recursos"))
    
    funcionario = recurso.avaliado
    
    # Verificar se tem devolutiva marcada
    if not funcionario.tem_devolutiva_marcada():
        flash("Devolutiva não foi marcada para você.", "error")
        return redirect(url_for("main.meus_recursos"))
    
    # Verificar se ainda está no prazo
    if not funcionario.pode_recorrer_apos_devolutiva():
        flash(
            "❌ O prazo para recorrer expirou. Você pode apenas concordar com a resposta.",
            "error"
        )
        return redirect(url_for("main.ver_devolutiva_recurso", recurso_id=recurso_id))
    
    # Atualizar recurso
    recurso.status = "aguardando_comissao_recurso"
    
    # Registrar evento
    evento = RecursoEvento(
        recurso_id=recurso.id,
        tipo="pedido_recorrer_apos_devolutiva",
        descricao="Funcionário pediu para recorrer à presidência após devolutiva.",
        criado_por="funcionario",
        criado_em=datetime.now(timezone.utc),
    )
    
    db.session.add(evento)
    db.session.commit()
    
    flash(
        "✅ Seu pedido de recorrer foi registrado!\n"
        "Aguardando análise da presidência.",
        "success"
    )
    return redirect(url_for("main.meus_recursos"))
