-- ---------------------------------------------------------
-- Prorrogação INDIVIDUAL de prazo (ex: pessoa de férias).
--
-- O prazo do ciclo (ciclos_avaliacao.data_limite_autoavaliacao /
-- data_limite_gestor) continua valendo para todo mundo. Esta tabela guarda
-- exceções: para um avaliador (quem preenche), num ciclo e tipo
-- ('auto' = autoavaliação | 'gestor' = avaliação do gestor), vale esta data
-- em vez da data do ciclo -- se ela for MAIOR que a do ciclo.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS prorrogacoes_prazo (
    id SERIAL PRIMARY KEY,
    ciclo_id INTEGER NOT NULL REFERENCES ciclos_avaliacao(id),
    tipo TEXT NOT NULL,                              -- 'auto' | 'gestor'
    avaliador_id UUID NOT NULL REFERENCES funcionarios(id),
    data_limite DATE NOT NULL,
    motivo TEXT,
    criado_por TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ciclo_id, tipo, avaliador_id)
);
