-- Quando o recurso é encerrado com a decisão final da presidência (mantida
-- ou com nota alterada), o colaborador precisa dar ciência de que tomou
-- conhecimento dessa decisão. Fica registrado aqui, com data/hora.

ALTER TABLE recursos_avaliacao
    ADD COLUMN IF NOT EXISTS ciente_funcionario BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ciente_funcionario_em TIMESTAMPTZ;
