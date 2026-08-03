"""
Funções utilitárias compartilhadas pelas rotas e templates.
"""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

# Todos os horários (criado_em, liberado_em, ciente_em, assinado_em etc.)
# são gravados em UTC no banco. Essa é a hora local usada pra EXIBIR pro
# usuário — a empresa fica em Fortaleza/CE (UTC-3, sem horário de verão).
FUSO_FORTALEZA = ZoneInfo("America/Fortaleza")

# Acima deste valor, um salário "redondo" (sem centavos) é considerado
# suspeito — provavelmente o separador decimal se perdeu na hora de
# digitar/importar (ex: "249431" em vez de "2494,31").
SALARIO_SUSPEITO_LIMITE = 50000


def formatar_cpf(cpf):
    """Formata um CPF (armazenado só com dígitos) como 000.000.000-00.

    Se o valor não tiver exatamente 11 dígitos (dado incompleto/errado),
    devolve o valor original sem alterar, para não mascarar um problema
    de cadastro.
    """
    if not cpf:
        return "-"
    digitos = "".join(ch for ch in str(cpf) if ch.isdigit())
    if len(digitos) != 11:
        return cpf
    return f"{digitos[0:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}"


def parse_salario(valor_bruto):
    """Converte um salário digitado/importado (string) para float, aceitando
    tanto o formato brasileiro (1.234,56) quanto o formato simples (1234.56
    ou 1234).

    Também corrige o erro comum de perder a vírgula decimal: se o número
    resultante for "redondo" (sem centavos) e muito alto, assume que na
    verdade faltou o separador decimal e vai dividindo por 100 até o valor
    fazer sentido (ex: 2494310000 -> 249431 -> 2494.31).

    Levanta ValueError se não for possível converter.
    """
    if valor_bruto is None:
        return None

    texto = str(valor_bruto).strip()
    if not texto:
        return None

    texto = texto.replace("R$", "").replace(" ", "")

    if "," in texto:
        # Formato brasileiro: ponto = milhar, vírgula = decimal.
        texto = texto.replace(".", "").replace(",", ".")

    valor = float(texto)

    # Corrige o caso em que o separador decimal foi perdido (ex.: import
    # de planilha com o valor "249431" para o que deveria ser "2494,31").
    while valor == int(valor) and abs(valor) > SALARIO_SUSPEITO_LIMITE:
        valor = valor / 100

    return valor


def formatar_moeda_br(valor):
    """Formata um número como moeda no padrão brasileiro: 2.494,31
    (ponto como separador de milhar, vírgula como separador decimal)."""
    texto = f"{valor:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def media_avaliacao(avaliacao):
    """Média dos pontos dos fatores de uma Avaliacao (auto ou gestor).
    Retorna None se a avaliação não existir, não estiver concluída, ou não
    tiver respostas salvas."""
    if not avaliacao or avaliacao.status != "concluida" or not avaliacao.respostas:
        return None
    pontuacoes = [r.pontuacao for r in avaliacao.respostas]
    return sum(pontuacoes) / len(pontuacoes)


def calcular_resultado_final(media_auto, media_gestor, peso_auto=0.30, peso_gestor=0.70):
    """Resultado final ponderado (sem comissão, por enquanto): auto x0,30 +
    gestor x0,70. Retorna None se alguma das duas médias faltar."""
    if media_auto is None or media_gestor is None:
        return None
    return media_auto * peso_auto + media_gestor * peso_gestor


def conceito_resultado(resultado_final):
    """Converte a nota final (0 a 10) na letra do conceito, seguindo a
    mesma régua da planilha: A entre 8,0 e 10,0 · B entre 7,0 e 7,9 · C
    abaixo de 7,0."""
    if resultado_final is None:
        return None
    if resultado_final >= 8.0:
        return "A"
    if resultado_final >= 7.0:
        return "B"
    return "C"


def para_fortaleza(data_utc):
    """Converte um datetime salvo em UTC (naive ou aware) pro horário de
    Fortaleza/CE. Devolve um datetime (sem formatar) pra usar com
    .strftime(...) depois, tanto em templates quanto em código Python."""
    if data_utc is None:
        return None
    if data_utc.tzinfo is None:
        data_utc = data_utc.replace(tzinfo=timezone.utc)
    return data_utc.astimezone(FUSO_FORTALEZA)


def formatar_data_local(data_utc, com_hora=True):
    """Converte um datetime UTC pro horário de Fortaleza/CE e já formata
    como dd/mm/aaaa (ou dd/mm/aaaa às HH:MM, se com_hora=True)."""
    data_local = para_fortaleza(data_utc)
    if data_local is None:
        return ""
    if com_hora:
        return data_local.strftime("%d/%m/%Y às %H:%M")
    return data_local.strftime("%d/%m/%Y")


def adicionar_dias_uteis(data_inicio, dias_uteis):
    """Soma dias úteis (pula sábado e domingo) a uma data/datetime.

    Não desconta feriados — não há uma tabela de feriados cadastrada no
    sistema ainda. Se isso for necessário no futuro, é só cruzar aqui com
    uma tabela de feriados.
    """
    if data_inicio is None:
        return None
    data = data_inicio
    dias_somados = 0
    while dias_somados < dias_uteis:
        data += timedelta(days=1)
        if data.weekday() < 5:  # 0=segunda ... 4=sexta
            dias_somados += 1
    return data
