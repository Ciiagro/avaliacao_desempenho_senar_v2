-- Progressão de nível: guarda o histórico de notas de exercícios anteriores
-- ao sistema (importado por planilha), o "ponteiro" de onde o par de anos
-- de cada funcionário deve ser contado, e o registro (auditável) de
-- progressões efetivadas e de eventos que reiniciam a contagem (ex: mudança
-- de função).

-- Notas/conceitos de exercícios que existiram ANTES do sistema (hoje: 2023
-- e 2024). Para exercícios que já rodam dentro do sistema, a nota é sempre
-- calculada na hora a partir de Avaliacao (auto/gestor), igual já acontece
-- em resultados_finais — não se guarda nota duplicada aqui.
CREATE TABLE IF NOT EXISTS historico_pre_sistema (
    id SERIAL PRIMARY KEY,
    funcionario_id UUID NOT NULL REFERENCES funcionarios(id),
    exercicio INTEGER NOT NULL,
    nota NUMERIC(4, 2) NOT NULL,
    origem TEXT NOT NULL DEFAULT 'importado', -- 'importado' | 'manual'
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (funcionario_id, exercicio)
);

-- O "ponteiro": a partir de qual exercício o par de progressão de cada
-- funcionário deve ser contado. Para o histórico pré-sistema, esse valor
-- vem da planilha (decidido pelo RH, porque só ele sabe o que já foi usado
-- antes do sistema existir). A partir daqui, o próprio sistema mantém esse
-- ponteiro andando conforme progressões são efetivadas e eventos ocorrem.
CREATE TABLE IF NOT EXISTS progressao_ponto_partida (
    funcionario_id UUID PRIMARY KEY REFERENCES funcionarios(id),
    exercicio_inicio INTEGER, -- NULL = ainda não determinado (ex.: precisa confirmação do RH)
    observacao TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_por TEXT
);

-- Eventos que reiniciam/adiam a contagem do par (ex.: mudança de função).
-- Tipos previstos hoje: 'mudanca_funcao'. Novos tipos podem ser adicionados
-- sem mudar a estrutura.
CREATE TABLE IF NOT EXISTS eventos_funcionario (
    id SERIAL PRIMARY KEY,
    funcionario_id UUID NOT NULL REFERENCES funcionarios(id),
    tipo TEXT NOT NULL,
    exercicio INTEGER NOT NULL,
    observacao TEXT,
    registrado_por TEXT,
    registrado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Progressões efetivadas (Fase 1: sempre por clique manual da administração).
CREATE TABLE IF NOT EXISTS progressoes (
    id SERIAL PRIMARY KEY,
    funcionario_id UUID NOT NULL REFERENCES funcionarios(id),
    exercicio_inicio INTEGER NOT NULL,
    exercicio_fim INTEGER NOT NULL,
    efetivada_em_exercicio INTEGER NOT NULL,
    nivel_anterior TEXT,
    nivel_novo TEXT,
    decidido_por TEXT,
    decidido_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
