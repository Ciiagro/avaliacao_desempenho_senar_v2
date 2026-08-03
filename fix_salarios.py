"""
Script de correção única para salários que ficaram sem a vírgula decimal
(ex: 249431 quando o correto era 2494,31; ou 2494310000 quando o correto
era 2494,31 com dois zeros extras).

Como usar:
    1. Rode primeiro em modo de conferência (não altera nada no banco):
         python fix_salarios.py

    2. Revise a lista impressa. Se estiver tudo certo, rode de novo
       confirmando a gravação:
         python fix_salarios.py --aplicar

Coloque este arquivo na raiz do projeto (mesmo nível do run.py) antes
de rodar, pois ele usa o mesmo app/config/banco já configurado no seu
.env.
"""
import sys

from app import create_app
from app.extensions import db
from app.models import Funcionario
from app.utils import SALARIO_SUSPEITO_LIMITE, formatar_moeda_br


def corrigir(valor):
    """Mesma lógica usada em app/utils.py:parse_salario, mas partindo
    de um valor Decimal/float já salvo no banco."""
    valor = float(valor)
    while valor == int(valor) and abs(valor) > SALARIO_SUSPEITO_LIMITE:
        valor = valor / 100
    return valor


def main():
    aplicar = "--aplicar" in sys.argv

    app = create_app()
    with app.app_context():
        funcionarios = (
            Funcionario.query.filter(Funcionario.salario.isnot(None))
            .order_by(Funcionario.nome)
            .all()
        )

        alterados = []
        for f in funcionarios:
            valor_atual = float(f.salario)
            valor_corrigido = corrigir(valor_atual)
            if abs(valor_corrigido - valor_atual) > 0.001:
                alterados.append((f, valor_atual, valor_corrigido))

        if not alterados:
            print("Nenhum salário suspeito encontrado. Nada para corrigir.")
            return

        print(f"{len(alterados)} salário(s) serão corrigidos:\n")
        for f, antes, depois in alterados:
            antes_fmt = formatar_moeda_br(antes)
            depois_fmt = formatar_moeda_br(depois)
            print(f"  {f.nome:<45} R$ {antes_fmt:>15}  ->  R$ {depois_fmt:>12}")

        if not aplicar:
            print(
                "\nNenhuma alteração foi gravada (modo de conferência).\n"
                "Revise a lista acima e, se estiver correta, rode:\n"
                "    python fix_salarios.py --aplicar"
            )
            return

        for f, _, depois in alterados:
            f.salario = depois
        db.session.commit()
        print(f"\n{len(alterados)} salário(s) corrigido(s) e gravado(s) no banco.")


if __name__ == "__main__":
    main()
