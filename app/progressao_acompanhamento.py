"""
Acompanhamento de progressão de nível POR PAR de anos.

Para um "ano da progressão" Y (o ano em que a progressão vale), o par
considerado é (Y-2, Y-1). Exemplo: Y=2025 -> par 2023-2024.

Só LÊ dados (nunca grava nada). Usa as mesmas consultas em lote da tela
de Progressão de Nível (carregar_dados_progressao) para não criar N+1.
"""

from collections import defaultdict

from .models import Funcionario, Progressao
from .progressao_service import carregar_dados_progressao, notas_detalhadas_do_funcionario
from .utils import conceito_resultado

GRUPOS = [
    # chave, título curto, descrição para a legenda, cor (hex) usada no PDF
    ("subiram", "Subiram de nível", "Conceito A nos dois anos do par, com progressão aplicada", "#d5dbe1"),
    ("primeiro_a", "1º conceito A", "Primeiro conceito A no último ano do par (ainda sem progressão)", "#f6d14b"),
    ("a_sem_progressao", "A sem progressão", "Conceito A nos dois anos, mas sem progressão neste par", "#f0e0e0"),
    ("fora_tabela", "Fora da tabela", "Sem progressão por estar em tabela extra faixa", "#c9dcb0"),
]
ORDEM_GRUPOS = [g[0] for g in GRUPOS]


def _conceito(nota):
    return conceito_resultado(nota) if nota is not None else None


def anos_disponiveis(dados=None):
    """Anos de progressão (Y) que têm par completo (Y-2 e Y-1 com nota) ou
    alguma progressão registrada. O mais recente vem por último."""
    dados = dados or carregar_dados_progressao()
    exercicios = set()
    for (exercicio, _fid) in dados["nota_ciclo_funcionario"]:
        exercicios.add(exercicio)
    for porfunc in dados["nota_historico_por_funcionario"].values():
        exercicios.update(porfunc.keys())
    anos = {e + 1 for e in exercicios if (e - 1) in exercicios}
    anos.update(p.efetivada_em_exercicio for p in Progressao.query.all())
    return sorted(anos)


def montar_acompanhamento(ano, dados=None):
    """Devolve {"ano", "par", "grupos": {chave: [linhas]}, "contagem", "total_avaliados"}.

    Cada linha: matricula, nome, admissao, nota_a, nota_b, conceito_a,
    conceito_b, nivel_anterior, nivel_novo, motivo, grupo.
    """
    dados = dados or carregar_dados_progressao()
    a, b = ano - 2, ano - 1

    progressoes = defaultdict(list)
    for p in Progressao.query.all():
        progressoes[p.funcionario_id].append(p)

    funcionarios = Funcionario.query.order_by(Funcionario.nome).all()
    grupos = {chave: [] for chave in ORDEM_GRUPOS}
    total_avaliados = 0
    todos = []

    for f in funcionarios:
        notas = {n["exercicio"]: n["nota"] for n in notas_detalhadas_do_funcionario(f.id, dados)}
        nota_a, nota_b = notas.get(a), notas.get(b)
        prog = next(
            (p for p in progressoes.get(f.id, []) if p.efetivada_em_exercicio == ano or p.exercicio_fim == b),
            None,
        )
        if prog is None and not f.ativo:
            continue
        if nota_a is None and nota_b is None and prog is None:
            continue
        total_avaliados += 1

        conceito_a, conceito_b = _conceito(nota_a), _conceito(nota_b)
        ambos_a = conceito_a == "A" and conceito_b == "A"
        ponteiro = dados["ponteiros_por_funcionario"].get(f.id)
        excluido = bool(ponteiro and ponteiro.excluido_progressao)
        obs = (ponteiro.observacao or "") if ponteiro else ""

        subiu = False
        if prog is not None:
            subiu = prog.subiu if prog.subiu is not None else (prog.nivel_anterior != prog.nivel_novo)

        grupo = None
        motivo = ""
        if subiu:
            grupo = "subiram"
            motivo = "Progressão aplicada em %s" % ano
        elif excluido and "tabela" in obs.lower() and (conceito_a == "A" or conceito_b == "A"):
            grupo = "fora_tabela"
            motivo = obs or "Fora da tabela salarial"
        elif ambos_a:
            grupo = "a_sem_progressao"
            if prog is not None and prog.subiu is False:
                motivo = "Decidido: não sobe neste par"
            elif excluido:
                motivo = obs or "Não se aplica"
            else:
                ultima = dados["ultima_progressao_por_funcionario"].get(f.id)
                if ultima and ultima.exercicio_fim >= a and ultima.efetivada_em_exercicio != ano:
                    motivo = "Anos já usados em progressão de %s" % ultima.efetivada_em_exercicio
                else:
                    motivo = "Sem decisão registrada"
        elif conceito_b == "A" and conceito_a != "A":
            grupo = "primeiro_a"
            motivo = "1º conceito A em %s" % b

        linha = {
            "grupo": grupo,
            "matricula": f.matricula or "",
            "nome": f.nome,
            "admissao": f.data_admissao,
            "nota_a": nota_a,
            "nota_b": nota_b,
            "conceito_a": conceito_a,
            "conceito_b": conceito_b,
            "nivel_anterior": (prog.nivel_anterior if prog else None) or f.nivel_hierarquico,
            "nivel_novo": prog.nivel_novo if (prog and subiu) else None,
            "motivo": motivo,
        }
        if nota_b is not None and f.ativo:
            todos.append(linha)
        if grupo is None:
            continue
        grupos[grupo].append(linha)

    return {
        "ano": ano,
        "par": (a, b),
        "grupos": grupos,
        "contagem": {k: len(v) for k, v in grupos.items()},
        "total_avaliados": total_avaliados,
        "todos": todos,
    }
