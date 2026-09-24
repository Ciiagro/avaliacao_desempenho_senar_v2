-- "Minhas Capacitações": cursos/treinamentos/certificações que o próprio
-- funcionário cadastra sobre si mesmo. O RH (Administração) vê a lista de
-- todo mundo em admin/capacitacoes.

CREATE TABLE IF NOT EXISTS capacitacoes (
    id SERIAL PRIMARY KEY,
    funcionario_id UUID NOT NULL REFERENCES funcionarios(id),
    nome_curso TEXT NOT NULL,
    instituicao TEXT,
    tipo TEXT,
    carga_horaria INTEGER,
    data_inicio DATE,
    data_conclusao DATE,
    observacoes TEXT,
    criado_em TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_capacitacoes_funcionario_id ON capacitacoes(funcionario_id);
