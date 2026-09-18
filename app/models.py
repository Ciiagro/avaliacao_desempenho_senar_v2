import uuid
from datetime import datetime, date

from sqlalchemy.dialects.postgresql import UUID
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db


class Cargo(db.Model):
    __tablename__ = "cargos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.Text, unique=True, nullable=False)

    funcionarios = db.relationship("Funcionario", back_populates="cargo")
    formulario = db.relationship("Formulario", back_populates="cargo", uselist=False)


class Setor(db.Model):
    __tablename__ = "setores"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.Text, unique=True, nullable=False)

    funcionarios = db.relationship("Funcionario", back_populates="setor")


NIVEIS_HIERARQUICOS = ["Empregado", "Gestor", "Superintendente"]
OPCOES_SEXO = ["Feminino", "Masculino", "Outro"]
DIAS_MINIMOS_PARA_AVALIACAO = 365  # 1 ano de casa


class Funcionario(db.Model):
    __tablename__ = "funcionarios"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text)
    matricula = db.Column(db.Text)
    cpf = db.Column(db.Text, unique=True)
    data_nascimento = db.Column(db.Date)
    data_admissao = db.Column(db.Date)
    data_demissao = db.Column(db.Date)
    sexo = db.Column(db.Text)
    salario = db.Column(db.Numeric(12, 2))
    cargo_id = db.Column(db.Integer, db.ForeignKey("cargos.id"))
    setor_id = db.Column(db.Integer, db.ForeignKey("setores.id"))
    nivel_hierarquico = db.Column(db.Text)
    elegivel_avaliacao = db.Column(db.Boolean)  # None = calcular automaticamente pela data_admissao
    senha_hash = db.Column(db.Text)
    senha_provisoria = db.Column(db.Boolean, nullable=False, default=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    eh_presidencia = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    cargo = db.relationship("Cargo", back_populates="funcionarios")
    setor = db.relationship("Setor", back_populates="funcionarios")

    def __repr__(self):
        return f"<Funcionario {self.nome}>"

    def set_senha(self, senha_texto_plano):
        self.senha_hash = generate_password_hash(senha_texto_plano)

    def checar_senha(self, senha_texto_plano):
        if not self.senha_hash:
            return False
        return check_password_hash(self.senha_hash, senha_texto_plano)

    def dias_de_casa(self, referencia=None):
        if not self.data_admissao:
            return None
        referencia = referencia or datetime.utcnow().date()
        return (referencia - self.data_admissao).days

    def eh_membro_comissao(self):
        return MembroComissao.query.filter_by(funcionario_id=self.id).first() is not None

    def eh_gestor_de_alguem(self):
        return VinculoAvaliacao.query.filter_by(avaliador_id=self.id).first() is not None

    def tempo_de_casa_str(self, referencia=None):
        dias = self.dias_de_casa(referencia)
        if dias is None:
            return "-"
        if dias < 30:
            return f"{dias} dia(s)"
        if dias < 365:
            meses = dias // 30
            return f"{meses} mes(es)"
        anos = dias // 365
        return f"{anos} ano(s)"

    def is_elegivel_avaliacao(self, referencia=None):
        """
        Se elegivel_avaliacao foi definido manualmente (True/False), usa esse valor.
        Caso contrário, calcula com base na data_admissao (>= 1 ano de casa).
        """
        if self.elegivel_avaliacao is not None:
            return self.elegivel_avaliacao
        if not self.data_admissao:
            return None  # sem data cadastrada, não dá para calcular
        dias = self.dias_de_casa(referencia)
        return dias >= DIAS_MINIMOS_PARA_AVALIACAO


class Formulario(db.Model):
    __tablename__ = "formularios"

    id = db.Column(db.Integer, primary_key=True)
    nivel_hierarquico = db.Column(db.Text, unique=True, nullable=False)
    cargo_id = db.Column(db.Integer, db.ForeignKey("cargos.id"))  # legado, não usado mais para escolher o formulário
    nome = db.Column(db.Text, nullable=False)

    cargo = db.relationship("Cargo", back_populates="formulario")
    fatores = db.relationship(
        "Fator", back_populates="formulario", order_by="Fator.ordem"
    )


class Fator(db.Model):
    __tablename__ = "fatores"

    id = db.Column(db.Integer, primary_key=True)
    formulario_id = db.Column(db.Integer, db.ForeignKey("formularios.id"), nullable=False)
    ordem = db.Column(db.Integer, nullable=False)
    nome = db.Column(db.Text, nullable=False)
    descricao = db.Column(db.Text)

    formulario = db.relationship("Formulario", back_populates="fatores")


class CicloAvaliacao(db.Model):
    __tablename__ = "ciclos_avaliacao"

    id = db.Column(db.Integer, primary_key=True)
    exercicio = db.Column(db.Integer, unique=True, nullable=False)
    data_inicio = db.Column(db.Date)
    data_fim = db.Column(db.Date)
    data_limite_autoavaliacao = db.Column(db.Date)
    data_limite_gestor = db.Column(db.Date)
    status = db.Column(db.Text, nullable=False, default="aberto")
    # Quando existe mais de um ciclo com status "aberto" ao mesmo tempo (ex:
    # o ciclo do ano anterior ainda em avaliação e o do ano corrente já
    # criado), este campo diz qual deles deve ser considerado o padrão nas
    # telas que não pedem pro usuário escolher o ciclo explicitamente.
    # Só um ciclo por vez deve ter padrao=True (isso é garantido na rota
    # que define o padrão, não por constraint no banco).
    padrao = db.Column(db.Boolean, nullable=False, default=False, server_default="false")

    def referencia_elegibilidade(self):
        """Data a usar como 'hoje' pra calcular elegibilidade (1 ano de
        casa) de um funcionário PARA ESTE ciclo — nunca a data atual, senão
        um ciclo de anos passados (ex: 2025) ficaria calculando elegibilidade
        com base em quanto tempo a pessoa tem de casa HOJE, e não em quanto
        tempo ela tinha de casa durante o próprio ciclo."""
        return self.data_fim or date(self.exercicio, 12, 31)


class VinculoAvaliacao(db.Model):
    __tablename__ = "vinculos_avaliacao"

    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("ciclos_avaliacao.id"), nullable=False)
    avaliado_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    avaliador_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)

    avaliado = db.relationship("Funcionario", foreign_keys=[avaliado_id])
    avaliador = db.relationship("Funcionario", foreign_keys=[avaliador_id])


class Avaliacao(db.Model):
    __tablename__ = "avaliacoes"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("ciclos_avaliacao.id"), nullable=False)
    avaliado_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    avaliador_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    tipo = db.Column(db.Text, nullable=False)  # 'auto' | 'gestor'
    formulario_id = db.Column(db.Integer, db.ForeignKey("formularios.id"), nullable=False)
    status = db.Column(db.Text, nullable=False, default="em_andamento")

    pontos_fortes = db.Column(db.Text)
    oportunidades_desenvolvimento = db.Column(db.Text)
    plano_acao = db.Column(db.Text)
    plano_prazo = db.Column(db.Text)
    resultados_alcancados = db.Column(db.Text)

    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    atualizado_em = db.Column(
        db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Assinatura eletrônica (registrada quando a avaliação é concluída)
    assinado_por = db.Column(db.Text)
    assinado_em = db.Column(db.DateTime(timezone=True))

    avaliado = db.relationship("Funcionario", foreign_keys=[avaliado_id])
    avaliador = db.relationship("Funcionario", foreign_keys=[avaliador_id])
    formulario = db.relationship("Formulario")
    respostas = db.relationship(
        "RespostaFator", back_populates="avaliacao", cascade="all, delete-orphan"
    )


class RespostaFator(db.Model):
    __tablename__ = "respostas_fatores"

    id = db.Column(db.Integer, primary_key=True)
    avaliacao_id = db.Column(UUID(as_uuid=True), db.ForeignKey("avaliacoes.id"), nullable=False)
    fator_id = db.Column(db.Integer, db.ForeignKey("fatores.id"), nullable=False)
    pontuacao = db.Column(db.Integer, nullable=False)

    avaliacao = db.relationship("Avaliacao", back_populates="respostas")
    fator = db.relationship("Fator")


class NotificacaoPrazo(db.Model):
    """Registro de um lembrete de prazo (5 dias / 2 dias / no dia) já
    enviado por e-mail para um avaliador, num ciclo e tipo específicos —
    evita mandar o mesmo lembrete de novo se a rotina rodar mais de uma
    vez no mesmo dia."""

    __tablename__ = "notificacoes_prazo"

    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("ciclos_avaliacao.id"), nullable=False)
    tipo = db.Column(db.Text, nullable=False)  # 'auto' | 'gestor' | 'ciencia_resultado'
    avaliador_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    dias_restantes = db.Column(db.Integer, nullable=False)  # 5, 2 ou 0
    enviado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)


# Pesos do resultado final (sem comissão, por enquanto): Auto 30% + Gestor 70%.
PESO_AUTO = 0.30
PESO_GESTOR = 0.70


class ResultadoFinal(db.Model):
    """
    Guarda, por ciclo + avaliado, se o resultado final (autoavaliação x0,30 +
    avaliação do gestor x0,70) já foi liberado para o próprio empregado ver.
    A nota em si não é duplicada aqui — é sempre calculada a partir das
    Avaliacoes (auto/gestor) concluídas; esta tabela só controla a liberação.
    """

    __tablename__ = "resultados_finais"

    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("ciclos_avaliacao.id"), nullable=False)
    avaliado_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    liberado = db.Column(db.Boolean, nullable=False, default=False)
    liberado_em = db.Column(db.DateTime(timezone=True))
    liberado_por = db.Column(db.Text)

    # Ciência do avaliado: marcada por ele mesmo, confirmando que recebeu
    # o resultado final. Fica registrada (com data/hora) e é impressa no PDF.
    ciente_avaliado = db.Column(db.Boolean, nullable=False, default=False)
    ciente_em = db.Column(db.DateTime(timezone=True))
    # 'aceito' (satisfeito, encerra) ou 'recorreu' (abriu recurso).
    decisao_avaliado = db.Column(db.Text)

    avaliado = db.relationship("Funcionario", foreign_keys=[avaliado_id])

    __table_args__ = (
        db.UniqueConstraint("ciclo_id", "avaliado_id", name="uq_resultado_final_ciclo_avaliado"),
    )


class MembroComissao(db.Model):
    """Grupo fixo de pessoas que compõem a Comissão de Recursos. O mesmo
    grupo vale para qualquer recurso aberto por qualquer empregado."""

    __tablename__ = "comissao_membros"

    id = db.Column(db.Integer, primary_key=True)
    funcionario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False, unique=True)

    funcionario = db.relationship("Funcionario", foreign_keys=[funcionario_id])


# Status possíveis de um RecursoAvaliacao, em ordem do fluxo:
RECURSO_STATUS_AGUARDANDO_COMISSAO_INICIAL = "aguardando_comissao_inicial"
RECURSO_STATUS_AGUARDANDO_GESTOR = "aguardando_gestor"
RECURSO_STATUS_AGUARDANDO_COMISSAO_REPASSE = "aguardando_comissao_repasse"
RECURSO_STATUS_AGUARDANDO_FUNCIONARIO = "aguardando_funcionario"
RECURSO_STATUS_AGUARDANDO_COMISSAO_FECHAMENTO = "aguardando_comissao_fechamento"
RECURSO_STATUS_AGUARDANDO_COMISSAO_RECURSO = "aguardando_comissao_recurso"
RECURSO_STATUS_AGUARDANDO_PRESIDENCIA = "aguardando_presidencia"
RECURSO_STATUS_ENCERRADO = "encerrado"


class RecursoAvaliacao(db.Model):
    """Um pedido de recurso aberto pelo próprio empregado quando ele não
    concorda com o resultado final liberado. Segue um fluxo: Comissão
    encaminha pro gestor -> gestor revê -> (se mantido e o empregado ainda
    não concordar) Comissão encaminha pra presidência -> presidência
    decide."""

    __tablename__ = "recursos_avaliacao"

    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("ciclos_avaliacao.id"), nullable=False)
    avaliado_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    status = db.Column(db.Text, nullable=False, default=RECURSO_STATUS_AGUARDANDO_GESTOR)
    resultado_final_em_texto = db.Column(db.Text)
    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    ciente_funcionario = db.Column(db.Boolean, nullable=False, default=False)
    ciente_funcionario_em = db.Column(db.DateTime(timezone=True))

    ciclo = db.relationship("CicloAvaliacao")
    avaliado = db.relationship("Funcionario", foreign_keys=[avaliado_id])
    eventos = db.relationship(
        "RecursoEvento", back_populates="recurso", order_by="RecursoEvento.criado_em"
    )
    revisoes_notas = db.relationship(
        "RecursoRevisaoNota", order_by="RecursoRevisaoNota.criado_em"
    )
    itens_contestados = db.relationship(
        "RecursoItemContestado", order_by="RecursoItemContestado.id"
    )

    @property
    def itens_contestados_por_fator(self):
        """{fator_id: motivo} -- pra usar direto no template e destacar a
        linha do fator na tabela de notas."""
        return {item.fator_id: item.motivo for item in self.itens_contestados}


class RecursoItemContestado(db.Model):
    """Um fator específico que o empregado contestou ao abrir o recurso,
    com o motivo daquele item. Complementa o campo `motivo` (texto livre)
    de RecursoAvaliacao, permitindo destacar cada item direto na tabela de
    notas em vez de um bloco de texto solto."""

    __tablename__ = "recurso_itens_contestados"

    id = db.Column(db.Integer, primary_key=True)
    recurso_id = db.Column(db.Integer, db.ForeignKey("recursos_avaliacao.id"), nullable=False)
    fator_id = db.Column(db.Integer, db.ForeignKey("fatores.id"), nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    fator = db.relationship("Fator")


class RecursoEvento(db.Model):
    """Linha do tempo de um recurso: abertura, resposta do gestor,
    encaminhamento da comissão pra presidência, decisão da presidência."""

    __tablename__ = "recurso_eventos"

    id = db.Column(db.Integer, primary_key=True)
    recurso_id = db.Column(db.Integer, db.ForeignKey("recursos_avaliacao.id"), nullable=False)
    tipo = db.Column(db.Text, nullable=False)  # abertura / resposta_gestor / encaminhamento_comissao / decisao_presidencia / aceite_funcionario
    autor_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"))
    decisao = db.Column(db.Text)  # manteve / revisou / acatado / nao_acatado (conforme o tipo)
    texto = db.Column(db.Text)
    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    recurso = db.relationship("RecursoAvaliacao", back_populates="eventos")
    autor = db.relationship("Funcionario", foreign_keys=[autor_id])


class RecursoRevisaoNota(db.Model):
    """Histórico de mudança de nota feita através de um recurso (pelo
    gestor ou pela presidência) — guarda o valor antigo e o novo, pra nunca
    perder o rastro do que foi alterado."""

    __tablename__ = "recurso_revisoes_notas"

    id = db.Column(db.Integer, primary_key=True)
    recurso_id = db.Column(db.Integer, db.ForeignKey("recursos_avaliacao.id"), nullable=False)
    fator_id = db.Column(db.Integer, db.ForeignKey("fatores.id"), nullable=False)
    nota_anterior = db.Column(db.Integer)
    nota_nova = db.Column(db.Integer, nullable=False)
    alterado_por_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    fator = db.relationship("Fator")
    alterado_por = db.relationship("Funcionario", foreign_keys=[alterado_por_id])


# ---------------------------------------------------------------
# Progressão de nível (nota/conceito de exercícios pré-sistema + regra do
# "par de anos" para decidir quem pode subir de nivel_hierarquico)
# ---------------------------------------------------------------
class HistoricoPreSistema(db.Model):
    """Nota de um exercício anterior à existência do sistema (hoje: 2023 e
    2024), importada por planilha. Para exercícios já rodados dentro do
    sistema, a nota nunca fica guardada aqui — é sempre calculada na hora a
    partir de Avaliacao, igual acontece em ResultadoFinal."""

    __tablename__ = "historico_pre_sistema"

    id = db.Column(db.Integer, primary_key=True)
    funcionario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    exercicio = db.Column(db.Integer, nullable=False)
    nota = db.Column(db.Numeric(4, 2), nullable=False)
    origem = db.Column(db.Text, nullable=False, default="importado")
    criado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    funcionario = db.relationship("Funcionario")

    __table_args__ = (db.UniqueConstraint("funcionario_id", "exercicio"),)


class ProgressaoPontoPartida(db.Model):
    """O 'ponteiro': a partir de qual exercício o par de progressão de cada
    funcionário conta. Para o histórico pré-sistema vem da planilha (só o
    RH sabe o que já foi usado antes do sistema existir); a partir daí, o
    próprio sistema mantém esse ponteiro andando."""

    __tablename__ = "progressao_ponto_partida"

    funcionario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), primary_key=True)
    exercicio_inicio = db.Column(db.Integer)  # None = ainda não determinado (precisa confirmação do RH)
    precisa_confirmacao = db.Column(db.Boolean, nullable=False, default=False)
    excluido_progressao = db.Column(db.Boolean, nullable=False, default=False)
    observacao = db.Column(db.Text)
    atualizado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    atualizado_por = db.Column(db.Text)

    funcionario = db.relationship("Funcionario")


TIPOS_EVENTO_FUNCIONARIO = ["mudanca_funcao"]


class EventoFuncionario(db.Model):
    """Evento que reinicia/adia a contagem do par de progressão (ex.:
    mudança de função). Guardado para auditoria e para o cálculo do par."""

    __tablename__ = "eventos_funcionario"

    id = db.Column(db.Integer, primary_key=True)
    funcionario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    tipo = db.Column(db.Text, nullable=False)
    exercicio = db.Column(db.Integer, nullable=False)
    observacao = db.Column(db.Text)
    registrado_por = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    funcionario = db.relationship("Funcionario")


class Progressao(db.Model):
    """Progressão de nível_hierarquico efetivada (Fase 1: sempre por clique
    manual da administração, guardado aqui para auditoria)."""

    __tablename__ = "progressoes"

    id = db.Column(db.Integer, primary_key=True)
    funcionario_id = db.Column(UUID(as_uuid=True), db.ForeignKey("funcionarios.id"), nullable=False)
    exercicio_inicio = db.Column(db.Integer, nullable=False)
    exercicio_fim = db.Column(db.Integer, nullable=False)
    efetivada_em_exercicio = db.Column(db.Integer, nullable=False)
    nivel_anterior = db.Column(db.Text)
    nivel_novo = db.Column(db.Text)
    subiu = db.Column(db.Boolean)
    decidido_por = db.Column(db.Text)
    decidido_em = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    funcionario = db.relationship("Funcionario")
