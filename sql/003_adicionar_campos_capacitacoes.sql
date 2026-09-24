-- Migração: Adicionar novos campos à tabela capacitacoes
-- Data: 2026-09-24
-- Descrição: Adiciona campos para status, arquivo de comprovação e valor pago pelo SENAR

ALTER TABLE capacitacoes
ADD COLUMN status VARCHAR(255),
ADD COLUMN arquivo_comprovacao VARCHAR(255),
ADD COLUMN valor_pago_senar NUMERIC(10, 2);

-- Comentários explicativos
COMMENT ON COLUMN capacitacoes.status IS 'Status da capacitação: Concluído ou Em andamento';
COMMENT ON COLUMN capacitacoes.arquivo_comprovacao IS 'Nome do arquivo de comprovação (PDF, JPG ou PNG)';
COMMENT ON COLUMN capacitacoes.valor_pago_senar IS 'Valor pago pelo SENAR para a capacitação';
