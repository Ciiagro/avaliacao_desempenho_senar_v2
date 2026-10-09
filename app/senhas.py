"""
Regras de senha do sistema: senha provisória aleatória, validação de senha
nova, bloqueio por tentativas erradas e links de "esqueci minha senha".
"""

import hashlib
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from .extensions import db
from .models import Funcionario, RedefinicaoSenha

SENHA_MINIMO_CARACTERES = 8

# Login: depois de N erros seguidos, a conta fica bloqueada por um tempo.
MAX_TENTATIVAS_LOGIN = 5
BLOQUEIO_MINUTOS = 15

# Link de "esqueci minha senha"
TOKEN_VALIDADE_MINUTOS = 30
# Evita que alguém use o formulário para lotar a caixa de e-mail de outra
# pessoa: no máximo 1 link novo a cada N segundos por colaborador.
TOKEN_INTERVALO_SEGUNDOS = 60

# Sem 0/O, 1/l/I e outros caracteres que se confundem quando a senha é lida.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"

_SENHAS_COMUNS = {
    "12345678", "123456789", "1234567890", "87654321", "11111111", "00000000",
    "senha123", "senha1234", "mudar123", "mudar@123", "senar123", "senar@123",
    "abc12345", "qwerty123", "password", "password1", "123mudar", "admin123",
    "brasil123", "12341234", "senha@123", "senar2024", "senar2025", "senar2026",
}


def agora():
    return datetime.now(timezone.utc)


def _como_utc(valor):
    """Bancos como o SQLite devolvem datas sem fuso; o Postgres devolve com."""
    if valor is None:
        return None
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


# ---------------------------------------------------------------------------
# Senha provisória
# ---------------------------------------------------------------------------
def gerar_senha_temporaria():
    """Senha aleatória, diferente para cada pessoa. Ex.: 'K7mQ-p3xW-dR9t'."""
    grupos = ["".join(secrets.choice(_ALFABETO) for _ in range(4)) for _ in range(3)]
    return "-".join(grupos)


# ---------------------------------------------------------------------------
# Validação de senha nova
# ---------------------------------------------------------------------------
def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def validar_senha_nova(senha, funcionario=None):
    """Devolve uma mensagem de erro (str) ou None se a senha é aceitável."""
    if len(senha) < SENHA_MINIMO_CARACTERES:
        return f"A nova senha precisa ter pelo menos {SENHA_MINIMO_CARACTERES} caracteres."
    normalizada = _normalizar(senha)
    if normalizada in _SENHAS_COMUNS or len(set(normalizada)) <= 2:
        return "Essa senha é fácil demais de adivinhar. Escolha outra."
    if funcionario is not None:
        email = _normalizar((funcionario.email or "").strip())
        parte_email = email.split("@")[0]
        if normalizada == email or (parte_email and normalizada == parte_email):
            return "A senha não pode ser igual ao seu e-mail."
        nome = _normalizar(funcionario.nome or "").replace(" ", "")
        if nome and normalizada.replace(" ", "") == nome:
            return "A senha não pode ser o seu nome."
    return None


# ---------------------------------------------------------------------------
# Bloqueio por tentativas erradas
# ---------------------------------------------------------------------------
def minutos_de_bloqueio_restantes(funcionario):
    """0 se a conta não está bloqueada; senão, quantos minutos faltam."""
    ate = _como_utc(funcionario.bloqueado_ate)
    if not ate or ate <= agora():
        return 0
    return max(1, int((ate - agora()).total_seconds() // 60) + 1)


def registrar_login_errado(funcionario):
    """Soma 1 erro; no 5º seguido bloqueia a conta. Não dá commit."""
    ate = _como_utc(funcionario.bloqueado_ate)
    if ate and ate <= agora():
        # bloqueio antigo já venceu: começa a contar de novo
        funcionario.tentativas_login = 0
        funcionario.bloqueado_ate = None
    funcionario.tentativas_login = (funcionario.tentativas_login or 0) + 1
    if funcionario.tentativas_login >= MAX_TENTATIVAS_LOGIN:
        funcionario.bloqueado_ate = agora() + timedelta(minutes=BLOQUEIO_MINUTOS)
        funcionario.tentativas_login = 0


def limpar_tentativas_login(funcionario):
    funcionario.tentativas_login = 0
    funcionario.bloqueado_ate = None


# ---------------------------------------------------------------------------
# Link de "esqueci minha senha"
# ---------------------------------------------------------------------------
def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def criar_token_redefinicao(funcionario):
    """Cria um link novo e devolve o token (texto puro, só para o e-mail).

    Devolve None se já foi pedido um link há pouco tempo para essa pessoa.
    Não dá commit.
    """
    recente = (
        RedefinicaoSenha.query.filter(
            RedefinicaoSenha.funcionario_id == funcionario.id,
            RedefinicaoSenha.criado_em > agora() - timedelta(seconds=TOKEN_INTERVALO_SEGUNDOS),
        ).first()
    )
    if recente:
        return None
    # Um link novo invalida os anteriores ainda pendentes.
    invalidar_tokens_pendentes(funcionario)
    token = secrets.token_urlsafe(32)
    db.session.add(
        RedefinicaoSenha(
            funcionario_id=funcionario.id,
            token_hash=_hash_token(token),
            expira_em=agora() + timedelta(minutes=TOKEN_VALIDADE_MINUTOS),
        )
    )
    return token


def buscar_token_valido(token):
    """Devolve a RedefinicaoSenha válida (não usada, não vencida) ou None."""
    if not token:
        return None
    registro = RedefinicaoSenha.query.filter_by(token_hash=_hash_token(token)).first()
    if not registro or registro.usado_em is not None:
        return None
    if _como_utc(registro.expira_em) <= agora():
        return None
    return registro


def consumir_token(token):
    """Gasta o link de forma atômica: só UMA requisição consegue.

    Se a pessoa clicar duas vezes em "Salvar" (ou duas abas enviarem ao mesmo
    tempo), só a primeira recebe o registro; a outra recebe None. Assim a
    senha é trocada e o e-mail de aviso é enviado uma única vez.
    Não dá commit — faça junto com a troca da senha.
    """
    if not token:
        return None
    resultado = db.session.execute(
        db.update(RedefinicaoSenha)
        .where(
            RedefinicaoSenha.token_hash == _hash_token(token),
            RedefinicaoSenha.usado_em.is_(None),
            RedefinicaoSenha.expira_em > agora(),
        )
        .values(usado_em=agora())
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        return None
    return RedefinicaoSenha.query.filter_by(token_hash=_hash_token(token)).first()


def invalidar_tokens_pendentes(funcionario):
    """Marca como usados todos os links ainda pendentes. Não dá commit."""
    pendentes = RedefinicaoSenha.query.filter(
        RedefinicaoSenha.funcionario_id == funcionario.id,
        RedefinicaoSenha.usado_em.is_(None),
    ).all()
    for p in pendentes:
        p.usado_em = agora()


def buscar_funcionario_ativo_por_email(email):
    email = (email or "").strip().lower()
    if not email:
        return None
    return Funcionario.query.filter(
        db.func.lower(db.func.trim(Funcionario.email)) == email,
        Funcionario.ativo.is_(True),
    ).first()
