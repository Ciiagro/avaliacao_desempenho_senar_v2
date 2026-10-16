-- Cursos que atravessam varios trimestres (uma linha por trimestre, ligadas por grupo_curso).
-- Pode rodar mais de uma vez sem problema.
ALTER TABLE capacitacoes
    ADD COLUMN IF NOT EXISTS carga_horaria_total INTEGER,
    ADD COLUMN IF NOT EXISTS valor_total_senar NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS grupo_curso UUID,
    ADD COLUMN IF NOT EXISTS previsto BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_capacitacoes_grupo_curso ON capacitacoes (grupo_curso);
-- Para desfazer:
-- ALTER TABLE capacitacoes DROP COLUMN carga_horaria_total, DROP COLUMN valor_total_senar, DROP COLUMN grupo_curso, DROP COLUMN previsto;

-- Conferir se as 4 colunas existem (deve voltar 4 linhas):
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name = 'capacitacoes'
--   AND column_name IN ('carga_horaria_total', 'valor_total_senar', 'grupo_curso', 'previsto');
