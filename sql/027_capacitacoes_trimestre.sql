-- Capacitações passam a ser lançadas por trimestre (ano + trimestre 1..4).
-- Os registros antigos são classificados pela data de conclusão, senão pela
-- data de início, senão pela data em que foram cadastrados.

ALTER TABLE capacitacoes
    ADD COLUMN IF NOT EXISTS ano INTEGER,
    ADD COLUMN IF NOT EXISTS trimestre INTEGER;

UPDATE capacitacoes
SET ano = EXTRACT(YEAR FROM COALESCE(data_conclusao, data_inicio, criado_em::date))::int,
    trimestre = EXTRACT(QUARTER FROM COALESCE(data_conclusao, data_inicio, criado_em::date))::int
WHERE ano IS NULL OR trimestre IS NULL;

ALTER TABLE capacitacoes
    ADD CONSTRAINT chk_capacitacoes_trimestre CHECK (trimestre BETWEEN 1 AND 4);

CREATE INDEX IF NOT EXISTS idx_capacitacoes_ano_trimestre ON capacitacoes(ano, trimestre);
