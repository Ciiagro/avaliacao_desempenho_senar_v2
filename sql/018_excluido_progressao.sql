-- Marca quando um funcionário está fora da regra de progressão por um
-- motivo que não é "chegou no nível hierárquico máximo" — por exemplo,
-- já foi admitido com um salário/nível alto o suficiente que não faz
-- sentido aplicar a régua do par de anos a ele.
ALTER TABLE progressao_ponto_partida
    ADD COLUMN IF NOT EXISTS excluido_progressao BOOLEAN NOT NULL DEFAULT FALSE;
