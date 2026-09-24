# =====================================================================
# ADICIONAR A admin.py - ROTAS PARA DEVOLUTIVA POR FUNCIONÁRIO
# =====================================================================

from datetime import datetime, timezone, timedelta

# ========== ROTA 1: Listar Funcionários para Marcar Devolutiva ==========

@admin_bp.route("/devolutiva/funcionarios", methods=["GET"])
def listar_funcionarios_devolutiva():
    """
    Página que lista todos os funcionários para admin marcar devolutiva.
    """
    from ..models import Funcionario, DevolutivaPorFuncionario
    
    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    
    # Adicionar informação de devolutiva de cada um
    lista = []
    for func in funcionarios:
        info = {
            "id": str(func.id),
            "nome": func.nome,
            "email": func.email,
            "data_devolutiva": func.devolutiva.data_devolutiva if func.devolutiva else None,
            "data_limite": func.devolutiva.data_limite_recorrer if func.devolutiva else None,
            "tem_devolutiva": func.tem_devolutiva_marcada()
        }
        lista.append(info)
    
    return render_template(
        "admin/devolutiva_funcionarios.html",
        funcionarios=lista
    )


# ========== ROTA 2: Marcar Devolutiva para UM Funcionário ==========

@admin_bp.route("/devolutiva/funcionario/<funcionario_id>/marcar", methods=["POST"])
def marcar_devolutiva_funcionario(funcionario_id):
    """
    Admin marca data de devolutiva para UM funcionário específico.
    
    Todos os recursos abertos deste funcionário usarão essa data.
    
    Exemplo:
        POST /devolutiva/funcionario/uuid-joao/marcar
        data_devolutiva: 2024-09-28
        
        → Todos os recursos de João usam 28/09/2024
    """
    from ..models import Funcionario, DevolutivaPorFuncionario
    
    try:
        funcionario = Funcionario.query.get_or_404(funcionario_id)
    except:
        flash("Funcionário não encontrado.", "error")
        return redirect(request.referrer or url_for("admin.index"))
    
    # Obter data do formulário
    data_devolutiva_str = request.form.get("data_devolutiva")
    if not data_devolutiva_str:
        flash("Data de devolutiva é obrigatória.", "error")
        return redirect(request.referrer or url_for("admin.listar_funcionarios_devolutiva"))
    
    try:
        data_devolutiva = datetime.strptime(data_devolutiva_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Formato de data inválido. Use YYYY-MM-DD.", "error")
        return redirect(request.referrer or url_for("admin.listar_funcionarios_devolutiva"))
    
    # Calcular data limite (data_devolutiva + 5 dias)
    data_limite = data_devolutiva + timedelta(days=5)
    
    # Verificar se já existe devolutiva marcada para este funcionário
    devolutiva = DevolutivaPorFuncionario.query.filter_by(funcionario_id=funcionario_id).first()
    
    if devolutiva:
        # Atualizar devolutiva existente
        devolutiva.data_devolutiva = data_devolutiva
        devolutiva.data_limite_recorrer = data_limite
        devolutiva.marcado_em = datetime.now(timezone.utc)
        devolutiva.marcado_por = session.get("email", "admin")
        
        acao = "Atualizada"
    else:
        # Criar nova devolutiva
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
    
    flash(
        f"✅ Devolutiva {acao} para {funcionario.nome}!\n"
        f"Data: {data_devolutiva.strftime('%d/%m/%Y')}\n"
        f"Prazo para recorrer: até {data_limite.strftime('%d/%m/%Y')}",
        "success"
    )
    
    return redirect(url_for("admin.listar_funcionarios_devolutiva"))


# ========== ROTA 3: Remover Devolutiva de UM Funcionário ==========

@admin_bp.route("/devolutiva/funcionario/<funcionario_id>/remover", methods=["POST"])
def remover_devolutiva_funcionario(funcionario_id):
    """
    Admin remove a devolutiva marcada para um funcionário.
    """
    from ..models import Funcionario, DevolutivaPorFuncionario
    
    try:
        funcionario = Funcionario.query.get_or_404(funcionario_id)
    except:
        flash("Funcionário não encontrado.", "error")
        return redirect(request.referrer or url_for("admin.index"))
    
    devolutiva = DevolutivaPorFuncionario.query.filter_by(funcionario_id=funcionario_id).first()
    
    if devolutiva:
        db.session.delete(devolutiva)
        db.session.commit()
        flash(f"Devolutiva de {funcionario.nome} removida.", "success")
    else:
        flash(f"{funcionario.nome} não tem devolutiva marcada.", "info")
    
    return redirect(url_for("admin.listar_funcionarios_devolutiva"))
