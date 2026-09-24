# =====================================================================
# ADICIONAR AO MODELS.PY - Classe Devolutiva por Funcionário
# =====================================================================

from datetime import date, timedelta

# Adicione esta classe DEPOIS da classe Funcionario:

class DevolutivaPorFuncionario(db.Model):
    """
    Data de devolutiva para cada funcionário.
    Todos os recursos abertos deste funcionário usam esta data.
    
    Exemplo:
        João = data_devolutiva 28/09/2024
        Todos os 5 recursos de João usam 28/09/2024
    """
    
    __tablename__ = "devolutiva_funcionario"
    
    id = db.Column(db.Integer, primary_key=True)
    funcionario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False, unique=True)
    data_devolutiva = db.Column(db.Date, nullable=False)
    data_limite_recorrer = db.Column(db.Date, nullable=False)
    marcado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    marcado_por = db.Column(db.String(255))
    
    funcionario = db.relationship("Funcionario", foreign_keys=[funcionario_id])
    
    def pode_recorrer(self):
        """Verifica se o funcionário ainda pode recorrer."""
        if not self.data_limite_recorrer:
            return False
        
        hoje = date.today()
        return hoje <= self.data_limite_recorrer
    
    def dias_restantes(self):
        """Calcula quantos dias faltam para expirar o prazo."""
        if not self.data_limite_recorrer:
            return None
        
        hoje = date.today()
        delta = (self.data_limite_recorrer - hoje).days
        
        return max(0, delta)


# =====================================================================
# MODIFICAR CLASSE Funcionario - Adicione este método:
# =====================================================================

class Funcionario(db.Model):
    # ... campos existentes ...
    
    # Adicione esta relação:
    devolutiva = db.relationship(
        "DevolutivaPorFuncionario",
        uselist=False,
        foreign_keys="DevolutivaPorFuncionario.funcionario_id"
    )
    
    def tem_devolutiva_marcada(self):
        """Verifica se este funcionário tem devolutiva marcada."""
        return self.devolutiva is not None
    
    def pode_recorrer_apos_devolutiva(self):
        """Verifica se este funcionário ainda pode recorrer."""
        if not self.devolutiva:
            return False
        
        return self.devolutiva.pode_recorrer()
    
    def dias_restantes_recorrer(self):
        """Calcula quantos dias faltam para expirar o prazo deste funcionário."""
        if not self.devolutiva:
            return None
        
        return self.devolutiva.dias_restantes()


# =====================================================================
# MODIFICAR CLASSE RecursoAvaliacao - Remova:
# =====================================================================

# REMOVA ESTES CAMPOS (eles estavam errados):
#   - data_devolutiva
#   - data_limite_recorrer_apos_devolutiva
#   - devolutiva_repassada_em
#   - método pode_recorrer_apos_devolutiva()
#   - método dias_restantes_recorrer()

# ADICIONE ESTE MÉTODO:
    @property
    def pode_recorrer_apos_devolutiva(self):
        """
        Verifica se o funcionário proprietário deste recurso
        ainda pode recorrer.
        Busca a data de devolutiva do FUNCIONÁRIO, não do recurso.
        """
        funcionario = self.avaliado
        if not funcionario:
            return False
        
        return funcionario.pode_recorrer_apos_devolutiva()
    
    @property
    def data_devolutiva(self):
        """Data de devolutiva do funcionário."""
        if self.avaliado and self.avaliado.devolutiva:
            return self.avaliado.devolutiva.data_devolutiva
        return None
    
    @property
    def data_limite_recorrer_apos_devolutiva(self):
        """Data limite de recorrer do funcionário."""
        if self.avaliado and self.avaliado.devolutiva:
            return self.avaliado.devolutiva.data_limite_recorrer
        return None
    
    @property
    def dias_restantes_recorrer(self):
        """Dias restantes para recorrer do funcionário."""
        if self.avaliado:
            return self.avaliado.dias_restantes_recorrer()
        return None
