-- Data em que o funcionário foi desligado da empresa. Preenchida
-- manualmente pelo admin (não é automática ao desmarcar "Ativo").

ALTER TABLE funcionarios
    ADD COLUMN IF NOT EXISTS data_demissao DATE;
