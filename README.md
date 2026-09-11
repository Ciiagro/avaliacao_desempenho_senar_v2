# Sistema de Avaliação de Desempenho (Flask + Supabase)

Sistema interno para conduzir o ciclo anual de avaliação de desempenho:
autoavaliação do empregado + avaliação do gestor imediato, com formulários
diferentes por cargo (Empregado, Gestor, Superintendente), fiel ao modelo
usado atualmente em papel/Word.

## Como funciona o fluxo

1. O RH cria o **ciclo de avaliação** do exercício (ex: 2026).
2. O RH cadastra os **funcionários** (nome + cargo) e os **vínculos**
   (quem avalia quem naquele ciclo) — manualmente ou importando uma planilha.
3. Cada **gestor** entra no sistema, seleciona seu nome e vê a lista dos
   empregados que ele avalia, com o status de cada avaliação.
4. Cada **empregado** entra no sistema, seleciona seu nome e preenche a
   **autoavaliação** (usa o mesmo formulário do seu cargo).
5. O formulário é montado dinamicamente: os fatores exibidos dependem do
   cargo da pessoa avaliada (14 fatores para Empregado, 15 para Gestor,
   11 para Superintendente — já carregados no seed a partir dos formulários
   reais da empresa).
6. As respostas podem ser salvas como **rascunho** ou **concluídas**.

## 1. Criar o projeto no Supabase

1. Crie um projeto em https://supabase.com
2. Vá em **SQL Editor** e rode, nesta ordem:
   - `sql/001_schema.sql` (cria as tabelas)
   - `sql/002_seed_fatores.sql` (cadastra os 3 formulários e seus fatores,
     já com o texto oficial extraído dos seus documentos, e cria o ciclo 2026)
   - `sql/003_setores.sql` (cria a tabela de setores/departamentos e vincula
     aos funcionários; já vem com alguns setores de exemplo — edite/apague
     conforme a estrutura real da empresa)
3. Vá em **Project Settings → Database → Connection string → URI** e copie
   a connection string. Como o projeto roda no Vercel (serverless), use o
   modo **"Transaction Pooling"** (porta `6543`), não o "Session pooling" —
   em serverless cada request pode subir uma função nova, então o modo
   transaction evita abrir conexão nova toda hora e reduz o consumo de
   egress/conexões no Supabase.

## 2. Configurar o projeto local

```bash
cd avaliacao_desempenho
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edite o .env e cole sua DATABASE_URL do Supabase
```

## 3. Cadastrar funcionários e vínculos

Duas opções:

**a) Pela interface** — acesse `/admin/setores` para cadastrar os setores/
departamentos, `/admin/funcionarios` para os funcionários (escolhendo o
setor no próprio formulário) e `/admin/vinculos` para definir quem avalia
quem. Tudo pode ser feito um a um.

**b) Importando planilha** — nas telas de funcionários e vínculos existe um
formulário de importação `.xlsx`/`.csv`. Modelos prontos em `exemplos/`:

- `exemplos/funcionarios_exemplo.csv` — colunas `nome, cargo, setor, email, matricula`
  (cargo deve ser exatamente `Empregado`, `Gestor` ou `Superintendente`; o
  setor é opcional e **criado automaticamente** se ainda não existir)
- `exemplos/vinculos_exemplo.csv` — colunas `avaliado, avaliador` (nomes
  exatamente como cadastrados nos funcionários)

> Dica: você pode gerar esses CSVs a partir da sua planilha "base de vidas"
> e do documento "avaliado x avaliador" que já existem hoje — bastando
> mapear as colunas para esse formato.

## 4. Rodar a aplicação

```bash
python run.py
```

Acesse http://localhost:5000

## Estrutura do projeto

```
avaliacao_desempenho/
├── app/
│   ├── config.py            # configuração (lê o .env)
│   ├── extensions.py        # instância do SQLAlchemy
│   ├── models.py            # tabelas: Funcionario, Cargo, Formulario, Fator,
│   │                         # CicloAvaliacao, VinculoAvaliacao, Avaliacao, RespostaFator
│   ├── routes/
│   │   ├── main.py          # tela inicial e seleção de gestor/colaborador
│   │   ├── avaliacoes.py    # formulário de avaliação (preencher/salvar)
│   │   └── admin.py         # cadastro de funcionários, vínculos e ciclos
│   ├── templates/           # HTML (Jinja2)
│   └── static/css/          # estilo
├── sql/
│   ├── 001_schema.sql       # schema completo do banco
│   └── 002_seed_fatores.sql # formulários e fatores reais + ciclo 2026
├── exemplos/                # CSVs modelo para importação em lote
├── requirements.txt
├── run.py
└── .env.example
```

## Próximos passos sugeridos (não incluídos ainda)

- **Login/autenticação** — hoje qualquer pessoa pode selecionar qualquer
  nome na lista. Para produção, recomendo usar o **Supabase Auth**
  (e-mail/senha ou magic link) e restringir: um gestor só pode acessar a
  lista de quem ele mesmo avalia; um empregado só acessa a própria autoavaliação.
- **Exportar avaliação em PDF** — gerar o mesmo layout do formulário atual
  para impressão/assinatura.
- **Dashboard de acompanhamento pelo RH** — % de avaliações concluídas por
  área, prazos, etc.
- **Histórico multi-exercício** — comparar desempenho do mesmo funcionário
  ano a ano (o modelo de dados já suporta isso, pois tudo é vinculado ao `ciclo_id`).
- **Notificação por e-mail** — lembrar gestores/empregados com avaliação pendente.

Posso implementar qualquer um desses itens em seguida — é só escolher por
onde continuar.


https://sistema-avaliacao-desempenho-psi.vercel.app/
