-- Recurso da avaliação: empregado insatisfeito com o resultado final pede
-- revisão. Fluxo: gestor revê -> (se mantido) comissão encaminha pra
-- presidência -> presidência decide.

ALTER TABLE funcionarios ADD COLUMN IF NOT EXISTS eh_presidencia BOOLEAN NOT NULL DEFAULT FALSE;

-- Grupo fixo de pessoas que compõem a Comissão de Recursos.
CREATE TABLE IF NOT EXISTS comissao_membros (
    id SERIAL PRIMARY KEY,
    funcionario_id UUID NOT NULL UNIQUE REFERENCES funcionarios(id)
);

CREATE TABLE IF NOT EXISTS recursos_avaliacao (
    id SERIAL PRIMARY KEY,
    ciclo_id INTEGER NOT NULL REFERENCES ciclos_avaliacao(id),
    avaliado_id UUID NOT NULL REFERENCES funcionarios(id),
    motivo TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aguardando_gestor',
    resultado_final_em_texto TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Linha do tempo do recurso: abertura, resposta do gestor, encaminhamento
-- da comissão pra presidência, decisão da presidência, aceite do empregado.
CREATE TABLE IF NOT EXISTS recurso_eventos (
    id SERIAL PRIMARY KEY,
    recurso_id INTEGER NOT NULL REFERENCES recursos_avaliacao(id),
    tipo TEXT NOT NULL,
    autor_id UUID REFERENCES funcionarios(id),
    decisao TEXT,
    texto TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Histórico de mudança de nota feita através de um recurso (nunca some o
-- valor antigo).
CREATE TABLE IF NOT EXISTS recurso_revisoes_notas (
    id SERIAL PRIMARY KEY,
    recurso_id INTEGER NOT NULL REFERENCES recursos_avaliacao(id),
    fator_id INTEGER NOT NULL REFERENCES fatores(id),
    nota_anterior INTEGER,
    nota_nova INTEGER NOT NULL,
    alterado_por_id UUID NOT NULL REFERENCES funcionarios(id),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
