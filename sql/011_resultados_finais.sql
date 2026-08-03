-- Controla, por ciclo + avaliado, se o Resultado Final (autoavaliação x0,30 +
-- avaliação do gestor x0,70) já foi liberado para o próprio empregado ver.
-- A nota em si NÃO é armazenada aqui: é sempre calculada na hora a partir das
-- avaliações "auto" e "gestor" concluídas. Esta tabela só guarda a liberação.

CREATE TABLE IF NOT EXISTS resultados_finais (
    id SERIAL PRIMARY KEY,
    ciclo_id INTEGER NOT NULL REFERENCES ciclos_avaliacao(id),
    avaliado_id UUID NOT NULL REFERENCES funcionarios(id),
    liberado BOOLEAN NOT NULL DEFAULT FALSE,
    liberado_em TIMESTAMPTZ,
    liberado_por TEXT,
    UNIQUE (ciclo_id, avaliado_id)
);
